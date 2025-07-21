#!/usr/bin/env python3
"""
bot_worker.py
Bot joins a Zoom call with:
  - camera = live slide deck (presentation.pptx)
  - audio  = spoken talking points (JSON + TTS)
Slides advance as soon as the TTS audio finishes.
"""

import asyncio
import base64
import io
import os
import time
import requests
from pathlib import Path
from pptx import Presentation
from PIL import Image
from aiohttp import web
from pydub import AudioSegment
from deepgram import DeepgramClient, SpeakRESTOptions
from local_presenter import LocalPresenter
from dotenv import load_dotenv
import threading
import logging
import sys

# ---------- Logging ----------
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("bot_worker.log")]
)
logger = logging.getLogger(__name__)

# ---------- Env & Config ----------
load_dotenv()

API_KEY          = os.getenv("RECALL_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
SLIDE_SERVER_URL = os.getenv("SLIDE_SERVER_URL", "https://1e675d80b1613.ngrok-free.app")

BASE         = "https://us-west-2.recall.ai/api/v1"
PPTX_PATH    = "presentation.pptx"
SLIDES_PORT  = 3443
AUDIO_DIR    = "audio_files"
os.makedirs(AUDIO_DIR, exist_ok=True)

# ---------- Global ----------
connected_websockets = set()          # live WebSocket clients
slides_b64           = []             # base64 PNG frames

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

# ---------- PPTX → PNG ----------
def load_pptx(path=PPTX_PATH):
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    prs = Presentation(path)
    for slide in prs.slides:
        img = Image.new("RGB", (1280, 720), (255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        slides_b64.append(base64.b64encode(buf.getvalue()).decode())
    logger.info(f"Loaded {len(slides_b64)} slides")

# ---------- Slide Server ----------
def build_html():
    imgs = "\n".join(
        f'<img src="data:image/png;base64,{b64}" style="display:none">' for b64 in slides_b64
    )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <style>
    html,body{{margin:0;height:100%;background:#000;display:flex;align-items:center;justify-content:center}}
    img{{width:100%;height:100%;object-fit:contain;display:none}}
    img.active{{display:block}}
  </style>
</head>
<body>
  <div id="slides">{imgs}</div>
  <script>
    let idx = 0;
    const changeSlide = (n) => {{
      if (n < 0 || n >= {len(slides_b64)}) return;
      document.querySelectorAll('#slides img').forEach((img, i) =>
        img.classList.toggle('active', i === n)
      );
      idx = n;
      console.log('Slide →', n);
    }};
    changeSlide(0);

    const ws = new WebSocket(`wss://${{location.host}}/ws`);
    ws.onmessage = (e) => changeSlide(parseInt(e.data, 10));
    ws.onopen    = () => console.log('WS connected');
    ws.onclose   = () => console.log('WS closed');
  </script>
</body>
</html>"""

async def slide_server():
    logger.debug("Entering slide_server")
    try:
        async def index(_):
            return web.Response(text=build_html(), content_type="text/html")

        async def websocket_handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            connected_websockets.add(ws)
            logger.info("WebSocket client connected")
            try:
                async for _ in ws:
                    pass
            finally:
                connected_websockets.discard(ws)
                logger.info("WebSocket client disconnected")
            return ws

        app = web.Application()
        app.router.add_get("/", index)
        app.router.add_get("/ws", websocket_handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", SLIDES_PORT)
        await site.start()
        logger.info(f"Slide server running on {SLIDE_SERVER_URL}")
    except Exception as e:
        logger.error(f"Failed to start slide server: {str(e)}")
        raise
    finally:
        logger.debug("Exiting slide_server")
        
# ---------- ZoomPresenter ----------
class ZoomPresenter(LocalPresenter):
    def __init__(self, bot_id: str):
        super().__init__()
        self.bot_id      = bot_id
        self.SAMPLE_RATE_OUT = 16_000
        self.slide_idx   = 0
        self.max_slides  = len(slides_b64) - 1

    async def speak(self, text: str):
        if not text.strip():
            return
        logger.info(f"[TTS] {text}")

        dg   = DeepgramClient()
        opts = SpeakRESTOptions(
            model="aura-2-andromeda-en",
            encoding="linear16",
            sample_rate=self.SAMPLE_RATE_OUT,
        )
        audio_bytes = await asyncio.to_thread(
            lambda: dg.speak.rest.v("1").stream_memory({"text": text}, opts).stream.read()
        )

        wav_path = f"{AUDIO_DIR}/tmp_{time.time()}.wav"
        mp3_path = wav_path.replace(".wav", ".mp3")

        with open(wav_path, "wb") as f:
            f.write(audio_bytes)
        AudioSegment.from_wav(wav_path).export(mp3_path, format="mp3")

        b64 = base64.b64encode(open(mp3_path, "rb").read()).decode()
        _post(f"/bot/{self.bot_id}/output_audio/", {"kind": "mp3", "b64_data": b64})

        dur = len(AudioSegment.from_mp3(mp3_path)) / 1000.0
        await asyncio.sleep(dur + 1)

        self.slide_idx = min(self.slide_idx + 1, self.max_slides)
        await self._change_slide(self.slide_idx)

        os.remove(wav_path)
        os.remove(mp3_path)

    async def _change_slide(self, n: int):
        if n < 0 or n >= len(slides_b64):
            return
        for ws in connected_websockets:
            await ws.send_str(str(n))
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
    load_pptx()
    await slide_server()

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
        status = _get(f"/bot/{bot_id}")["status_changes"][-1]["code"]
        logger.info(f"Status: {status}")
        if status == "in_call_recording":
            break
        await asyncio.sleep(2)
    else:
        raise TimeoutError("Bot never entered call")

    presenter = ZoomPresenter(bot_id)
    await presenter.run_presentation()

    try:
        requests.delete(f"{BASE}/bot/{bot_id}",
                        headers={"Authorization": f"Token {API_KEY}"})
    except Exception as e:
        logger.warning(f"Could not delete bot: {e}")

# ---------- CLI ----------
def join_and_present(meeting_url: str):
    def run():
        asyncio.run(run_bot(meeting_url))
    threading.Thread(target=run, daemon=False).start()

if __name__ == "__main__":
    meeting_url = sys.argv[1] if len(sys.argv) > 1 else \
        "https://us05web.zoom.us/j/89011877257?pwd=bQuK1kwYk3qNGaACAbuY9DLF7tlNbM.1"
    join_and_present(meeting_url)