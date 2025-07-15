import os
from pathlib import Path

# folders & files
ROOT = Path(__file__).parent
TMP_DIR       = ROOT / "tmp"
SCRIPT_JSON   = ROOT / "presentation_script.json"
PPTX_FILE     = ROOT / "deck.pptx"
CRED_PATH     = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")

# Zoom / Recall
RECALL_API_KEY = os.getenv("RECALL_API_KEY")

# Google Drive folders
TEMPLATES_FOLDER_ID = "1bz3HQH4TUEqEFIid-zjIYqFeCcaA96z1"
OUTPUT_FOLDER_ID    = "1RefP1KaakdfK0oQuVd3YW4Y1gy1Phax-"

TMP_DIR.mkdir(exist_ok=True)