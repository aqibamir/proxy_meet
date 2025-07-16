import os
import re
import shutil
import tempfile
import threading
import time
from datetime import datetime, timedelta, date

import streamlit as st

# Import our local generator
from slides_generator_local import generate_local

# ------------------------------------------------------------------
# Streamlit page setup
# ------------------------------------------------------------------
st.set_page_config(page_title="Zoom Slide Bot (Local)", layout="wide")
st.title("📊 Zoom Slide Bot – Local Edition")
st.markdown(
    "Generate presentation slides **locally** (no Google Drive) and optionally let the bot join a Zoom meeting."
)

# ------------------------------------------------------------------
# SECTION 1 – Generate Slides
# ------------------------------------------------------------------
st.subheader("Generate Slides")
col1, col2 = st.columns([2, 1])

with col1:
    prompt = st.text_area(
        "Prompt (Optional)",
        height=120,
        placeholder="e.g., Create a presentation about Q3 sales performance...",
        help="Enter a prompt to guide slide generation. Leave blank if using a PDF only.",
    )
    pdf_file = st.file_uploader(
        "Upload PDF (Optional)",
        type=["pdf"],
        help="Upload a PDF to generate slides from its content. Max 200 MB.",
    )

if st.button("📑 Generate Slides", use_container_width=True):
    if not prompt and not pdf_file:
        st.error("Please provide a prompt or upload a PDF.")
    else:
        with st.spinner("Generating presentation…"):
            tmp_dir = tempfile.mkdtemp()
            pdf_path = None
            if pdf_file:
                pdf_path = os.path.join(tmp_dir, "input.pdf")
                with open(pdf_path, "wb") as f:
                    f.write(pdf_file.read())
            try:
                pptx_path, json_path = generate_local(
                    prompt or "Generate a default presentation",
                    pdf_path or "",
                    tmp_dir,
                )

                # Read binaries for download button
                with open(pptx_path, "rb") as f:
                    pptx_bytes = f.read()

                st.success("✅ Slides generated successfully! Download the presentation below.")
                st.download_button(
                    label="📥 Download Presentation (PPTX)",
                    data=pptx_bytes,
                    file_name="presentation.pptx",
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    use_container_width=True,
                )
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

st.markdown("---")

# ------------------------------------------------------------------
# SECTION 2 – Join Zoom Meeting (unchanged logic)
# ------------------------------------------------------------------
st.subheader("Join Zoom Meeting")
col3, col4 = st.columns([2, 1])

with col3:
    zoom_url = st.text_input(
        "🔗 Zoom Meeting Link (Required)",
        placeholder="https://zoom.us/j/123456789",
        help="Enter the Zoom meeting link (e.g., https://zoom.us/j/...).",
    )
    join_option = st.radio(
        "Join Option",
        ["Join Now", "Schedule"],
        help="Choose to join the meeting immediately or schedule for a later time.",
    )
    join_time = None
    if join_option == "Schedule":
        selected_date = st.date_input(
            "Join Date",
            value=date.today(),
            help="Select the date for the bot to join.",
        )
        selected_time = st.time_input(
            "Join Time",
            value=(datetime.now() + timedelta(minutes=1)).time(),
            help="Select the time for the bot to join.",
        )
        join_time = datetime.combine(selected_date, selected_time)

if st.button("🤝 Join Meeting", use_container_width=True):
    if not zoom_url:
        st.error("Please provide a Zoom meeting link.")
    elif not re.match(r"https://[a-zA-Z0-9.-]+\.zoom\.us/[a-zA-Z0-9_/?-]+", zoom_url):
        st.warning("The Zoom link format looks invalid. Please ensure it starts with https://*.zoom.us/.")
    else:
        # Dummy join_and_present for now; replace with real bot_worker
        def join_and_present(url: str) -> None:
            time.sleep(2)  # simulate work
            print("Bot joined", url)

        if join_option == "Join Now":
            st.success("✅ Bot is joining the meeting now.")
            threading.Thread(target=join_and_present, args=(zoom_url,), daemon=True).start()
        else:
            if not join_time:
                st.error("Please select a valid date and time for scheduling.")
            else:
                now = datetime.now()
                if join_time < now:
                    st.warning("Scheduled time is in the past. Running bot immediately.")
                    threading.Thread(target=join_and_present, args=(zoom_url,), daemon=True).start()
                else:
                    delay_seconds = (join_time - now).total_seconds()
                    st.success(f"✅ Bot scheduled to join at {join_time.strftime('%Y-%m-%d %H:%M:%S')}.")
                    threading.Timer(delay_seconds, join_and_present, args=(zoom_url,)).start()
        st.info("The bot is running in the background. You can close this page.")