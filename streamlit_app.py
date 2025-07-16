import os
import tempfile
import streamlit as st
from datetime import datetime, timedelta, date, time
from bot_worker import join_and_present
# from slides_generator import generate_presentation
import threading
import time
import re
import shutil

st.set_page_config(page_title="Zoom Slide Bot", layout="wide")
st.title("📊 Zoom Slide Bot")
st.markdown("Easily join a Zoom meeting with an automated presentation bot. Upload a PDF and provide a prompt to generate slides, or just enter a Zoom link to join.")

# UI Layout with Columns
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Presentation Inputs")
    prompt = st.text_area(
        "Prompt (Optional)",
        height=120,
        placeholder="e.g., Create a presentation about Q3 sales performance...",
        help="Enter a prompt to guide slide generation. Leave blank if you have a pre-prepared script."
    )
    pdf_file = st.file_uploader(
        "Upload PDF (Optional)",
        type=["pdf"],
        help="Upload a PDF to generate slides from its content. Max 200MB."
    )

with col2:
    st.subheader("Meeting Details")
    zoom_url = st.text_input(
        "🔗 Zoom Meeting Link (Required)",
        placeholder="https://zoom.us/j/123456789",
        help="Enter the Zoom meeting link (e.g., https://zoom.us/j/...)."
    )
    join_option = st.radio(
        "Join Option",
        ["Join Now", "Schedule"],
        help="Choose to join the meeting immediately or schedule for a later time."
    )
    join_time = None
    if join_option == "Schedule":
        selected_date = st.date_input(
            "Join Date",
            value=date.today(),
            help="Select the date for the bot to join."
        )
        selected_time = st.time_input(
            "Join Time",
            value=(datetime.now() + timedelta(minutes=1)).time(),
            help="Select the time for the bot to join."
        )
        join_time = datetime.combine(selected_date, selected_time)

if st.button("🚀 Start Presentation", use_container_width=True):
    # Validate Zoom link
    if not zoom_url:
        st.error("Please provide a Zoom meeting link.")
        st.stop()
    if not re.match(r"https://[a-zA-Z0-9.-]+\.zoom\.us/[a-zA-Z0-9_/?-]+", zoom_url):
        st.warning("The Zoom link format looks invalid. Please ensure it starts with https://*.zoom.us/.")

    # Initialize temporary directory
    tmp_dir = tempfile.mkdtemp()

    # Generate presentation if prompt or PDF is provided
    slides_url = None
    pptx_path = None
    if prompt or pdf_file:
        try:
            from slides_generator import generate_presentation
            pdf_path = os.path.join(tmp_dir, "input.pdf") if pdf_file else None
            if pdf_file:
                with open(pdf_path, "wb") as f:
                    f.write(pdf_file.read())
            with st.spinner("Generating presentation…"):
                slides_url = generate_presentation(
                    prompt or "Generate a default presentation",
                    pdf_path or "",
                    output_dir=tmp_dir
                )
                st.success(f"✅ Slides generated: [View Slides]({slides_url})")
                pptx_path = os.path.join(tmp_dir, "deck.pptx")
                if os.path.exists(pptx_path):
                    with open(pptx_path, "rb") as f:
                        st.download_button(
                            label="📥 Download PPTX",
                            data=f,
                            file_name="presentation.pptx",
                            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                            use_container_width=True
                        )
        except ImportError:
            st.warning("Slide generation not available (slides_generator not found). Proceeding with bot execution.")
        except Exception as e:
            st.warning(f"Slide generation skipped: {str(e)}. Proceeding with bot execution.")

    # Function to run bot and clean up
    def run_bot_with_cleanup(meeting_url, tmp_dir, delay_seconds=0):
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            join_and_present(meeting_url)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # Handle join now or schedule
    if join_option == "Join Now":
        st.success("✅ Bot is joining the meeting now.")
        threading.Thread(target=run_bot_with_cleanup, args=(zoom_url, tmp_dir), daemon=True).start()
    else:
        if not join_time:
            st.error("Please select a valid date and time for scheduling.")
            st.stop()
        now = datetime.now()
        if join_time < now:
            st.warning("Scheduled time is in the past. Running bot immediately.")
            delay_seconds = 0
        else:
            delay_seconds = (join_time - now).total_seconds()
            st.success(f"✅ Bot scheduled to join at {join_time.strftime('%Y-%m-%d %H:%M:%S')}.")
        threading.Thread(target=run_bot_with_cleanup, args=(zoom_url, tmp_dir, delay_seconds), daemon=True).start()

    st.info("The bot is running in the background. You can close this page.")