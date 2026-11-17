# modules/library_engine.py

import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import List, Optional

import chromadb
from chromadb.utils import embedding_functions
import pymupdf

from modules.config import config

logger = logging.getLogger("Calypso.Library")


class LibraryEngine:
    def __init__(self, db_path: Optional[Path] = None):
        self.chroma_dir = db_path or config.LIBRARY_CHROMA_DIR
        self.chroma_dir.mkdir(parents=True, exist_ok=True)

        self.input_dir = config.INPUT_DIR
        self.output_dir = config.DOCS_OUTPUT_DIR
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Isolated ChromaDB Client
        self.client = chromadb.PersistentClient(path=str(self.chroma_dir))
        self.ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self.collection = self.client.get_or_create_collection(
            name="reference_library",
            embedding_function=self.ef
        )

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

    def _chunk_text(self, text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
        """Splits long text into overlapping chunks respecting sentence/paragraph boundaries."""
        if not text:
            return []
        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + chunk_size, text_len)
            chunk = text[start:end]

            # Try to snap to the nearest paragraph or sentence boundary
            if end < text_len:
                last_newline = chunk.rfind("\n\n")
                last_period = chunk.rfind(". ")
                if last_newline > int(chunk_size * 0.6):
                    end = start + last_newline + 2
                elif last_period > int(chunk_size * 0.6):
                    end = start + last_period + 2

            clean_chunk = text[start:end].strip()
            if clean_chunk:
                chunks.append(clean_chunk)

            start = end - overlap if end < text_len else text_len
        return chunks

    def ingest_pdf(self, pdf_path: Path) -> dict:
        """Extracts text page by page, chunks with metadata, and stores into ChromaDB."""
        if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
            return {"success": False, "filename": pdf_path.name, "error": "Invalid PDF path."}

        all_docs = []
        all_metas = []
        all_ids = []
        page_count = 0

        try:
            with pymupdf.open(str(pdf_path)) as doc:
                page_count = len(doc)
                for page_idx, page in enumerate(doc):
                    page_text = page.get_text()
                    if not page_text.strip():
                        try:
                            page_text = page.get_textpage_ocr(flags=0, full=True).get_text()
                        except Exception:
                            page_text = ""

                    if not page_text.strip():
                        continue

                    chunks = self._chunk_text(page_text, chunk_size=1200, overlap=180)
                    for c_idx, chunk in enumerate(chunks):
                        chunk_id = f"lib_{pdf_path.stem}_{page_idx+1}_{c_idx}_{uuid.uuid4().hex[:4]}"
                        meta = {
                            "source": pdf_path.name,
                            "page": page_idx + 1,
                            "chunk_index": c_idx,
                            "timestamp": time.strftime("%Y-%m-%d %H:%M")
                        }
                        all_docs.append(chunk)
                        all_metas.append(meta)
                        all_ids.append(chunk_id)

            if not all_docs:
                return {"success": False, "filename": pdf_path.name, "error": "No readable text found in PDF."}

            # Batch insert in groups of 100 to avoid memory spikes
            batch_size = 100
            for i in range(0, len(all_docs), batch_size):
                self.collection.add(
                    documents=all_docs[i:i + batch_size],
                    metadatas=all_metas[i:i + batch_size],
                    ids=all_ids[i:i + batch_size]
                )

            # Move processed PDF to documents output folder
            dest = self._get_unique_path(self.output_dir / pdf_path.name)
            shutil.move(str(pdf_path), str(dest))
            logger.info(f"[Library] Successfully indexed {len(all_docs)} chunks from {pdf_path.name} -> {dest.name}")

            return {
                "success": True,
                "filename": pdf_path.name,
                "archived_path": str(dest),
                "chunks": len(all_docs),
                "pages": page_count
            }

        except Exception as e:
            logger.error(f"[Library] Error ingesting PDF {pdf_path.name}: {e}", exc_info=True)
            return {"success": False, "filename": pdf_path.name, "error": str(e)}

    def ingest_all_staged_pdfs(self) -> List[dict]:
        """Scans workspace/input for all PDF files and indexes them."""
        if not self.input_dir.exists():
            return []

        pdf_files = [f for f in self.input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
        results = []
        for pdf in pdf_files:
            res = self.ingest_pdf(pdf)
            results.append(res)
        return results
        
    def index_research_entry(self, topic: str, vetted_text: str, sources: List[str]) -> bool:
        """Indexes vetted online research synthesis into the reference library collection."""
        if not vetted_text or not vetted_text.strip():
            return False

        try:
            chunks = self._chunk_text(vetted_text, chunk_size=1000, overlap=150)
            all_docs = []
            all_metas = []
            all_ids = []

            source_list_str = ", ".join(sources) if sources else "Web Research"
            for c_idx, chunk in enumerate(chunks):
                chunk_id = f"web_{uuid.uuid4().hex[:8]}_{c_idx}"
                meta = {
                    "source": f"Online Research: {topic}",
                    "domains": source_list_str,
                    "page": 1,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M")
                }
                all_docs.append(chunk)
                all_metas.append(meta)
                all_ids.append(chunk_id)

            self.collection.add(
                documents=all_docs,
                metadatas=all_metas,
                ids=all_ids
            )
            logger.info(f"[Library] Indexed {len(all_docs)} research chunks for topic: '{topic}'")
            return True
        except Exception as e:
            logger.error(f"[Library] Failed to index research: {e}")
            return False

    def delete_research_entry(self, topic: str) -> bool:
        """Deletes all indexed research chunks for a given topic from the reference library."""
        if not topic or not topic.strip():
            return False
        try:
            self.collection.delete(where={"source": f"Online Research: {topic}"})
            logger.info(f"[Library] Purged research chunks for topic: '{topic}'")
            return True
        except Exception as e:
            logger.error(f"[Library] Failed to delete research for '{topic}': {e}")
            return False
            
    def query_library(self, query_text: str, n_results: int = 3, distance_threshold: float = 0.95) -> List[dict]:
        """
        Selective retrieval: Only returns excerpts if their distance is below the threshold
        (lower distance = higher semantic similarity in Chroma L2 space).
        """
        count = self.collection.count()
        if count == 0 or not query_text or not query_text.strip():
            return []

        k = min(n_results, count)
        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=k,
                include=["documents", "metadatas", "distances"]
            )

            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]

            matched = []
            for doc, meta, dist in zip(docs, metas, dists):
                if dist <= distance_threshold:
                    matched.append({
                        "content": doc,
                        "source": meta.get("source", "Reference Text"),
                        "page": meta.get("page", 1),
                        "distance": dist
                    })
            return matched
        except Exception as e:
            logger.error(f"[Library] Query error: {e}")
            return []

    def get_library_context(self, query_target: str, force_query: bool = False, distance_threshold: float = 0.95) -> str:
        """Returns a formatted prompt block containing reference excerpts."""
        # In an active study session (force_query=True), use a slightly more generous threshold
        threshold = 1.15 if force_query else distance_threshold
        matches = self.query_library(query_target, n_results=3, distance_threshold=threshold)
        if not matches:
            return ""

        formatted_lines = [
            "\n### REFERENCE STUDY MATERIAL (CALYPSO'S LIBRARY):",
            "The following excerpts are from books and documents you have read and studied:"
        ]
        for m in matches:
            formatted_lines.append(f"- [Source: {m['source']}, Page {m['page']}]: \"{m['content']}\"")
        formatted_lines.append("Integrate these insights naturally and conversationally in your thoughtful stance.\n")

        return "\n".join(formatted_lines)

    def count(self) -> int:
        return self.collection.count()
