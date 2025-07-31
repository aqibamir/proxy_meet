# DEMO LINK
https://youtu.be/R7zIVcgdXGU

# Proxy Meet

Proxy Meet is an innovative tool designed to streamline Zoom meetings by automating slide generation and presentation delivery. With Proxy Meet, users can generate professional presentation slides from a prompt or PDF, have a bot join a Zoom meeting to present the slides, handle a Q&A session, and receive summarized meeting minutes afterward—all with minimal manual effort.

## Features

- **Slide Generation**: Create polished PowerPoint slides (.pptx) from a user-provided prompt or extracted PDF content using OpenAI's API.
- **Zoom Bot**: A bot joins Zoom meetings, displays slides as its camera feed, and speaks talking points via text-to-speech (TTS).
- **Q&A Session**: Post-presentation, the bot answers up to three participant questions using the Groq language model.
- **Transcription**: Records the full meeting transcription, capturing both participant and bot interactions.
- **Meeting Minutes**: Generates concise minutes from the transcription and optionally emails them to the user.

## Installation

To set up Proxy Meet locally, follow these steps:

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/yourusername/proxy-meet.git
   cd proxy-meet
   ```

2. **Install Python Dependencies**:
   Ensure you have Python 3.8+ installed, then install the required packages:
   ```bash
   pip install -r requirements.txt
   ```
   This installs key libraries such as `streamlit`, `openai`, `groq`, `deepgram-sdk`, `python-pptx`, and others listed in `requirements.txt`.

3. **Set Up Environment Variables**:
   Create a `.env` file in the project root with the following:
   ```plaintext
   OPENAI_API_KEY=your_openai_api_key
   DEEPGRAM_API_KEY=your_deepgram_api_key
   GROQ_API_KEY=your_groq_api_key
   RECALL_API_KEY=your_recall_api_key
   MAILTRAP_API_TOKEN=your_mailtrap_api_token
   SLIDE_SERVER_URL=https://your-ngrok-url.ngrok-free.app
   ```
   Replace placeholders with your actual API keys and ngrok URL (if applicable).

4. **Install LibreOffice**:
   LibreOffice is required for converting PDFs to slides. Download and install it from [libreoffice.org](https://www.libreoffice.org/). Ensure it’s accessible from the command line.

## Setting Up Accounts

Proxy Meet integrates with several services. You’ll need to create accounts and obtain API keys/tokens for each:

1. **OpenAI**:
   - Sign up at [openai.com](https://openai.com).
   - Navigate to the API section and generate an API key.
   - Add it to your `.env` file as `OPENAI_API_KEY`.

2. **Groq**:
   - Sign up at [groq.com](https://groq.com).
   - Obtain an API key from your account dashboard.
   - Add it to your `.env` file as `GROQ_API_KEY`.

3. **Deepgram**:
   - Sign up at [deepgram.com](https://deepgram.com).
   - Generate an API key in the developer console.
   - Add it to your `.env` file as `DEEPGRAM_API_KEY`.

4. **Recall.ai**:
   - Sign up at [recall.ai](https://recall.ai).
   - Get an API key from your account settings.
   - Add it to your `.env` file as `RECALL_API_KEY`.
   - Note: Recall.ai handles Zoom integration, so no local Zoom client is required.

5. **Mailtrap**:
   - Sign up at [mailtrap.io](https://mailtrap.io).
   - Obtain an API token from the SMTP settings or API section.
   - Add it to your `.env` file as `MAILTRAP_API_TOKEN`.

6. **ngrok** (Optional):
   - Sign up at [ngrok.com](https://ngrok.com).
   - Install ngrok and run it to expose the slide server (default port 3443):
     ```bash
     ngrok http 3443
     ```
   - Copy the generated URL (e.g., `https://your-ngrok-url.ngrok-free.app`) and update `SLIDE_SERVER_URL` in your `.env` file.

## Usage

Proxy Meet is a Streamlit-based application with an intuitive interface. Here’s how to use it:

1. **Run the Streamlit App**:
   Launch the app from the command line:
   ```bash
   streamlit run app.py
   ```
   Replace `app.py` with the actual filename if it differs.

2. **Generate Presentation Slides**:
   - **Input**: Enter a prompt (e.g., "Create a presentation about renewable energy") or upload a PDF (max 200 MB).
   - **Action**: Click "Generate Slides" to create a `.pptx` file.
   - **Output**: Download the presentation from the interface.

3. **Join a Zoom Meeting**:
   - **Input**: Paste a Zoom meeting link (e.g., `https://zoom.us/j/123456789`).
   - **Optional**: Enter an email address to receive meeting minutes.
   - **Options**: Select "Join Now" for immediate start or "Schedule" for a future time.
   - **Action**: Click "Join Meeting" to deploy the bot. It will present slides, narrate them, and manage a Q&A session.

4. **Get Meeting Minutes**:
   - **Action**: After the meeting, click "Check for Minutes" to download the minutes as a `.txt` file.
   - **Email**: If an email was provided, minutes are also emailed automatically.

### Bot Behavior
- **Presentation**: The bot displays slides as its video feed and narrates talking points.
- **Q&A**: Answers up to three questions using Groq, then exits.
- **Exit Conditions**: Leaves after three questions, a "bye" command, or 15 seconds of silence (with a 5-second warning).

## Configuration

- **API Keys**: Ensure all `.env` variables are set correctly.
- **Slide Server**: The server runs on port 3443 by default. If using ngrok, keep it active and update `SLIDE_SERVER_URL`.
- **File Storage**: Slides, transcriptions (`temp_files/meeting_transcription.txt`), and minutes (`temp_files/minutes_of_meeting.txt`) are saved in `temp_files/`.

## Troubleshooting

- **Slide Generation Fails**: Verify LibreOffice is installed and the OpenAI API key is valid.
- **Bot Won’t Join**: Check the Zoom link and Recall API key. Ensure `SLIDE_SERVER_URL` is accessible.
- **Transcription Errors**: Confirm the Deepgram API key and audio input.
- **Email Issues**: Validate the Mailtrap API token and SMTP setup.
- **Logs**: Check `bot_worker.log` and `generate_minutes.log` for detailed error messages.