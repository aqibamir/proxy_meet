#!/usr/bin/env python3
"""
slide_final.py
Export every slide → PNG via LibreOffice (PPTX to PDF) and Poppler (PDF to PNGs)
Serve at http://localhost:3443
"""

import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from aiohttp import web

PORT = 3443
PPTX_FILE = "presentation.pptx"


class SlideServer:
    def __init__(self, pptx_path: str, port: int = 3443):
        self.port = port
        self.pptx_path = Path(pptx_path)
        self.current = 0
        self.png_paths = []
        self._export_pngs()
        self._ensure_static_dir()

    # ------------------------------------------------------------------
    # 1. Export PPTX to PDF, then PDF to per-slide PNGs
    # ------------------------------------------------------------------
    def _export_pngs(self) -> None:
        if not self.pptx_path.exists():
            raise FileNotFoundError(f"PPTX file not found: {self.pptx_path}")

        tmp_dir = Path(tempfile.mkdtemp(prefix="slides_"))

        # Step 1: Convert PPTX to PDF
        pdf_path = tmp_dir / "presentation.pdf"
        cmd_pdf = [
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",  # Adjust path if needed
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_dir),
            str(self.pptx_path),
        ]
        result_pdf = subprocess.run(cmd_pdf, capture_output=True, text=True)
        if result_pdf.returncode != 0:
            raise RuntimeError(f"LibreOffice PDF export failed:\n{result_pdf.stderr}")

        # Step 2: Convert PDF to per-slide PNGs
        cmd_png = [
            "pdftoppm",
            "-png",
            str(pdf_path),
            str(tmp_dir / "slide"),
        ]
        result_png = subprocess.run(cmd_png, capture_output=True, text=True)
        if result_png.returncode != 0:
            raise RuntimeError(f"pdftoppm conversion failed:\n{result_png.stderr}")

        # Collect PNG files (e.g., slide-1.png, slide-2.png, ...)
        png_files = sorted(tmp_dir.glob("slide-*.png"))
        print("Generated PNGs:", [p.name for p in png_files])
        if not png_files:
            raise RuntimeError("No PNG files generated")
        
        self.png_paths = [str(p) for p in png_files]
        print(f"✅ Exported {len(self.png_paths)} PNGs → {tmp_dir}")

    # ------------------------------------------------------------------
    # 2. Static directory
    # ------------------------------------------------------------------
    def _ensure_static_dir(self):
        self.static_path = Path(tempfile.mkdtemp(prefix="static_"))
        for idx, src in enumerate(self.png_paths):
            dst = self.static_path / f"{idx}.png"
            shutil.copy2(src, dst)
        print(f"Static files ready → {self.static_path}")

    # ------------------------------------------------------------------
    # 3. HTTP handlers
    # ------------------------------------------------------------------
    async def _index(self, _):
        return web.Response(text=self._html(), content_type="text/html")

    async def _next_handler(self, _):
        self.current = (self.current + 1) % len(self.png_paths)
        print(f"Advance to slide {self.current}")
        return web.json_response({"slide": self.current})

    def _html(self) -> str:
        total = len(self.png_paths)
        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Slide Deck</title>
  <style>
    html,body{{margin:0;height:100%;background:#000;display:flex;align-items:center;justify-content:center}}
    img{{width:100%;height:100%;object-fit:contain}}
    #controls{{position:fixed;top:20px;left:20px;color:#fff;font-family:sans-serif}}
  </style>
</head>
<body>
  <div id="controls">
    <button onclick="nextSlide()" {'style="display:none"' if total <= 1 else ''}>Next</button>
    <span id="counter">1 / {total}</span>
  </div>

  <img id="slide" src="/static/0.png" alt="slide">

  <script>
    let idx = 0;
    const total = {total};

    const update = data => {{
      idx = data.slide;
      document.getElementById('slide').src = `/static/${{idx}}.png`;
      document.getElementById('counter').textContent = `${{idx + 1}} / {total}`;
    }};

    async function nextSlide() {{
      const r = await fetch('/next');
      update(await r.json());
    }}
  </script>
</body>
</html>"""

    # ------------------------------------------------------------------
    # 4. Start aiohttp
    # ------------------------------------------------------------------
    async def start(self):
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_get("/next", self._next_handler)
        app.router.add_static("/static", self.static_path)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()
        print(f"Serve slides at http://localhost:{self.port}/")
        await asyncio.Event().wait()


if __name__ == "__main__":
    if not os.path.exists(PPTX_FILE):
        print(f"Create {PPTX_FILE} or edit PPTX_FILE variable.")
        exit(1)

    server = SlideServer(PPTX_FILE)
    asyncio.run(server.start())