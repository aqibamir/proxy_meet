#!/usr/bin/env python3
"""
generate_minutes.py
Reads the transcript from meeting_transcription.txt, uses OpenAI to generate
summarized meeting minutes, saves them to temp_files/minutes_of_meeting.txt,
and sends an email with the minutes as body text and attachment using Mailtrap SMTP.
The receiver email is provided as a command-line argument.
"""

import os
import logging
import sys
import re
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# ---------- Logging ----------
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("generate_minutes.log")]
)
logger = logging.getLogger(__name__)

# ---------- Env & Config ----------
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MAILTRAP_API_TOKEN = os.getenv("MAILTRAP_API_TOKEN")
TRANSCRIPT_PATH = "temp_files/meeting_transcription.txt"
OUTPUT_DIR = "temp_files"
OUTPUT_PATH = f"{OUTPUT_DIR}/minutes_of_meeting.txt"

# Mailtrap SMTP credentials
SMTP_HOST = "live.smtp.mailtrap.io"
SMTP_PORT = 587
SMTP_USERNAME = "api"
SMTP_PASSWORD = MAILTRAP_API_TOKEN
SENDER = "Private Person <hello@demomailtrap.co>"

# ---------- Helper Functions ----------
def read_transcript() -> str:
    """Read the transcript from meeting_transcription.txt."""
    try:
        with open(TRANSCRIPT_PATH, "r") as f:
            transcript = f.read()
        if not transcript.strip():
            logger.warning("Transcript file is empty")
            return ""
        logger.info("Successfully read transcript")
        return transcript
    except FileNotFoundError:
        logger.error(f"Transcript file not found: {TRANSCRIPT_PATH}")
        raise FileNotFoundError(f"Transcript file not found: {TRANSCRIPT_PATH}")
    except Exception as e:
        logger.error(f"Error reading transcript: {e}")
        raise

def generate_minutes(transcript: str) -> str:
    """Use OpenAI to generate meeting minutes from the transcript."""
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set in environment")
        raise ValueError("OPENAI_API_KEY not set in environment")

    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = (
        "You are an expert at summarizing meetings. Below is a transcript of a Zoom meeting "
        "where a bot (SlideBot) presented slides and answered up to 3 questions in a Q&A session. "
        "Generate concise meeting minutes summarizing the Q&A session, including key questions "
        "asked and answers provided. Exclude SlideBot's presentation content unless referenced "
        "in questions. Format the minutes professionally with sections for Date, Summary, and "
        "Q&A Details. Note that the meeting ended either after 3 questions, a 'bye' command, "
        "or 15 seconds of silence (10s + 5s after a warning). Use the current date: July 31, 2025.\n\n"
        "--- TRANSCRIPT ---\n"
        f"{transcript}\n"
        "--- END ---\n\n"
        "Provide the minutes in plain text, suitable for saving to a file and including in an email."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Generate meeting minutes from the provided transcript."}
            ],
            temperature=0.3,
            max_tokens=1000
        )
        minutes = response.choices[0].message.content.strip()
        logger.info("Successfully generated meeting minutes")
        return minutes
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        raise

def save_minutes(minutes: str):
    """Save the meeting minutes to temp_files/minutes_of_meeting.txt."""
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(OUTPUT_PATH, "w") as f:
            f.write(minutes)
        logger.info(f"Meeting minutes saved to {OUTPUT_PATH}")
    except Exception as e:
        logger.error(f"Error saving meeting minutes: {e}")
        raise

def extract_email(receiver: str) -> str:
    """Extract email address from 'Name <email@domain.com>' format."""
    match = re.search(r'<(.+?)>', receiver) or re.search(r'(\S+@\S+\.\S+)', receiver)
    if match:
        return match.group(1)
    logger.error(f"Invalid email format: {receiver}")
    raise ValueError(f"Invalid email format: {receiver}")

def send_email(minutes: str, receiver: str):
    """Send an email with the meeting minutes as body text and attachment using Mailtrap."""
    if not SMTP_PASSWORD:
        logger.error("MAILTRAP_API_TOKEN not set in environment")
        raise ValueError("MAILTRAP_API_TOKEN not set in environment")

    # Create email message
    msg = MIMEMultipart()
    msg['From'] = SENDER
    msg['To'] = receiver
    msg['Subject'] = "Meeting Minutes - July 31, 2025"

    # Add minutes to email body
    body = (
        "Dear Recipient,\n\n"
        "Attached are the minutes from the Zoom meeting held on July 31, 2025. "
        "The minutes summarize the Q&A session following the SlideBot presentation. "
        "The full text is also included below for your convenience.\n\n"
        f"{minutes}\n\n"
        "Best regards,\nSlideBot"
    )
    msg.attach(MIMEText(body, 'plain'))

    # Attach minutes file
    try:
        with open(OUTPUT_PATH, "rb") as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header(
            'Content-Disposition',
            f'attachment; filename=minutes_of_meeting.txt'
        )
        msg.attach(part)
    except FileNotFoundError:
        logger.error(f"Minutes file not found for attachment: {OUTPUT_PATH}")
        raise FileNotFoundError(f"Minutes file not found for attachment: {OUTPUT_PATH}")

    # Send email using Mailtrap
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SENDER, extract_email(receiver), msg.as_string())
        logger.info(f"Email sent successfully to {receiver}")
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        raise

# ---------- Main Execution ----------
def main():
    try:
        
        receiver = "aqibamirdev@gmail.com"
        logger.info(f"Using receiver email: {receiver}")

        # Read transcript
        transcript = read_transcript()
        if not transcript:
            print("No transcript content to process. Exiting.")
            return

        # Generate minutes
        minutes = generate_minutes(transcript)

        # Save minutes
        save_minutes(minutes)

        # Send email
        send_email(minutes, receiver)
        print(f"Meeting minutes generated, saved to {OUTPUT_PATH}, and emailed to {receiver}")

    except Exception as e:
        print(f"Error generating or sending minutes: {e}")
        logger.error(f"Main execution failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()