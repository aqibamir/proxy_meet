#!/usr/bin/env python3
"""
bot_worker.py
Bot joins a Zoom call with:
  - camera = live slide deck (presentation.pptx exported to PNG)
  - audio  = spoken talking points (JSON + TTS)
Slides advance as soon as the TTS audio finishes.
"""

import asyncio
import base64
import os
import shutil
import subprocess
import tempfile
import threading
import time
import sys
import logging
from pathlib import Path
from typing import List

import requests
from aiohttp import web
from pydub import AudioSegment
from deepgram import DeepgramClient, SpeakRESTOptions
from local_presenter import LocalPresenter
from dotenv import load_dotenv

# ---------- Logging ----------
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("bot_worker.log")]
)
logger = logging.getLogger(__name__)

# ---------- Synchronous Wrapper for Streamlit ----------
def join_and_present(zoom_url):
    """Join a Zoom meeting and present slides using the bot.

    Args:
        zoom_url (str): The Zoom meeting URL to join.
    """
    try:
        logger.info(f"Starting bot for URL: {zoom_url}")
        asyncio.run(run_bot(zoom_url))
    except Exception as e:
        logger.error(f"Error in join_and_present: {e}")
        raise

# ---------- Env & Config ----------
load_dotenv()

API_KEY          = os.getenv("RECALL_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
SLIDE_SERVER_URL = os.getenv("SLIDE_SERVER_URL", "https://c151b1607221.ngrok-free.app")
BASE             = "https://us-west-2.recall.ai/api/v1"
PPTX_PATH        = "temp_files/presentation.pptx"
SLIDES_PORT      = 3443
AUDIO_DIR        = "audio_files"
os.makedirs(AUDIO_DIR, exist_ok=True)

# ---------- Recall helpers ----------
def _post(path: str, payload: dict):
    headers = {"Authorization": f"Token {API_KEY}", "ngrok-skip-browser-warning": "true"}
    r = requests.post(BASE + path, json=payload, headers=headers)
    logger.info(f"POST {path}: {r.status_code}")
    r.raise_for_status()
    return r.json()

def _get(path: str):
    headers = {"Authorization": f"Token {API_KEY}", "ngrok-skip-browser-warning": "true"}
    r = requests.get(BASE + path, headers=headers)
    logger.info(f"GET {path}: {r.status_code}")
    r.raise_for_status()
    return r.json()

# ---------- PNG Slide Server (mini slide_final.py embedded) ----------
class PNGSlideServer:
    """
    Convert PPTX → PDF → PNGs and serve them via aiohttp.
    """
    def __init__(self, pptx_path: str, port: int = 3443):
        self.port = port
        self.pptx_path = Path(pptx_path)
        self.current = 0
        self.png_paths: List[str] = []
        self.static_dir = None
        self._export_pngs()
        self._prepare_static()

    def _export_pngs(self) -> None:
        if not self.pptx_path.exists():
            raise FileNotFoundError(f"PPTX file not found: {self.pptx_path}")

        tmp_dir = Path(tempfile.mkdtemp(prefix="slides_"))
        self.tmp_dir = tmp_dir  # Store for cleanup

        # Step 1: PPTX → PDF
        pdf_path = tmp_dir / "presentation.pdf"
        cmd = [
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",  # Adjust for your system
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

        # Step 2: PDF → PNGs
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
        logger.info(f"✅ Exported {len(self.png_paths)} PNGs: {[p.name for p in tmp_dir.glob('slide-*.png')]}")

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

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_get("/next", self._next_handler)
        app.router.add_get("/current_slide", self._current_slide)  # New endpoint
        app.router.add_static("/static", self.static_dir)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()
        logger.info(f"PNG slide server running on {SLIDE_SERVER_URL}")

    async def _index(self, _):
        total = len(self.png_paths)
        html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Slide Deck</title>
  <style>
    html,body{{margin:0;height:100%;background:#000;display:flex;align-items:center;justify-content:center}}
    img{{width:100%;height:100 Ascending order
100%;object-fit:contain}}
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
    // Expose for remote control
    window.advanceSlide = () => fetch('/next').then(r => r.json()).then(update);
    // Poll for slide changes
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
    def __init__(self, bot_id: str, png_server: PNGSlideServer):
        super().__init__()
        self.bot_id = bot_id
        self.png_server = png_server
        self.SAMPLE_RATE_OUT = 16_000
        self.slide_idx = 0
        self.max_slides = len(png_server.png_paths) - 1

    async def speak(self, text: str):
        if not text.strip():
            return
        logger.info(f"[TTS] {text}")

        dg = DeepgramClient(api_key=DEEPGRAM_API_KEY)
        opts = SpeakRESTOptions(
            model="aura-asteria-en",  # Updated model for better TTS
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
            AudioSegment.from_wav(wav_path).export(mp3_path, format="mp3")

            b64 = base64.b64encode(open(mp3_path, "rb").read()).decode()
            _post(f"/bot/{self.bot_id}/output_audio/", {"kind": "mp3", "b64_data": b64})

            dur = len(AudioSegment.from_mp3(mp3_path)) / 1000.0
            await asyncio.sleep(dur + 1)

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
        await self.speak("Any questions?")
        await self.speak("Thanks for attending. Goodbye!")

# ---------- Bot Runner ----------
async def run_bot(meeting_url: str):
    bot_id = None
    try:
        png_server = PNGSlideServer(PPTX_PATH, SLIDES_PORT)
        server_task = asyncio.create_task(png_server.start())  # Run server in background
        await asyncio.sleep(1)  # Give server time to start

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
        })
        bot_id = bot["id"]
        logger.info(f"Bot {bot_id} created")

        # Wait until bot is in call
        for _ in range(30):
            bot_data = _get(f"/bot/{bot_id}")
            if not bot_data.get("status_changes"):
                logger.warning("No status changes available yet")
                await asyncio.sleep(2)
                continue
            status = bot_data["status_changes"][-1]["code"]
            logger.info(f"Status: {status}")
            if status == "in_call_recording":
                break
            await asyncio.sleep(2)
        else:
            raise TimeoutError("Bot never entered call")

        presenter = ZoomPresenter(bot_id, png_server)
        presentation_task = asyncio.create_task(presenter.run_presentation())  # Run presentation in background
        await presentation_task  # Wait for presentation to complete

    except Exception as e:
        logger.error(f"Error in run_bot: {e}")
        raise
    finally:
        try:
            if bot_id:
                requests.delete(f"{BASE}/bot/{bot_id}",
                                headers={"Authorization": f"Token {API_KEY}"})
                logger.info(f"Bot {bot_id} deleted")
        except Exception as e:
            logger.warning(f"Could not delete bot: {e}")
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
        "https://us05web.zoom.us/j/86079976337?pwd=kDrCpxvpzMzxURxPiHMKeCnKHjjOOr.1"
    await run_bot(meeting_url)

if __name__ == "__main__":
    asyncio.run(main())  # Run the main coroutine in the main thread's event loop