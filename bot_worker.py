#!/usr/bin/env python3
"""
bot_worker.py
Bot joins a Zoom call with:
  - camera = live slide deck (presentation.pptx exported to PNG)
  - audio = spoken talking points (JSON + TTS)
Slides advance as soon as the TTS audio finishes. After the presentation,
it processes up to 3 participant questions using Groq LLM for answers,
waiting 10 seconds for questions, issuing a warning after silence, and leaving
after 5 more seconds of silence or after 3 questions with a cost-related message.
A new meeting transcription file is created each run, including both participant
and bot utterances, saved locally to meeting_transcription.txt.
When the meeting ends, it creates a meeting_ended.flag file to notify the Streamlit app.
"""

import asyncio
import base64
import os
import shutil
import subprocess
import time
import sys
import logging
from pathlib import Path
from typing import List
import json
from aiohttp import web
import requests
from pydub import AudioSegment
from deepgram import DeepgramClient, SpeakRESTOptions
from groq import Groq
from local_presenter import LocalPresenter
from dotenv import load_dotenv
import tempfile

# ---------- Logging ----------
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("bot_worker.log")]
)
logger = logging.getLogger(__name__)

# ---------- Env & Config ----------
load_dotenv()

API_KEY = os.getenv("RECALL_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SLIDE_SERVER_URL = os.getenv("SLIDE_SERVER_URL", "https://e92c4811c3d1.ngrok-free.app")
BASE = "https://us-west-2.recall.ai/api/v1"
PPTX_PATH = "temp_files/presentation.pptx"
SLIDES_PORT = 3443
AUDIO_DIR = "audio_files"
os.makedirs(AUDIO_DIR, exist_ok=True)

# ---------- Recall helpers ----------
def _post(path: str, payload: dict):
    headers = {"Authorization": f"Token {API_KEY}", "ngrok-skip-browser-warning": "true"}
    r = requests.post(BASE + path, json=payload, headers=headers)
    logger.info(f"POST {path}: {r.status_code}")
    if not r.ok:
        logger.error(f"Response content: {r.text}")
    r.raise_for_status()
    return r.json()

def _get(path: str):
    headers = {"Authorization": f"Token {API_KEY}", "ngrok-skip-browser-warning": "true"}
    r = requests.get(BASE + path, headers=headers)
    logger.info(f"GET {path}: {r.status_code}")
    r.raise_for_status()
    return r.json()

def _delete(path: str):
    headers = {"Authorization": f"Token {API_KEY}", "ngrok-skip-browser-warning": "true"}
    r = requests.delete(BASE + path, headers=headers)
    logger.info(f"DELETE {path}: {r.status_code}")
    if not r.ok:
        logger.error(f"Response content: {r.text}")
    r.raise_for_status()
    return r.json()

# ---------- PNG Slide Server ----------
class PNGSlideServer:
    def __init__(self, pptx_path: str, port: int = 3443):
        self.port = port
        self.pptx_path = Path(pptx_path)
        self.current = 0
        self.png_paths: List[str] = []
        self.static_dir = None
        self.app = None
        self.transcriptions = []  # List to store all transcriptions
        self._export_pngs()
        self._prepare_static()

    def _export_pngs(self) -> None:
        if not self.pptx_path.exists():
            raise FileNotFoundError(f"PPTX file not found: {self.pptx_path}")

        tmp_dir = Path(tempfile.mkdtemp(prefix="slides_"))
        self.tmp_dir = tmp_dir

        # PPTX → PDF
        pdf_path = tmp_dir / "presentation.pdf"
        cmd = [
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(tmp_dir),
            str(self.pptx_path),
        ]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.debug(f"LibreOffice stdout: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"LibreOffice failed: {e.stderr}")
            raise RuntimeError(f"LibreOffice PDF export failed: {e.stderr}")

        # PDF → PNGs
        cmd = [
            "pdftoppm", "-png", str(pdf_path), str(tmp_dir / "slide")
        ]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.debug(f"pdftoppm stdout: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"pdftoppm failed: {e.stderr}")
            raise RuntimeError(f"pdftoppm conversion failed: {e.stderr}")

        self.png_paths = sorted(str(p) for p in tmp_dir.glob("slide-*.png"))
        if not self.png_paths:
            raise RuntimeError("No PNGs generated")
        logger.info(f"✅ Exported {len(self.png_paths)} PNGs")

    def _prepare_static(self):
        self.static_dir = Path(tempfile.mkdtemp(prefix="static_"))
        for idx, src in enumerate(self.png_paths):
            shutil.copy2(src, self.static_dir / f"{idx}.png")
        logger.info(f"Static dir ready → {self.static_dir}")

    def cleanup(self):
        if self.static_dir and self.static_dir.exists():
            shutil.rmtree(self.static_dir, ignore_errors=True)
            logger.info(f"Cleaned up static dir: {self.static_dir}")
        if self.tmp_dir and self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
            logger.info(f"Cleaned up slides dir: {self.tmp_dir}")

    async def start(self, question_queue: asyncio.Queue, bot_participant_id: str, presenter) -> None:
        self.app = web.Application()
        self.app['question_queue'] = question_queue
        self.app['bot_participant_id'] = bot_participant_id
        self.app['presenter'] = presenter
        self.app.router.add_get("/", self._index)
        self.app.router.add_get("/next", self._next_handler)
        self.app.router.add_get("/current_slide", self._current_slide)
        self.app.router.add_post("/transcript", self.transcription_handler)
        self.app.router.add_static("/static", self.static_dir)

        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()
        logger.info(f"PNG slide server running on {SLIDE_SERVER_URL}")

    async def transcription_handler(self, request):
        """Handle incoming transcription webhooks and print transcriptions in real-time."""
        try:
            data = await request.json()
            logger.info(f"Full webhook payload: {json.dumps(data, indent=2)}")
            
            if data.get('event') in ['transcript.data', 'transcript.partial_data']:
                transcript_data = data.get('data', {}).get('data', {})
                words = transcript_data.get('words', [])
                
                if words:
                    text = " ".join(word['text'] for word in words)
                    participant = transcript_data.get('participant', {})
                    participant_name = participant.get('name', 'Unknown')
                    start_time = words[0].get('start_timestamp', {}).get('relative', 0.0)
                    
                    if not participant_name.startswith('SlideBot'):
                        print(f"[Transcription] {participant_name} at {start_time:.2f}s: {text}")
                        logger.info(f"Received transcription: {text}")
                        await self.app['question_queue'].put(text)
                        self.transcriptions.append(f"{participant_name} at {start_time:.2f}s: {text}")
                    else:
                        logger.debug(f"Ignored bot transcription: {text}")
                else:
                    logger.debug("No words in transcription data")
            else:
                logger.debug(f"Ignored webhook event: {data.get('event')}")
            
            return web.Response(status=200)
        except Exception as e:
            logger.error(f"Error processing webhook: {str(e)}")
            return web.Response(status=500)
    
    async def _index(self, _):
        total = len(self.png_paths)
        html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Slide Deck</title>
  <style>
    html,body{{margin:0;height:100%;background:#000;display:flex;align-items:center;justify-content:center}}
    img{{width:100%;height:100%;object-fit:contain}}
    #controls{{position:fixed;top:20px;left:20px;color:#fff;font-family:sans-serif}}
  </style>
</head>
<body>
  <div id="controls">
    <button onclick="nextSlide()" {'style="display:none"' if total <= 1 else ''}>Next</button>
    <span id="counter">1 / {total}</span>
  </div>
  <img id="slide" src="/static/0.png" alt="slide">
  <script>
    let idx = 0;
    const total = {total};
    const update = data => {{
      idx = data.slide;
      document.getElementById('slide').src = `/static/${{idx}}.png`;
      document.getElementById('counter').textContent = `${{idx + 1}} / {total}`;
      console.log('Slide →', idx);
    }};
    async function nextSlide() {{
      const r = await fetch('/next');
      update(await r.json());
    }}
    window.advanceSlide = () => fetch('/next').then(r => r.json()).then(update);
    setInterval(async () => {{
      try {{
        const r = await fetch('/current_slide');
        const data = await r.json();
        if (data.slide !== idx) {{
          update(data);
        }}
      }} catch (e) {{
        console.error('Polling error:', e);
      }}
    }}, 1000);
  </script>
</body>
</html>"""
        return web.Response(text=html, content_type="text/html")

    async def _next_handler(self, _):
        self.current = (self.current + 1) % len(self.png_paths)
        logger.info(f"Advance to slide {self.current}")
        return web.json_response({"slide": self.current})

    async def _current_slide(self, _):
        return web.json_response({"slide": self.current})

    async def advance(self, n: int):
        self.current = n % len(self.png_paths)
        logger.info(f"Jump to slide {self.current}")
        return {"slide": self.current}

# ---------- ZoomPresenter ----------
class ZoomPresenter(LocalPresenter):
    def __init__(self, bot_id: str, png_server: PNGSlideServer, question_queue: asyncio.Queue, recording_start_time: float):
        super().__init__()
        self.bot_id = bot_id
        self.png_server = png_server
        self.question_queue = question_queue
        self.SAMPLE_RATE_OUT = 16_000
        self.slide_idx = 0
        self.max_slides = len(png_server.png_paths) - 1
        self.speaking_periods = []
        self.recording_start_time = recording_start_time
        self.groq_client = Groq(api_key=GROQ_API_KEY)
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self):
        """Build system prompt with presentation context."""
        presentation_context = json.dumps(self._load_script(), indent=2)
        return (
            "You just finished a presentation. Answer questions based on the "
            "following slide content and your general knowledge:\n\n"
            "--- SLIDES ---\n"
            f"{presentation_context}\n"
            "--- END ---"
        )

    async def speak(self, text: str):
        if not text.strip():
            return
        logger.info(f"[TTS] {text}")

        # Log bot utterance to transcriptions
        start_time = time.time() - self.recording_start_time
        self.png_server.transcriptions.append(f"SlideBot at {start_time:.2f}s: {text}")
        print(f"[Bot Transcription] SlideBot at {start_time:.2f}s: {text}")

        dg = DeepgramClient(api_key=DEEPGRAM_API_KEY)
        opts = SpeakRESTOptions(
            model="aura-asteria-en",
            encoding="linear16",
            sample_rate=self.SAMPLE_RATE_OUT,
        )
        try:
            audio_bytes = await asyncio.to_thread(
                lambda: dg.speak.rest.v("1").stream_memory({"text": text}, opts).stream.read()
            )
        except Exception as e:
            logger.error(f"TTS failed: {e}")
            return

        wav_path = f"{AUDIO_DIR}/tmp_{time.time()}.wav"
        mp3_path = wav_path.replace(".wav", ".mp3")

        try:
            with open(wav_path, "wb") as f:
                f.write(audio_bytes)
            audio = AudioSegment.from_wav(wav_path)
            audio.export(mp3_path, format="mp3")

            b64 = base64.b64encode(open(mp3_path, "rb").read()).decode()
            start_time = time.time() - self.recording_start_time
            _post(f"/bot/{self.bot_id}/output_audio/", {"kind": "mp3", "b64_data": b64})
            dur = len(audio) / 1000.0
            await asyncio.sleep(dur + 1)
            end_time = start_time + dur
            self.speaking_periods.append((start_time, end_time))
            logger.debug(f"Speaking period added: {start_time} to {end_time}")

            self.slide_idx = min(self.slide_idx + 1, self.max_slides)
            await self._change_slide(self.slide_idx)
        finally:
            if os.path.exists(wav_path):
                os.remove(wav_path)
            if os.path.exists(mp3_path):
                os.remove(mp3_path)

    async def _change_slide(self, n: int):
        if n < 0 or n >= len(self.png_server.png_paths):
            logger.warning(f"Invalid slide index: {n}")
            return
        await self.png_server.advance(n)
        logger.info(f"Changed to slide {n}")

    async def run_presentation(self):
        script = self._load_script()
        for slide in script:
            await self.speak(slide.get("talking_points", ""))
        await self.run_qa_session()

    async def run_qa_session(self):
        """Run the Q&A session, answering up to 3 questions with LLM."""
        logger.info("Starting Q&A session")
        await self.speak("Any questions?")
        silence_duration = 10  # Seconds to wait for a question
        warning_duration = 5  # Seconds to wait after warning
        last_speech_time = time.time()
        warning_issued = False
        question_count = 0  # Track number of questions answered

        while question_count < 3:
            try:
                question = await asyncio.wait_for(self.question_queue.get(), timeout=silence_duration if not warning_issued else warning_duration)
                logger.info(f"Processing question: {question}")
                
                warning_issued = False
                last_speech_time = time.time()
                
                # Check for goodbye phrase
                if "bye" in question.lower():
                    await self.speak("You're welcome. Goodbye!")
                    break
                
                # Generate and speak LLM response
                response = await self.get_llm_response(question)
                await self.speak(response)
                self.question_queue.task_done()
                question_count += 1
                
                # Check if max questions reached
                if question_count >= 3:
                    await self.speak("Due to cost issues, we can only answer three questions for now. Goodbye!")
                    break
                
                # Prompt for next question
                await self.speak("Anything else?")
                self._save_transcription()
                
            except asyncio.TimeoutError:
                if not warning_issued and time.time() - last_speech_time >= silence_duration:
                    warning_message = "If there are no more questions, I will leave in 5 seconds."
                    logger.info(f"Issuing warning: {warning_message}")
                    await self.speak(warning_message)
                    last_speech_time = time.time()
                    warning_issued = True
                elif warning_issued and time.time() - last_speech_time >= warning_duration:
                    logger.info("Silence detected after warning, ending session")
                    break
                
                self._save_transcription()

        if question_count < 3:
            await self.speak("Thanks for attending. Goodbye!")
        logger.info("Q&A session ended")
        self._save_transcription()

    async def get_llm_response(self, question: str) -> str:
        """Generate a response using Groq LLM."""
        try:
            resp = await asyncio.to_thread(
                self.groq_client.chat.completions.create,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": question},
                ],
                model="llama3-8b-8192",
            )
            return resp.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return "Sorry, I’m having trouble answering right now."

    def _save_transcription(self):
        """Save transcriptions to a file."""
        if not self.png_server.transcriptions:
            return
        try:
            with open("temp_files/meeting_transcription.txt", "a") as f:
                for transcription in self.png_server.transcriptions:
                    f.write(f"{transcription}\n")
            logger.info("Transcriptions saved to meeting_transcription.txt")
            self.png_server.transcriptions.clear()
        except Exception as e:
            logger.error(f"Error saving transcriptions: {e}")

# ---------- Bot Runner ----------
async def run_bot(meeting_url: str, email: str = None):
    bot_id = None
    try:
        # Clear the transcription file at the start of each run
        try:
            with open("temp_files/meeting_transcription.txt", "w") as f:
                f.write("")  # Create or overwrite with empty content
            logger.info("Cleared meeting_transcription.txt for new run")
        except Exception as e:
            logger.error(f"Error clearing transcription file: {e}")

        question_queue = asyncio.Queue()
        png_server = PNGSlideServer(PPTX_PATH, SLIDES_PORT)
        recording_start_time = time.time()
        presenter = ZoomPresenter(None, png_server, question_queue, recording_start_time)
        server_task = asyncio.create_task(png_server.start(question_queue, None, presenter))
        await asyncio.sleep(1)

        bot = _post("/bot", {
            "meeting_url": meeting_url,
            "bot_name": "SlideBot",
            "output_media": {
                "camera": {
                    "kind": "webpage",
                    "config": {"url": SLIDE_SERVER_URL}
                }
            },
            "variant": {"zoom": "web_4_core"},
            "recording_config": {
                "transcript": {
                    "provider": {
                        "deepgram_streaming": {
                            "model": "nova-3",
                            "language": "en",
                            "interim_results": True,
                            "endpointing": "10"
                        }
                    }
                },
                "realtime_endpoints": [
                    {
                        "type": "webhook",
                        "url": f"{SLIDE_SERVER_URL}/transcript",
                        "events": ["transcript.data"]
                    }
                ]
            }
        })
        bot_id = bot["id"]
        logger.info(f"Bot {bot_id} created")
        presenter.bot_id = bot_id
        presenter.recording_start_time = time.time()

        for _ in range(30):
            bot_data = _get(f"/bot/{bot_id}")
            if not bot_data.get("status_changes"):
                logger.warning("No status changes yet")
                await asyncio.sleep(2)
                continue
            status = bot_data["status_changes"][-1]["code"]
            logger.info(f"Status: {status}")
            if status == "in_call_recording":
                presenter.recording_start_time = time.time()
                break
            await asyncio.sleep(2)
        else:
            raise TimeoutError("Bot never entered call")

        presentation_task = asyncio.create_task(presenter.run_presentation())
        await presentation_task

        # Create flag file to notify Streamlit app
        try:
            os.makedirs("temp_files", exist_ok=True)
            with open("temp_files/meeting_ended.flag", "w") as f:
                f.write("Meeting ended")
            logger.info("Created meeting_ended.flag to notify Streamlit app")
        except Exception as e:
            logger.error(f"Error creating meeting_ended.flag: {e}")

    except Exception as e:
        logger.error(f"Error in run_bot: {e}")
        raise
    finally:
        try:
            if bot_id:
                _delete(f"/bot/{bot_id}")
                logger.info(f"Bot {bot_id} instructed to leave")
        except Exception as e:
            logger.warning(f"Could not instruct bot to leave: {e}")
        try:
            png_server.cleanup()
        except Exception as e:
            logger.warning(f"Could not clean up temporary files: {e}")
        if 'server_task' in locals():
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass

# ---------- Main Execution ----------
async def main():
    meeting_url = sys.argv[1] if len(sys.argv) > 1 else \
        "https://us05web.zoom.us/j/83464337978?pwd=I5M6BDqDgHvSnZEakWBOtaAFhFl76K.1"
    await run_bot(meeting_url)

if __name__ == "__main__":
    asyncio.run(main())