"""
streamlit_app.py
UI → zero-touch Zoom presentation
"""

import os
import tempfile
import asyncio
import streamlit as st
from bot_worker import run_meeting

st.set_page_config(page_title="Zoom Slide Bot", layout="centered")
st.title("📊 Zoom Bot – Join & Present")

prompt = st.text_area("Prompt", height=120)
pdf_file = st.file_uploader("Upload PDF", type=["pdf"])
zoom_url = st.text_input("🔗 Zoom meeting link")

if st.button("Join & Present"):
    if not all([prompt, pdf_file, zoom_url]):
        st.error("Fill all fields.")
        st.stop()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_file.read())
        tmp_pdf = tmp.name

    with st.spinner("Generating deck & joining…"):
        bot_id = asyncio.run(run_meeting(tmp_pdf, prompt, zoom_url))
    st.success(f"✅ Bot joined!  ID: `{bot_id}`")
    st.info("Slides are now being presented.")

    os.unlink(tmp_pdf)