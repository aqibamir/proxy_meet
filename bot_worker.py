import asyncio
import base64
import os
import time
import requests
from pydub import AudioSegment
from deepgram import DeepgramClient, SpeakRESTOptions
from local_presenter import LocalPresenter  # Importing the original LocalPresenter
from dotenv import load_dotenv

load_dotenv()
# API Configuration
API_KEY = os.getenv("RECALL_API_KEY")  # Replace with your Recall.ai API key
MEETING = os.getenv("ZOOM_LINK")  # Replace with your Zoom meeting URL
BASE = "https://us-west-2.recall.ai/api/v1"

# Audio Directory
AUDIO_DIR = "audio_files"
os.makedirs(AUDIO_DIR, exist_ok=True)

# ---------- Helpers ----------
def _post(path, payload):
    """Make POST requests to Recall.ai API."""
    r = requests.post(BASE + path, json=payload, headers={"Authorization": f"Token {API_KEY}"})
    r.raise_for_status()
    return r.json()

def _get(path):
    """Make GET requests to Recall.ai API."""
    r = requests.get(BASE + path, headers={"Authorization": f"Token {API_KEY}"})
    r.raise_for_status()
    return r.json()

def convert_wav_to_mp3(wav_path, mp3_path):
    """Convert WAV audio to MP3 using pydub."""
    audio = AudioSegment.from_wav(wav_path)
    audio.export(mp3_path, format="mp3")
    return mp3_path

def encode_audio_to_base64(mp3_path):
    """Encode MP3 file to base64 string."""
    with open(mp3_path, "rb") as f:
        audio_bytes = f.read()
    return base64.b64encode(audio_bytes).decode("utf-8")

def get_audio_duration(mp3_path):
    """Get the duration of an MP3 file in seconds."""
    audio = AudioSegment.from_mp3(mp3_path)
    return len(audio) / 1000  # Convert milliseconds to seconds

# ---------- Zoom Presenter Class ----------
class ZoomPresenter(LocalPresenter):
    def __init__(self, bot_id):
        super().__init__()
        self.bot_id = bot_id
        self.SAMPLE_RATE_OUT = 16000  # Adjusted to a common sample rate for compatibility

    async def speak(self, text: str):
        """Generate audio and send it to the Zoom bot instead of playing locally."""
        if not text.strip():
            return

        print(f"[TTS] Generating speech for: {text}")

        # Generate WAV audio with Deepgram (using inherited dg_client)
        source = {"text": text}
        opts = SpeakRESTOptions(
            model="aura-2-andromeda-en",
            encoding="linear16",
            sample_rate=self.SAMPLE_RATE_OUT,
        )
        audio_bytes = await asyncio.to_thread(
            lambda: self.dg_client.speak.rest.v("1").stream_memory(source, opts).stream.read()
        )

        # Save WAV file temporarily
        wav_filename = f"audio_{time.time()}.wav"
        wav_path = os.path.join(AUDIO_DIR, wav_filename)
        with open(wav_path, "wb") as f:
            f.write(audio_bytes)

        # Convert to MP3
        mp3_filename = f"audio_{time.time()}.mp3"
        mp3_path = os.path.join(AUDIO_DIR, mp3_filename)
        convert_wav_to_mp3(wav_path, mp3_path)

        # Encode to base64
        b64_audio = encode_audio_to_base64(mp3_path)

        # Send audio to bot
        try:
            payload = {"kind": "mp3", "b64_data": b64_audio}
            _post(f"/bot/{self.bot_id}/output_audio/", payload)
            print(f"[AUDIO] Sent audio to bot: {text}")
        except Exception as e:
            print(f"[ERROR] Failed to send audio to bot: {e}")

        # Wait for audio duration plus buffer
        duration = get_audio_duration(mp3_path)
        buffer = 2  # Extra seconds for latency
        await asyncio.sleep(duration + buffer)

        # Clean up temporary files
        os.remove(wav_path)
        os.remove(mp3_path)

    async def run_presentation(self):
        """Run the presentation by speaking each slide's talking points."""
        script = self._load_script()  # Load the script dynamically
        if not script:
            print("Empty script. Exiting.")
            return

        for slide in script:
            talking_points = slide.get("talking_points", "")
            await self.speak(talking_points)

        await self.run_qa_session()

    async def run_qa_session(self):
        """Simplified Q&A session for Zoom."""
        await self.speak("Any questions?")
        await self.speak("Thanks for attending! Goodbye!")
        print("[QA] Q&A session completed.")

# ---------- Main Execution ----------
async def main():
    # Create a silent MP3 for bot initialization
    silent_mp3_path = "silent.mp3"
    if not os.path.exists(silent_mp3_path):
        silent_audio = AudioSegment.silent(duration=1000)  # 1 second of silence
        silent_audio.export(silent_mp3_path, format="mp3")
    silent_b64 = encode_audio_to_base64(silent_mp3_path)

    # Create bot and join Zoom meeting
    bot = _post("/bot", {
        "meeting_url": MEETING,
        "bot_name": "SlideBot",
        "automatic_audio_output": {
            "in_call_recording": {
                "data": {"kind": "mp3", "b64_data": silent_b64}
            }
        }
    })
    bot_id = bot["id"]
    print(f"🤖 Bot created: {bot_id}")

    # Wait until bot is in the meeting
    while True:
        data = _get(f"/bot/{bot_id}")
        changes = data.get("status_changes", [])
        status = changes[-1]["code"] if changes else None
        print(f"⏳ Status: {status}")
        if status == "in_call_recording":
            break
        if status in ("call_ended", "fatal"):
            raise RuntimeError("Bot failed/left")
        await asyncio.sleep(2)

    # Run presentation with Zoom integration
    presenter = ZoomPresenter(bot_id)
    await presenter.run_presentation()

    # Remove bot from meeting
    requests.delete(f"{BASE}/bot/{bot_id}", headers={"Authorization": f"Token {API_KEY}"})
    print("👋 Bot removed from meeting.")

if __name__ == "__main__":
    asyncio.run(main())