import os
import re
import shutil
import tempfile
import threading
import time
import asyncio
from datetime import datetime, timedelta, date
import streamlit as st
from bot_worker import run_bot
from slides_generator_local import generate_local
from generate_minutes import read_transcript, generate_minutes, save_minutes, send_email
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Streamlit page setup
st.set_page_config(page_title="Zoom Slide Bot (Local)", layout="wide")
st.title("📊 Zoom Slide Bot – Local Edition")
st.markdown(
    "Generate presentation slides locally and let the bot join your Zoom meeting. After the meeting, download the minutes or have them emailed to you!"
)

# SECTION 1 – Generate Slides
st.header("1. Generate Presentation Slides")
col1, col2 = st.columns([2, 1])

with col1:
    prompt = st.text_area(
        "📝 Prompt (Optional)",
        height=120,
        placeholder="e.g., Create a presentation about Q3 sales performance...",
        help="Enter a prompt to guide slide generation. Leave blank if using a PDF only."
    )
    pdf_file = st.file_uploader(
        "📄 Upload PDF (Optional)",
        type=["pdf"],
        help="Upload a PDF to generate slides from its content. Max 200 MB."
    )

if st.button("📑 Generate Slides", use_container_width=True):
    if not prompt and not pdf_file:
        st.error("Please provide a prompt or upload a PDF.")
    else:
        with st.spinner("Generating presentation…"):
            tmp_dir = tempfile.mkdtemp()
            output_dir = "temp_files"
            pdf_path = None
            try:
                if pdf_file:
                    pdf_path = os.path.join(tmp_dir, "input.pdf")
                    with open(pdf_path, "wb") as f:
                        f.write(pdf_file.read())
                else:
                    pdf_path = ""

                logger.info("Starting slide generation")
                pptx_path, json_path = generate_local(
                    prompt or "Generate a default presentation",
                    pdf_path,
                    output_dir,
                )

                if not pptx_path or not json_path:
                    st.error("Failed to generate slides: No files produced.")
                    logger.error("Slide generation returned empty file paths")
                    raise ValueError("Slide generation failed")

                with open(pptx_path, "rb") as f:
                    pptx_bytes = f.read()

                st.success("✅ Slides generated successfully! Download below.")
                st.download_button(
                    label="📥 Download Presentation (PPTX)",
                    data=pptx_bytes,
                    file_name="presentation.pptx",
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"Failed to generate slides: {str(e)}")
                logger.error(f"Slide generation error: {str(e)}")
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                logger.info("Cleaned up temporary directory")

st.markdown("---")

# SECTION 2 – Join Zoom Meeting
st.header("2. Join Zoom Meeting")
col3, col4 = st.columns([2, 1])

with col3:
    zoom_url = st.text_input(
        "🔗 Zoom Meeting Link (Required)",
        placeholder="https://zoom.us/j/123456789",
        help="Enter the Zoom meeting link (e.g., https://zoom.us/j/...)."
    )
    email = st.text_input(
        "📧 Email (Optional)",
        placeholder="you@example.com",
        help="Enter your email to receive the meeting minutes after the session."
    )
    join_option = st.radio(
        "⏰ Join Option",
        ["Join Now", "Schedule"],
        help="Choose to join immediately or schedule for later."
    )
    join_time = None
    if join_option == "Schedule":
        with st.expander("Schedule Details"):
            selected_date = st.date_input(
                "📅 Join Date",
                value=date.today(),
                help="Select the date for the bot to join."
            )
            selected_time = st.time_input(
                "⏱ Join Time",
                value=(datetime.now() + timedelta(minutes=1)).time(),
                help="Select the time for the bot to join."
            )
            join_time = datetime.combine(selected_date, selected_time)

def run_bot_in_thread(meeting_url, email):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_bot(meeting_url, email))
    finally:
        loop.close()

if st.button("🤝 Join Meeting", use_container_width=True):
    if not zoom_url:
        st.error("Please provide a Zoom meeting link.")
    elif not re.match(r"https://[a-zA-Z0-9.-]+\.zoom\.us/[a-zA-Z0-9_/?-]+", zoom_url):
        st.warning("The Zoom link format looks invalid. Please ensure it starts with https://*.zoom.us/.")
    else:
        try:
            # Validate email if provided
            if email and not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
                st.error("Invalid email format.")
            else:
                st.session_state.email = email if email else None
                if join_option == "Join Now":
                    st.success("✅ Bot is joining the meeting now.")
                    logger.info(f"Starting bot immediately for URL: {zoom_url}")
                    threading.Thread(
                        target=run_bot_in_thread,
                        args=(zoom_url, st.session_state.email),
                        daemon=True
                    ).start()
                else:
                    if not join_time:
                        st.error("Please select a valid date and time for scheduling.")
                    else:
                        now = datetime.now()
                        if join_time < now:
                            st.warning("Scheduled time is in the past. Running bot immediately.")
                            logger.info(f"Scheduled time in past, starting bot immediately for URL: {zoom_url}")
                            threading.Thread(
                                target=run_bot_in_thread,
                                args=(zoom_url, st.session_state.email),
                                daemon=True
                            ).start()
                        else:
                            delay_seconds = (join_time - now).total_seconds()
                            st.success(f"✅ Bot scheduled to join at {join_time.strftime('%Y-%m-%d %H:%M:%S')}.")
                            logger.info(f"Scheduling bot for {join_time} (delay: {delay_seconds}s) for URL: {zoom_url}")
                            threading.Timer(
                                delay_seconds,
                                run_bot_in_thread,
                                args=(zoom_url, st.session_state.email)
                            ).start()
                st.info("The bot is running in the background. Check for minutes below after the meeting ends.")
        except Exception as e:
            st.error(f"Failed to start bot: {str(e)}")
            logger.error(f"Error starting bot: {str(e)}")

# Check if meeting has ended and generate minutes
flag_path = "temp_files/meeting_ended.flag"
if os.path.exists(flag_path):
    st.info("📋 Meeting has ended. Generating meeting minutes...")
    try:
        transcript = read_transcript()
        if transcript:
            minutes = generate_minutes(transcript)
            save_minutes(minutes)
            if st.session_state.get("email"):
                send_email(minutes, st.session_state.email)
                st.success(f"✅ Minutes generated and sent to {st.session_state.email}!")
            else:
                st.success("✅ Minutes generated!")
            # Clean up the flag file
            os.remove(flag_path)
            logger.info("Removed meeting_ended.flag after processing")
        else:
            st.error("No transcript available to generate minutes.")
            logger.warning("Transcript file is empty or missing")
    except Exception as e:
        st.error(f"Failed to generate or send minutes: {str(e)}")
        logger.error(f"Error generating/sending minutes: {str(e)}")

# Check for Minutes Button
st.markdown("---")
st.header("3. Get Meeting Minutes")
if st.button("🔄 Check for Minutes", use_container_width=True):
    minutes_path = "temp_files/minutes_of_meeting.txt"
    if os.path.exists(minutes_path):
        with open(minutes_path, "rb") as f:
            minutes_bytes = f.read()
        st.success("✅ Minutes are ready!")
        st.download_button(
            label="📥 Download Minutes",
            data=minutes_bytes,
            file_name="minutes_of_meeting.txt",
            mime="text/plain",
            use_container_width=True
        )
    else:
        st.info("Minutes not yet available. Please wait until the meeting concludes.")