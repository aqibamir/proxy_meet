"""
slides_generator.py
PDF + prompt → .pptx + JSON → Google-Slides public URL
"""

import os
import json
import datetime
from pathlib import Path
from typing import List, Dict

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from openai import OpenAI
from PyPDF2 import PdfReader

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
TEMPLATES_FOLDER_ID  = os.getenv("TEMPLATES_FOLDER",  "1bz3HQH4TUEqEFIid-zjIYqFeCcaA96z1")
OUTPUT_FOLDER_ID     = os.getenv("OUTPUT_FOLDER",     "1RefP1KaakdfK0oQuVd3YW4Y1gy1Phax-")
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/presentations"
]

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service  = build("drive",  "v3", credentials=creds)
slides_service = build("slides", "v1", credentials=creds)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", "sk-placeholder"))

# --------------------------------------------------
# UTILS
# --------------------------------------------------
def list_templates(folder_id: str) -> List[Dict[str, str]]:
    q = f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.presentation'"
    return drive_service.files().list(q=q, fields="files(id,name)").execute().get("files", [])

def pick_valid_template(templates: List[Dict[str, str]]) -> Dict[str, str]:
    valid = [t for t in templates if _has_body(t["id"])]
    if not valid:
        raise ValueError("No template with BODY placeholder")
    return valid[0]

def _has_body(template_id: str) -> bool:
    try:
        pres = slides_service.presentations().get(presentationId=template_id).execute()
        return any(
            "placeholder" in e.get("shape", {})
            and e["shape"]["placeholder"].get("type") == "BODY"
            for e in pres["slides"][0].get("pageElements", [])
        )
    except HttpError:
        return False

def copy_template(template_id: str, name: str) -> str:
    body = {"name": name, "parents": [OUTPUT_FOLDER_ID]}
    return drive_service.files().copy(fileId=template_id, body=body).execute()["id"]

# --------------------------------------------------
# TEXT / JSON GENERATION
# --------------------------------------------------
def read_pdf(pdf_path: str) -> str:
    with open(pdf_path, "rb") as f:
        return "".join(page.extract_text() or "" for page in PdfReader(f).pages)

def structure_content(prompt: str, pdf_text: str) -> str:
    user = (
        f"Prompt: {prompt}\n\n"
        f"PDF content:\n{pdf_text}\n\n"
        "Structure into a deck outline like:\n"
        "Slide 1 Title: <title>\n<bullet text>\nGraph Data: <cat>: <val>\n\n"
        "Slide 2 Title: ..."
    )
    resp = client.chat.completions.create(
        model="gpt-4", messages=[{"role": "user", "content": user}], max_tokens=1000
    )
    return resp.choices[0].message.content.strip()

# --------------------------------------------------
# UPLOAD & RETURN PUBLIC URL
# --------------------------------------------------
def upload_pptx_to_google_slides(pptx_path: str, title: str) -> str:
    file_metadata = {"name": title, "mimeType": "application/vnd.google-apps.presentation"}
    media = MediaFileUpload(
        pptx_path,
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    file = drive_service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    file_id = file.get("id")
    drive_service.permissions().create(fileId=file_id, body={"role": "reader", "type": "anyone"})
    return f"https://docs.google.com/presentation/d/{file_id}/present"

# --------------------------------------------------
# MAIN FUNCTION
# --------------------------------------------------
def generate_presentation(prompt: str, pdf_path: str) -> str:
    """
    PDF + prompt → .pptx → Google-Slides public URL
    Also writes JSON deck for LocalPresenter
    """
    templates = list_templates(TEMPLATES_FOLDER_ID)
    if not templates:
        raise RuntimeError("No templates")

    pdf_text = read_pdf(pdf_path)
    content = structure_content(prompt, pdf_text)

    topic = content.splitlines()[0].split("Title:", 1)[-1].strip() or "Deck"
    template = pick_valid_template(templates)
    new_id = copy_template(template["id"], f"AI_{datetime.datetime.now():%Y%m%d_%H%M%S}")

    # Export .pptx locally
    pptx_path = "deck.pptx"
    drive_service.files().export_media(
        fileId=new_id, mimeType="application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ).execute_to_file(pptx_path)

    # Upload to Google-Slides
    slides_url = upload_pptx_to_google_slides(pptx_path, topic)

    # Save JSON deck
    Path("presentation_script.json").write_text(content, encoding="utf-8")
    return slides_url