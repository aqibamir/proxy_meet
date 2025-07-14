"""
LocalPresenter.py
A presentation agent that:
  1. Reads a JSON slide deck,
  2. Speaks the talking points through a virtual audio device,
  3. Listens for questions over the same virtual device,
  4. Answers with LLM-generated speech.

This version uses `sounddevice` + `soundfile` instead of `pyaudio`
to avoid the common “no audio” problems on macOS.
"""

import os
import json
import asyncio
import sounddevice as sd
import soundfile as sf
import numpy as np
from io import BytesIO
from dotenv import load_dotenv
from deepgram import DeepgramClient, SpeakRESTOptions, LiveTranscriptionEvents, LiveOptions
from groq import Groq

# -------------------- Audio helpers --------------------
def select_blackhole_device(kind: str) -> int | None:
    """
    kind = 'input' or 'output'
    Returns the first device whose name contains 'BlackHole'.
    """
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        if "BlackHole".lower() in dev["name"].lower():
            if kind == "input" and dev["max_input_channels"] > 0:
                return idx
            if kind == "output" and dev["max_output_channels"] > 0:
                return idx
    return None


class LocalPresenter:
    def __init__(self):
        load_dotenv()
        self.dg_client = DeepgramClient()
        self.groq_client = Groq()
        self.transcript_queue = asyncio.Queue()

        # ---------------- Audio device selection ----------------
        mic_idx = select_blackhole_device("input")
        speaker_idx = select_blackhole_device("output")
        if mic_idx is None or speaker_idx is None:
            print("\n" + "=" * 60)
            print("ERROR: BlackHole device not found. Install with:")
            print("    brew install blackhole-2ch")
            print("Then set Zoom’s mic & speaker to 'BlackHole 2ch'.")
            print("=" * 60 + "\n")
            print(sd.query_devices())
            raise SystemExit

        self.mic_idx = mic_idx
        self.speaker_idx = speaker_idx
        print(
            f"Using BlackHole: mic device {mic_idx}, speaker device {speaker_idx}"
        )

        # Audio parameters
        self.SAMPLE_RATE_OUT = 24_000  # Deepgram TTS output
        self.SAMPLE_RATE_IN = 16_000   # Deepgram STT input

    # -------------------- Scripted presentation --------------------
    def _load_script(self, script_path="presentation_script.json"):
        try:
            with open(script_path) as f:
                return json.load(f)
        except Exception as e:
            print("Error loading script:", e)
            return []

    async def speak(self, text: str):
        """Generate speech with Deepgram and play via BlackHole."""
        if not text.strip():
            return

        print("Agent speaking:", text)
        source = {"text": text}
        opts = SpeakRESTOptions(
            model="aura-2-andromeda-en",
            encoding="linear16",
            sample_rate=self.SAMPLE_RATE_OUT,
        )

        # Synchronous Deepgram call in thread-pool
        audio_bytes = await asyncio.to_thread(
            lambda: self.dg_client.speak.rest.v("1")
            .stream_memory(source, opts)
            .stream.read()
        )
        audio, sr = sf.read(BytesIO(audio_bytes), dtype="int16")

        # Play via sounddevice
        await asyncio.to_thread(
            sd.play, audio, sr, device=self.speaker_idx, blocking=True
        )

    async def run_presentation(self):
        script = self._load_script()
        if not script:
            print("Empty script. Exiting.")
            return

        print("\n--- Starting Presentation ---\n")
        for slide in script:
            print("=" * 40)
            print(f"Slide {slide.get('slide_number', '?')}")
            print("=" * 40)
            print(slide.get("slide_content", ""))
            print("=" * 40)
            await self.speak(slide.get("talking_points", ""))
            print("\n")

        print("\n--- Presentation finished, starting Q&A ---")
        await self.run_qa_session()

    # -------------------- Q&A Session --------------------
    async def run_qa_session(self):
        stt_task = asyncio.create_task(self.listen_for_questions())

        presentation_context = json.dumps(self._load_script(), indent=2)
        system_prompt = (
            "You just finished a presentation. Answer questions based on the "
            "following slide content and your general knowledge:\n\n"
            "--- SLIDES ---\n"
            f"{presentation_context}\n"
            "--- END ---"
        )

        try:
            while True:
                question = await self.transcript_queue.get()
                if not question:
                    continue
                print("\nUser:", question)

                if "thank you goodbye" in question.lower().strip():
                    await self.speak("You're welcome. Goodbye!")
                    break

                answer = await self.get_llm_response(question, system_prompt)
                await self.speak(answer)
                print("Ready for next question...")

        except asyncio.CancelledError:
            pass
        finally:
            stt_task.cancel()
            try:
                await stt_task
            except asyncio.CancelledError:
                pass

    async def get_llm_response(self, question: str, system: str) -> str:
        try:
            resp = await asyncio.to_thread(
                self.groq_client.chat.completions.create,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": question},
                ],
                model="llama3-8b-8192",
            )
            return resp.choices[0].message.content
        except Exception as e:
            print("LLM error:", e)
            return "Sorry, I’m having trouble answering right now."

    # -------------------- Speech-to-Text stream --------------------
    async def _on_stt_message(self, _, result, **kwargs):
        transcript = result.channel.alternatives[0].transcript
        if transcript:
            await self.transcript_queue.put(transcript)

    async def listen_for_questions(self):
        dg_conn = self.dg_client.listen.asynclive.v("1")
        dg_conn.on(LiveTranscriptionEvents.Transcript, self._on_stt_message)

        await dg_conn.start(
            LiveOptions(model="nova-2", language="en-US", smart_format=True)
        )
        print("Listening... (say 'thank you goodbye' to exit)")

        def audio_callback(indata, frames, time_, status):
            if status:
                print("input overflow:", status)
            asyncio.create_task(dg_conn.send_bytes(indata.tobytes()))

        try:
            with sd.InputStream(
                samplerate=self.SAMPLE_RATE_IN,
                channels=1,
                dtype="int16",
                device=self.mic_idx,
                callback=audio_callback,
            ):
                while True:
                    await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            pass
        finally:
            await dg_conn.finish()

    # -------------------- graceful shutdown --------------------
    def shutdown(self):
        print("Shutting down audio...")


# -------------------- Entry point --------------------
async def main():
    presenter = None
    try:
        presenter = LocalPresenter()
        await presenter.run_presentation()
    except KeyboardInterrupt:
        print("\nUser interrupted.")
    finally:
        if presenter:
            presenter.shutdown()

if __name__ == "__main__":
    asyncio.run(main())