import os
import pyaudio
from dotenv import load_dotenv
from deepgram import DeepgramClient, DeepgramClientOptions, SpeakRESTOptions

class LocalPresenter:
    """
    A simple, local-only agent that reads a script and speaks it using Deepgram's TTS.
    This version is corrected to use the modern Deepgram SDK methods.
    """

    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        if not self.api_key or self.api_key == "YOUR_DEEPGRAM_API_KEY_HERE":
            raise ValueError("Please set your DEEPGRAM_API_KEY in the .env file.")
        
        # Initialize Deepgram with the API key
        self.deepgram = DeepgramClient(self.api_key)

        # Initialize PyAudio for speaker output
        self.pyaudio_instance = pyaudio.PyAudio()
        self.stream = self.pyaudio_instance.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=24000, # Aura voices output at 24kHz
            output=True
        )
        print("Audio output stream opened.")

    def _load_script(self, script_path="presentation_script.txt"):
        """Loads the presentation script from a text file."""
        try:
            with open(script_path, 'r') as f:
                return [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            print(f"Error: Script file not found at '{script_path}'")
            return []

    def speak(self, text):
        """Uses Deepgram's TTS to speak a single line of text."""
        try:
            # For the REST API, the source is a simple dictionary
            source = {"text": text}
            
            # Configure TTS options
            options = SpeakRESTOptions(
                model="aura-2-andromeda-en",
                encoding="linear16",
                sample_rate=24000
            )
            
            print(f"\nAgent Speaking: {text}")
            
            # Use the correct modern method: speak.v("1").stream_memory()
            response = self.deepgram.speak.v("1").stream_memory(source, options)
            
            # The audio data is in the .stream attribute of the response
            if response and response.stream:
                self.stream.write(response.stream.getvalue())

        except Exception as e:
            print(f"An error occurred while speaking: {e}")

    def run_presentation(self):
        """Main method to run the entire presentation."""
        script = self._load_script()
        if not script:
            print("Presentation script is empty or could not be loaded. Exiting.")
            return

        print("--- Starting Presentation ---")
        for line in script:
            self.speak(line)
        
        print("\n--- Presentation Finished ---")
        self.shutdown()

    def shutdown(self):
        """Cleans up audio resources."""
        print("Shutting down audio stream.")
        self.stream.stop_stream()
        self.stream.close()
        self.pyaudio_instance.terminate()

if __name__ == "__main__":
    try:
        presenter = LocalPresenter()
        presenter.run_presentation()
    except Exception as e:
        print(f"An error occurred during initialization: {e}")

