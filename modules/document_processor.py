# modules/document_processor.py

import json
import logging
import os
import re
import shutil
import urllib.request
from pathlib import Path
from typing import List, Optional

import pymupdf
from docx import Document

try:
    from odf.opendocument import load as odf_load
    from odf.text import P
    from odf import teletype
    HAS_ODF = True
except ImportError:
    HAS_ODF = False

from modules.config import config
from modules.gpu_lock import gpu_vram_lock

logger = logging.getLogger("Calypso.Documents")


class DocumentModule:
    def __init__(self, workspace=None, output_dir=None):
        self.workspace = Path(workspace) if workspace else config.INPUT_DIR
        self.output_dir = Path(output_dir) if output_dir else config.DOCS_OUTPUT_DIR
        self.summary_dir = self.output_dir / "summaries"

        self.workspace.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.summary_dir.mkdir(parents=True, exist_ok=True)

        self.valid_extensions = {".pdf", ".docx", ".odt", ".txt", ".md", ".json", ".py"}

    def _get_unique_path(self, target_path: Path) -> Path:
        if not target_path.exists():
            return target_path
        stem = target_path.stem
        suffix = target_path.suffix
        parent = target_path.parent
        counter = 1
        while True:
            candidate = parent / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def extract_text(self, file_path: Path, max_chars: int = 15000) -> str:
        """Extracts text content cleanly with proper context managers."""
        ext = file_path.suffix.lower()
        text = ""

        try:
            if ext == '.pdf':
                with pymupdf.open(str(file_path)) as doc:
                    for page in doc:
                        page_text = page.get_text()
                        if not page_text.strip():
                            try:
                                page_text = page.get_textpage_ocr(flags=0, full=True).get_text()
                            except Exception:
                                page_text = ""
                        text += page_text + "\n"
                        if len(text) >= max_chars:
                            break

            elif ext == '.docx':
                document = Document(str(file_path))
                paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
                text = "\n".join(paragraphs)

            elif ext == '.odt' and HAS_ODF:
                doc = odf_load(str(file_path))
                paragraphs = doc.getElementsByType(P)
                text = "\n".join([teletype.extractText(p).strip() for p in paragraphs if p])

            elif ext in ('.txt', '.md', '.json', '.py'):
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()

        except Exception as e:
            logger.error(f"[Documents] Failed reading {file_path.name}: {e}")
            return ""

        return text[:max_chars].strip()

    def generate_llm_summary(self, text: str, filename: str) -> str:
        """Queries Ollama to produce a concise synthesis of key insights and takeaways."""
        if not text:
            return "Empty document."

        prompt = (
            f"You are Calypso's cognitive document ingestion core. Read this extracted document text from '{filename}' "
            f"and generate a crisp, structured overview in under 120 words:\n"
            f"1. Executive Essence (What is this document about?)\n"
            f"2. Key Takeaways & Facts\n\n"
            f"DOCUMENT CONTENT:\n{text[:4500]}"
        )

        base_url = str(config.OLLAMA_URL).rstrip("/")
        if not base_url.endswith("/api/chat"):
            chat_url = base_url + "/api/chat" if "/api/" not in base_url else base_url.rsplit("/api/", 1)[0] + "/api/chat"
        else:
            chat_url = base_url

        payload = {
            "model": config.MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.2,
                "num_predict": 1024
            }
        }

        try:
            req = urllib.request.Request(
                chat_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with gpu_vram_lock:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

            msg = data.get("message", {})
            raw_content = msg.get("content", "").strip()

            if "</think>" in raw_content.lower():
                clean = re.sub(r"<think>.*?</think>", "", raw_content, flags=re.DOTALL | re.IGNORECASE).strip()
            else:
                clean = re.sub(r"<think>.*$", "", raw_content, flags=re.DOTALL | re.IGNORECASE).strip()
            clean = re.sub(r"</?think>", "", clean, flags=re.IGNORECASE).strip()

            if not clean and msg.get("thinking"):
                clean = str(msg.get("thinking", "")).strip()

            if not clean:
                logger.warning(f"[Documents] Ollama returned an empty summary for '{filename}'. Falling back to snippet.")
                return text[:400] + "..."

            return clean
        except Exception as e:
            logger.warning(f"[Documents] Ollama summary failed: {e}. Fallback to snippet.")
            return text[:400] + "..."

    def save_summary(self, original_filename: str, summary_text: str) -> Path:
        summary_filename = f"{Path(original_filename).stem}_summary.txt"
        summary_path = self._get_unique_path(self.summary_dir / summary_filename)
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write(summary_text)
        return summary_path

    def process_document(self, file_path: Path) -> dict:
        """Extracts text, generates an LLM summary, archives the file, and writes summary notes."""
        extracted = self.extract_text(file_path)
        if not extracted:
            return {"success": False, "filename": file_path.name, "error": "No readable text."}

        summary = self.generate_llm_summary(extracted, file_path.name)
        summary_path = self.save_summary(file_path.name, summary)

        dest_file = self._get_unique_path(self.output_dir / file_path.name)
        try:
            shutil.move(str(file_path), str(dest_file))
            logger.info(f"[Documents] Processed and moved {file_path.name} -> {dest_file.name}")
            return {
                "success": True,
                "filename": file_path.name,
                "archived_path": str(dest_file),
                "summary_path": str(summary_path),
                "summary": summary,
                "raw_sample": extracted[:500]
            }
        except Exception as e:
            logger.error(f"[Documents] Failed to move {file_path.name}: {e}")
            return {
                "success": False,
                "filename": file_path.name,
                "summary": summary,
                "error": str(e)
            }

    def scan_and_process_all(self) -> List[dict]:
        """Processes all documents waiting in the workspace input directory."""
        if not self.workspace.exists():
            return []

        files = [
            f for f in self.workspace.iterdir()
            if f.is_file() and f.suffix.lower() in self.valid_extensions
        ]

        results = []
        for file_path in files:
            res = self.process_document(file_path)
            results.append(res)
        return results
