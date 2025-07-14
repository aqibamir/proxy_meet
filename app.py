import os
import json
import pyaudio
from dotenv import load_dotenv
from deepgram import DeepgramClient, SpeakRESTOptions

class LocalPresenter:
    """
    A simple, local-only agent that reads a structured JSON script and 
    speaks the talking points using Deepgram's TTS.
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

    def _load_script(self, script_path="presentation_script.json"):
        """Loads the presentation script from a JSON file."""
        try:
            with open(script_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"Error: Script file not found at '{script_path}'")
            return []
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from '{script_path}'")
            return []

    def speak(self, text):
        """Uses Deepgram's TTS to speak a single line of text."""
        try:
            source = {"text": text}
            options = SpeakRESTOptions(
                model="aura-2-andromeda-en",
                encoding="linear16",
                sample_rate=24000
            )
            
            print(f"Agent Speaking: {text}")
            
            response = self.deepgram.speak.v("1").stream_memory(source, options)
            
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

        print("--- Starting Presentation ---\n")
        for slide in script:
            # Simulate displaying the slide content in the console
            print("="*40)
            print(f"Displaying Slide {slide.get('slide_number', 'N/A')}")
            print("="*40)
            print(slide.get('slide_content', 'No content.'))
            print("="*40)
            
            # Speak the corresponding talking points
            self.speak(slide.get("talking_points", ""))
            print("\n") # Add a newline for better readability
        
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