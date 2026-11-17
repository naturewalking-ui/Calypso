# modules/scrap_book.py

import json
import logging
import os
import re
import threading
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

import customtkinter as ctk
from PIL import Image, ImageOps

from modules.config import config
from modules.media_processor import MediaProcessor

logger = logging.getLogger("Calypso.Scrapbook")

VALID_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}

# Boilerplate SDXL tokens to strip when deriving fallback captions from raw prompts
_SDXL_BOILERPLATE_PATTERNS = [
    r"\b1girl\b", r"\bsolo\b", r"\bblonde hair\b", r"\blong hair\b", r"\bblue eyes\b",
    r"\blarge breasts\b", r"\bdetailed skin texture\b", r"\bred a-line dress\b",
    r"\bf/1\.8\b", r"\b85mm lens\b", r"\bshallow depth of field\b", r"\bcreamy bokeh\b",
    r"\bsharp focus on subject\b", r"\bmasterpiece\b", r"\bexpressive fine art\b",
    r"\bbreathtaking atmosphere\b", r"\bhighly detailed\b", r"\bsoft natural shadows\b",
    r"\bdepth of field\b", r"\bheavily blurred background\b", r"\bbokeh\b",
    r"\(detailed blue eyes\)1\.2", r"\(highly detailed face\)1\.2", r"\bnude\b"
]


def _clean_prompt_for_fallback_caption(raw_prompt: str) -> str:
    """Extracts the human-readable narrative portion of an SDXL prompt for legacy images."""
    if not raw_prompt:
        return ""
    cleaned = raw_prompt
    for pat in _SDXL_BOILERPLATE_PATTERNS:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
    # Collapse repeated commas and spaces
    cleaned = re.sub(r"(\s*,\s*)+", ", ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.")
    if not cleaned:
        return raw_prompt.strip()
    return cleaned + ("." if not cleaned.endswith((".", "!", "?")) else "")


def standalone_purge_image_asset(file_path: str | Path, memory_dir: Path = None, character_name: str = "calypso") -> bool:
    """
    Fallback complete purge if MemoryEngine instance is not passed (e.g., standalone mode).
    Deletes physical file, removes from gallery_history.json and creative_works_{character_name}.json.
    """
    if not file_path:
        return False
    mem_dir = Path(memory_dir) if memory_dir else config.MEMORY_DIR
    target_path = Path(file_path)
    target_name = target_path.name
    target_str = str(target_path.resolve()) if target_path.exists() else str(target_path)

    try:
        if target_path.exists() and target_path.is_file():
            target_path.unlink()
    except Exception as e:
        logger.error(f"[Scrapbook] Could not delete {target_path}: {e}")

    gallery_file = mem_dir / "gallery_history.json"
    if gallery_file.exists():
        try:
            with open(gallery_file, "r", encoding="utf-8") as f:
                history = json.load(f)
            if isinstance(history, list):
                filtered = [
                    e for e in history
                    if e.get("file_name") != target_name
                    and Path(str(e.get("file_path", ""))).name != target_name
                    and str(e.get("file_path", "")) != target_str
                ]
                if len(filtered) != len(history):
                    tmp = gallery_file.with_suffix(".tmp")
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(filtered, f, indent=2)
                    tmp.replace(gallery_file)
        except Exception as e:
            logger.warning(f"[Scrapbook] Failed updating gallery_history.json: {e}")

    works_file = mem_dir / f"creative_works_{character_name.lower()}.json"
    if works_file.exists():
        try:
            with open(works_file, "r", encoding="utf-8") as f:
                archive = json.load(f)
            if isinstance(archive, list):
                remaining = [
                    e for e in archive
                    if Path(str((e.get("metadata") or {}).get("file_path", ""))).name != target_name
                ]
                if len(remaining) != len(archive):
                    tmp = works_file.with_suffix(".tmp")
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(remaining, f, indent=2)
                    tmp.replace(works_file)
        except Exception as e:
            logger.warning(f"[Scrapbook] Failed updating {works_file.name}: {e}")

    return True


class ScrapbookView(ctk.CTkFrame):
    """
    Core Digital Scrapbook widget that can be embedded in a CTkToplevel modal
    (via GUIEngine) or a standalone CTk root window.
    """
    def __init__(
        self,
        master,
        album_dir: str | Path = None,
        media_processor: Optional[MediaProcessor] = None,
        memory_engine=None,
        scenario_engine=None,
        input_queue=None,
        open_viewer_callback=None,
        initial_filter: Optional[str] = None
    ):
        super().__init__(master, fg_color="#10131a", corner_radius=0)

        self.album_dir = Path(album_dir) if album_dir else config.IMAGES_OUTPUT_DIR
        self.media_processor = media_processor or MediaProcessor()
        self.memory_engine = memory_engine
        self.scenario_engine = scenario_engine
        self.input_queue = input_queue
        self.open_viewer_callback = open_viewer_callback

        self.all_entries: List[Dict[str, Any]] = []
        self.filtered_entries: List[Dict[str, Any]] = []
        self.current_index: int = 0
        self.newest_first: bool = True
        self.current_filter: str = initial_filter or "All Memories"
        self.sidebar_buttons: List[ctk.CTkButton] = []
        self._is_analyzing: bool = False

        self._build_layout()
        self.load_album_data(preserve_filter=bool(initial_filter))

    def _build_layout(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # ---------------------------------------------------------------------
        # 1. Left Sidebar Navigation & Album Filtering
        # ---------------------------------------------------------------------
        self.sidebar = ctk.CTkFrame(self, width=285, corner_radius=0, fg_color="#141824")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        self.sidebar_title = ctk.CTkLabel(
            self.sidebar,
            text="📚 Calypso's Scrapbook",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color="#f8fafc"
        )
        self.sidebar_title.pack(padx=16, pady=(16, 4), anchor="w")

        self.subtitle_lbl = ctk.CTkLabel(
            self.sidebar,
            text="Cataloged Roleplay & Shared Memories",
            font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic"),
            text_color="#94a3b8"
        )
        self.subtitle_lbl.pack(padx=16, pady=(0, 12), anchor="w")

        # Album Filter Selector
        filter_Row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        filter_Row.pack(fill="x", padx=14, pady=(0, 6))

        ctk.CTkLabel(
            filter_Row, text="Album Filter:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#cbd5e1"
        ).pack(anchor="w", pady=(0, 3))

        self.album_filter_menu = ctk.CTkOptionMenu(
            filter_Row,
            values=["All Memories"],
            fg_color="#1e293b",
            button_color="#334155",
            button_hover_color="#475569",
            text_color="#f8fafc",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            command=self._on_filter_selected
        )
        self.album_filter_menu.pack(fill="x")

        # Sort & Refresh Controls
        ctrl_row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        ctrl_row.pack(fill="x", padx=14, pady=(4, 8))

        self.sort_btn = ctk.CTkButton(
            ctrl_row, text="🔽 Newest First", height=26,
            fg_color="#1e293b", hover_color="#334155",
            font=ctk.CTkFont(size=11), text_color="#cbd5e1",
            command=self._toggle_sort_order
        )
        self.sort_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.refresh_btn = ctk.CTkButton(
            ctrl_row, text="🔄 Refresh", width=76, height=26,
            fg_color="#1e293b", hover_color="#334155",
            font=ctk.CTkFont(size=11), text_color="#cbd5e1",
            command=lambda: self.load_album_data(preserve_filter=True)
        )
        self.refresh_btn.pack(side="right")

        self.scrollable_list = ctk.CTkScrollableFrame(
            self.sidebar, label_text="Photos Available",
            fg_color="#0f131d", label_fg_color="#1e293b",
            label_text_color="#e2e8f0"
        )
        self.scrollable_list.pack(padx=10, pady=(2, 12), fill="both", expand=True)

        # ---------------------------------------------------------------------
        # 2. Main Warm Parchment Scrapbook Page Area
        # ---------------------------------------------------------------------
        self.canvas_page = ctk.CTkFrame(
            self, fg_color="#F4EBE1", corner_radius=16,
            border_width=2, border_color="#D7CCC8"
        )
        self.canvas_page.grid(row=0, column=1, padx=20, pady=18, sticky="nsew")
        self.canvas_page.grid_rowconfigure(2, weight=1)
        self.canvas_page.grid_columnconfigure(0, weight=1)

        # Top Header Row (Album Badge + Page Navigation)
        self.top_bar = ctk.CTkFrame(self.canvas_page, fg_color="transparent")
        self.top_bar.grid(row=0, column=0, sticky="ew", padx=24, pady=(14, 2))

        self.album_badge_lbl = ctk.CTkLabel(
            self.top_bar,
            text="📸 SHARED MOMENT",
            font=ctk.CTkFont(family="Consolas", size=11, weight="bold"),
            text_color="#6D4C41",
            fg_color="#E6D7C3",
            corner_radius=6,
            padx=10, pady=3
        )
        self.album_badge_lbl.pack(side="left")

        nav_frame = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        nav_frame.pack(side="right")

        self.prev_btn = ctk.CTkButton(
            nav_frame, text="◀ Prev", width=68, height=26,
            fg_color="#8D6E63", hover_color="#6D4C41", text_color="#FFFDF9",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.prev_page
        )
        self.prev_btn.pack(side="left", padx=(0, 6))

        self.page_counter_lbl = ctk.CTkLabel(
            nav_frame, text="Page 0 of 0",
            font=ctk.CTkFont(family="Courier", size=13, weight="bold"),
            text_color="#5D4037"
        )
        self.page_counter_lbl.pack(side="left", padx=6)

        self.next_btn = ctk.CTkButton(
            nav_frame, text="Next ▶", width=68, height=26,
            fg_color="#8D6E63", hover_color="#6D4C41", text_color="#FFFDF9",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.next_page
        )
        self.next_btn.pack(side="left", padx=(6, 0))

        # Memory Title Label
        self.memory_title_lbl = ctk.CTkLabel(
            self.canvas_page,
            text="",
            font=ctk.CTkFont(family="Georgia", size=18, weight="bold"),
            text_color="#3E2723",
            wraplength=720
        )
        self.memory_title_lbl.grid(row=1, column=0, padx=24, pady=(2, 4))

        # Photo Mat Frame
        self.photo_mat = ctk.CTkFrame(
            self.canvas_page,
            fg_color="#FFFDF9",
            corner_radius=10,
            border_width=2,
            border_color="#D7CCC8"
        )
        self.photo_mat.grid(row=2, column=0, padx=32, pady=6)

        self.photo_frame = ctk.CTkLabel(
            self.photo_mat, text="", cursor="hand2"
        )
        self.photo_frame.pack(padx=12, pady=12)
        self.photo_frame.bind("<Button-1>", self._on_photo_click)

        # Date & Tags Metadata Row
        meta_frame = ctk.CTkFrame(self.canvas_page, fg_color="transparent")
        meta_frame.grid(row=3, column=0, padx=28, pady=(2, 2))

        self.date_label = ctk.CTkLabel(
            meta_frame,
            text="",
            text_color="#5D4037",
            font=ctk.CTkFont(family="Courier", size=14, weight="bold")
        )
        self.date_label.pack()

        self.tags_label = ctk.CTkLabel(
            meta_frame,
            text="",
            text_color="#795548",
            font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic"),
            wraplength=680
        )
        self.tags_label.pack(pady=(1, 0))

        # Handwritten-style Scrapbook Journal / Caption Box
        self.description_box = ctk.CTkTextbox(
            self.canvas_page,
            width=680,
            height=110,
            fg_color="#FFFDF9",
            text_color="#3E2723",
            font=ctk.CTkFont(family="Georgia", size=14),
            corner_radius=10,
            border_width=1,
            border_color="#D7CCC8",
            wrap="word"
        )
        self.description_box.grid(row=4, column=0, padx=32, pady=(6, 8), sticky="ew")

        # Bottom Interactive Action Bar
        self.action_bar = ctk.CTkFrame(self.canvas_page, fg_color="transparent")
        self.action_bar.grid(row=5, column=0, padx=32, pady=(0, 14), sticky="ew")

        self.analyze_btn = ctk.CTkButton(
            self.action_bar,
            text="✨ Reminisce (Vision Analyze)",
            height=30,
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            text_color="#ffffff",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_vision_reminisce
        )
        self.analyze_btn.pack(side="left", padx=(0, 8))

        self.save_note_btn = ctk.CTkButton(
            self.action_bar,
            text="💾 Save Caption",
            height=30,
            fg_color="#6D4C41",
            hover_color="#5D4037",
            text_color="#FFFDF9",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_save_caption
        )
        self.save_note_btn.pack(side="left", padx=(0, 8))

        if self.input_queue is not None:
            self.share_chat_btn = ctk.CTkButton(
                self.action_bar,
                text="💬 Share Memory in Chat",
                height=30,
                fg_color="#0284c7",
                hover_color="#0369a1",
                text_color="#ffffff",
                font=ctk.CTkFont(size=12, weight="bold"),
                command=self._on_share_in_chat
            )
            self.share_chat_btn.pack(side="left", padx=(0, 8))

        self.status_lbl = ctk.CTkLabel(
            self.action_bar,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic"),
            text_color="#5D4037"
        )
        self.status_lbl.pack(side="left", padx=6)

        self.purge_btn = ctk.CTkButton(
            self.action_bar,
            text="🗑️ Purge Defective Photo",
            height=30,
            fg_color="#b91c1c",
            hover_color="#991b1b",
            text_color="#ffffff",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_purge_current_photo
        )
        self.purge_btn.pack(side="right")

    # -------------------------------------------------------------------------
    # DATA CATALOGING & METADATA MERGING
    # -------------------------------------------------------------------------
    def _load_metadata_maps(self) -> tuple[Dict[str, dict], Dict[str, dict]]:
        """Loads gallery_history.json and creative_works_calypso.json keyed by filename."""
        mem_dir = getattr(self.memory_engine, "memory_dir", config.MEMORY_DIR)
        char_name = getattr(self.memory_engine, "character_name", "calypso")

        gallery_map: Dict[str, dict] = {}
        gallery_file = mem_dir / "gallery_history.json"
        if gallery_file.exists():
            try:
                with open(gallery_file, "r", encoding="utf-8") as f:
                    for item in json.load(f):
                        fname = item.get("file_name") or Path(str(item.get("file_path", ""))).name
                        if fname:
                            gallery_map[fname] = item
            except Exception as e:
                logger.warning(f"[Scrapbook] Could not read gallery_history.json: {e}")

        works_map: Dict[str, dict] = {}
        works_file = mem_dir / f"creative_works_{char_name}.json"
        if works_file.exists():
            try:
                with open(works_file, "r", encoding="utf-8") as f:
                    for item in json.load(f):
                        if item.get("type") == "artwork":
                            meta = item.get("metadata") or {}
                            fp = str(meta.get("file_path", ""))
                            if fp:
                                works_map[Path(fp).name] = item
            except Exception as e:
                logger.warning(f"[Scrapbook] Could not read {works_file.name}: {e}")

        return gallery_map, works_map

    def load_album_data(self, preserve_filter: bool = True):
        """Scans the images output directory and merges scenario, artwork, and vision metadata."""
        if not self.album_dir.exists():
            self.album_dir.mkdir(parents=True, exist_ok=True)

        gallery_map, works_map = self._load_metadata_maps()

        raw_files = [
            f for f in self.album_dir.iterdir()
            if f.is_file() and f.suffix.lower() in VALID_IMAGE_EXTENSIONS
        ]
        raw_files.sort(key=lambda x: x.stat().st_mtime, reverse=self.newest_first)

        entries: List[Dict[str, Any]] = []
        scenario_albums_found = set()

        for img_path in raw_files:
            fname = img_path.name
            gal_entry = gallery_map.get(fname, {})
            gal_meta = gal_entry.get("metadata") or {}
            work_entry = works_map.get(fname, {})
            work_meta = work_entry.get("metadata") or {}

            # Determine Roleplay Scenario vs Autonomous Creation vs Shared Moment
            scenario_title = (
                gal_meta.get("scenario_title")
                or work_meta.get("scenario_title")
                or ""
            ).strip()
            scenario_id = (
                gal_meta.get("scenario_id")
                or work_meta.get("scenario_id")
                or ""
            ).strip()

            style = str(work_meta.get("style") or gal_meta.get("style") or "").strip()
            is_autonomous = bool(
                (style and style != "Conversational Artwork")
                or work_meta.get("neuro_summary")
                or gal_meta.get("origin") == "autonomous_art"
            )

            if scenario_title:
                category = "Roleplay Scenarios"
                album_name = f"🎭 {scenario_title}"
                scenario_albums_found.add(album_name)
                badge_text = f"🎭 ROLEPLAY // {scenario_title.upper()[:28]}"
            elif is_autonomous:
                category = "Autonomous Creations"
                album_name = "🎨 Autonomous Creations"
                badge_text = f"🎨 AUTONOMOUS ART // {(style or 'Original Painting').upper()[:24]}"
            else:
                category = "Shared Moments"
                album_name = "📸 Shared Moments"
                tier_str = work_meta.get("tier") or gal_meta.get("tier") or ""
                badge_text = f"📸 SHARED MOMENT" + (f" // {tier_str.upper()}" if tier_str else "")

            # Resolve Title
            title = (
                gal_meta.get("scrapbook_title")
                or work_entry.get("title")
                or scenario_title
                or fname
            )

            # Resolve Natural Scrapbook Caption (Zero per-turn prompt overhead)
            saved_caption = str(gal_meta.get("scrapbook_caption", "")).strip()
            spoken_reflection = str(work_entry.get("content") or gal_meta.get("caption") or "").strip()
            raw_prompt = str(gal_entry.get("prompt") or work_entry.get("prompt") or "").strip()

            if saved_caption:
                caption = saved_caption
            elif spoken_reflection:
                caption = spoken_reflection
            elif raw_prompt:
                caption = _clean_prompt_for_fallback_caption(raw_prompt)
            else:
                caption = f"Captured memory ({fname}). Click '✨ Reminisce' to have Calypso reflect on this photo."

            tags = gal_meta.get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]

            entries.append({
                "path": img_path,
                "file_name": fname,
                "mtime": img_path.stat().st_mtime,
                "title": title,
                "caption": caption,
                "raw_prompt": raw_prompt,
                "category": category,
                "album_name": album_name,
                "badge_text": badge_text,
                "scenario_title": scenario_title,
                "scenario_id": scenario_id,
                "is_autonomous": is_autonomous,
                "tags": tags,
                "tier": work_meta.get("tier") or gal_meta.get("tier") or ""
            })

        self.all_entries = entries

        # Build filter menu options
        filter_options = [
            f"All Memories ({len(entries)})",
            "📸 Shared Moments",
            "🎨 Autonomous Creations",
            "🎭 All Roleplay Scenarios"
        ]
        for sc_album in sorted(scenario_albums_found):
            filter_options.append(sc_album)

        self.album_filter_menu.configure(values=filter_options)

        if not preserve_filter or not any(
            self._matches_filter(e, self.current_filter) for e in self.all_entries
        ):
            self.current_filter = filter_options[0]

        self.album_filter_menu.set(self.current_filter)
        self._apply_filter()

    def _matches_filter(self, entry: Dict[str, Any], filter_label: str) -> bool:
        if not filter_label or filter_label.startswith("All Memories"):
            return True
        if filter_label == "📸 Shared Moments":
            return entry["category"] == "Shared Moments"
        if filter_label == "🎨 Autonomous Creations":
            return entry["category"] == "Autonomous Creations"
        if filter_label == "🎭 All Roleplay Scenarios":
            return entry["category"] == "Roleplay Scenarios"
        if filter_label.startswith("🎭 "):
            return entry["album_name"] == filter_label
        return True

    def _on_filter_selected(self, selected_value: str):
        self.current_filter = selected_value
        self._apply_filter()

    def _toggle_sort_order(self):
        self.newest_first = not self.newest_first
        self.sort_btn.configure(text="🔽 Newest First" if self.newest_first else "🔼 Oldest First")
        self.all_entries.sort(key=lambda e: e["mtime"], reverse=self.newest_first)
        self._apply_filter()

    def _apply_filter(self):
        self.filtered_entries = [
            e for e in self.all_entries if self._matches_filter(e, self.current_filter)
        ]

        # Clear sidebar buttons
        for child in self.scrollable_list.winfo_children():
            child.destroy()
        self.sidebar_buttons.clear()

        self.scrollable_list.configure(label_text=f"Photos ({len(self.filtered_entries)})")

        for idx, entry in enumerate(self.filtered_entries):
            icon = "🎭" if entry["category"] == "Roleplay Scenarios" else ("🎨" if entry["is_autonomous"] else "📷")
            dt_short = datetime.fromtimestamp(entry["mtime"]).strftime("%b %d")
            short_title = entry["title"].replace("\n", " ")[:18]
            btn_text = f"{icon} {dt_short} • {short_title}"

            btn = ctk.CTkButton(
                self.scrollable_list,
                text=btn_text,
                anchor="w",
                height=30,
                fg_color="transparent",
                hover_color="#1e293b",
                text_color="#e2e8f0",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                command=lambda i=idx: self.select_page(i)
            )
            btn.pack(fill="x", padx=4, pady=2)
            self.sidebar_buttons.append(btn)

        if self.filtered_entries:
            self.current_index = min(self.current_index, len(self.filtered_entries) - 1)
            self.select_page(self.current_index)
        else:
            self._show_empty_state()

    def _show_empty_state(self):
        self.album_badge_lbl.configure(text="📖 EMPTY ALBUM")
        self.page_counter_lbl.configure(text="Page 0 of 0")
        self.memory_title_lbl.configure(text="No Memories in This Album Yet")
        self.photo_frame.configure(
            text="No photos match the current album filter.\nCreate scenes during roleplay or conversation to fill your scrapbook!",
            image=None,
            text_color="#5D4037",
            font=ctk.CTkFont(family="Georgia", size=14, slant="italic")
        )
        self.date_label.configure(text="")
        self.tags_label.configure(text="")
        self.description_box.configure(state="normal")
        self.description_box.delete("1.0", tk.END)
        self.description_box.configure(state="disabled")
        self.analyze_btn.configure(state="disabled")
        self.save_note_btn.configure(state="disabled")
        self.purge_btn.configure(state="disabled")

    # -------------------------------------------------------------------------
    # PAGE DISPLAY & NAVIGATION
    # -------------------------------------------------------------------------
    def select_page(self, index: int):
        """Switches the scrapbook layout to the designated photo index."""
        if not self.filtered_entries:
            self._show_empty_state()
            return

        self.current_index = max(0, min(index, len(self.filtered_entries) - 1))
        entry = self.filtered_entries[self.current_index]
        img_path: Path = entry["path"]

        # Highlight active sidebar button
        for idx, btn in enumerate(self.sidebar_buttons):
            if btn.winfo_exists():
                btn.configure(
                    fg_color="#2563eb" if idx == self.current_index else "transparent",
                    text_color="#ffffff" if idx == self.current_index else "#e2e8f0"
                )

        self.analyze_btn.configure(state="normal")
        self.save_note_btn.configure(state="normal")
        self.purge_btn.configure(state="normal")
        self.status_lbl.configure(text="")

        self.album_badge_lbl.configure(text=entry["badge_text"])
        self.page_counter_lbl.configure(text=f"Page {self.current_index + 1} of {len(self.filtered_entries)}")
        self.memory_title_lbl.configure(text=entry["title"])

        date_str = datetime.fromtimestamp(entry["mtime"]).strftime("🗓️ %B %d, %Y at %I:%M %p")
        self.date_label.configure(text=date_str)

        if entry.get("tags"):
            self.tags_label.configure(text="🏷️ " + " • ".join(entry["tags"]))
        else:
            self.tags_label.configure(text="")

        # Populate editable caption box
        self.description_box.configure(state="normal")
        self.description_box.delete("1.0", tk.END)
        self.description_box.insert("1.0", entry["caption"])

        # Render Resized Image Asset inside photo mat
        try:
            with Image.open(img_path) as raw_pil:
                pil_img = ImageOps.exif_transpose(raw_pil).copy()
            pil_img.thumbnail((660, 410), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=pil_img.size)

            self.photo_frame.configure(image=ctk_img, text="")
            self.photo_frame.image = ctk_img
        except Exception as e:
            self.photo_frame.configure(text=f"Error loading image asset:\n{e}", image=None)

    def prev_page(self):
        if not self.filtered_entries:
            return
        new_idx = (self.current_index - 1) % len(self.filtered_entries)
        self.select_page(new_idx)

    def next_page(self):
        if not self.filtered_entries:
            return
        new_idx = (self.current_index + 1) % len(self.filtered_entries)
        self.select_page(new_idx)

    def _on_photo_click(self, event=None):
        """Opens the current photo in BorderlessViewer when clicked."""
        if not self.filtered_entries:
            return
        entry = self.filtered_entries[self.current_index]
        if callable(self.open_viewer_callback):
            self.open_viewer_callback(entry["path"], interval=0)

    # -------------------------------------------------------------------------
    # PERSISTING CAPTIONS & TAGS TO GALLERY_HISTORY.JSON
    # -------------------------------------------------------------------------
    def _persist_scrapbook_metadata(self, file_name: str, caption: str = None, tags: list = None):
        mem_dir = getattr(self.memory_engine, "memory_dir", config.MEMORY_DIR)
        gallery_file = mem_dir / "gallery_history.json"
        history = []
        if gallery_file.exists():
            try:
                with open(gallery_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []

        matched = False
        for item in history:
            item_fname = item.get("file_name") or Path(str(item.get("file_path", ""))).name
            if item_fname == file_name:
                meta = item.setdefault("metadata", {})
                if caption is not None:
                    meta["scrapbook_caption"] = caption
                if tags is not None:
                    meta["tags"] = tags
                matched = True

        if not matched and self.filtered_entries:
            entry = self.filtered_entries[self.current_index]
            meta = {}
            if caption is not None:
                meta["scrapbook_caption"] = caption
            if tags is not None:
                meta["tags"] = tags
            history.append({
                "timestamp": datetime.fromtimestamp(entry["mtime"]).strftime("%Y-%m-%d %H:%M:%S"),
                "file_name": file_name,
                "file_path": str(entry["path"]),
                "prompt": entry.get("raw_prompt", ""),
                "negative_prompt": "",
                "metadata": meta
            })

        try:
            gallery_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = gallery_file.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
            tmp.replace(gallery_file)
        except Exception as e:
            logger.error(f"[Scrapbook] Could not save scrapbook metadata: {e}")

    def _on_save_caption(self):
        if not self.filtered_entries:
            return
        entry = self.filtered_entries[self.current_index]
        new_caption = self.description_box.get("1.0", "end-1c").strip()
        entry["caption"] = new_caption
        self._persist_scrapbook_metadata(entry["file_name"], caption=new_caption)
        self.status_lbl.configure(text="✓ Caption saved to scrapbook!")

    # -------------------------------------------------------------------------
    # INTERACTIVE VISION REMINISCENCE VIA MEDIAPROCESSOR
    # -------------------------------------------------------------------------
    def _on_vision_reminisce(self):
        if not self.filtered_entries or self._is_analyzing:
            return

        entry = self.filtered_entries[self.current_index]
        img_path: Path = entry["path"]
        self._is_analyzing = True

        self.analyze_btn.configure(state="disabled", text="✨ Reminiscing...")
        self.status_lbl.configure(text="Calypso is looking closely at this photo...")

        context_parts = []
        if entry.get("scenario_title"):
            context_parts.append(f"Roleplay Scenario: '{entry['scenario_title']}'")
        if entry.get("title") and entry["title"] != entry["file_name"]:
            context_parts.append(f"Title: '{entry['title']}'")
        context_hint = " | ".join(context_parts)

        def _worker():
            try:
                caption_res = self.media_processor.run_analysis(
                    img_path, mode='scrapbook', context_hint=context_hint
                )
                tags_res = self.media_processor.run_analysis(img_path, mode='tag')
                tag_list = [
                    t.strip() for t in tags_res.split(",")
                    if t.strip() and not t.strip().startswith("[Notice:")
                ][:7]
            except Exception as e:
                caption_res = f"[Notice: Vision analysis encountered an error: {e}]"
                tag_list = []

            def _apply_ui():
                self._is_analyzing = False
                if not self.winfo_exists():
                    return
                self.analyze_btn.configure(state="normal", text="✨ Reminisce (Vision Analyze)")

                if caption_res and not caption_res.startswith("[Notice:"):
                    entry["caption"] = caption_res
                    if tag_list:
                        entry["tags"] = tag_list
                    self._persist_scrapbook_metadata(
                        entry["file_name"],
                        caption=caption_res,
                        tags=tag_list if tag_list else None
                    )

                    # Refresh UI if still on the same photo
                    if self.filtered_entries and self.filtered_entries[self.current_index]["file_name"] == entry["file_name"]:
                        self.description_box.configure(state="normal")
                        self.description_box.delete("1.0", tk.END)
                        self.description_box.insert("1.0", caption_res)
                        if tag_list:
                            self.tags_label.configure(text="🏷️ " + " • ".join(tag_list))
                        self.status_lbl.configure(text="✨ Calypso penned a new scrapbook memory!")
                else:
                    self.status_lbl.configure(text=caption_res or "Vision analysis unavailable.")

            self.after(0, _apply_ui)

        threading.Thread(target=_worker, daemon=True).start()

    # -------------------------------------------------------------------------
    # SHARE MEMORY IN CHAT
    # -------------------------------------------------------------------------
    def _on_share_in_chat(self):
        if not self.filtered_entries or self.input_queue is None:
            return
        entry = self.filtered_entries[self.current_index]
        caption_text = self.description_box.get("1.0", "end-1c").strip() or entry["caption"]
        album_ctx = f" from our '{entry['scenario_title']}' scenario" if entry.get("scenario_title") else ""
        stimulus = (
            f"[System Notice: Your companion is looking through your shared Digital Scrapbook with you "
            f"and pointed to the photo '{entry['title']}'{album_ctx}. "
            f"Scrapbook Note: \"{caption_text[:300]}\". "
            f"Reminisce warmly about this captured moment together.]"
        )
        self.input_queue.put(stimulus)
        self.status_lbl.configure(text="💬 Shared with Calypso in chat!")

    # -------------------------------------------------------------------------
    # COMPLETE PURGE OF DEFECTIVE PHOTOS
    # -------------------------------------------------------------------------
    def _on_purge_current_photo(self):
        if not self.filtered_entries:
            return

        entry = self.filtered_entries[self.current_index]
        img_path: Path = entry["path"]

        confirm = messagebox.askyesno(
            "Purge Photo from Scrapbook",
            f"Permanently delete '{entry['file_name']}'?\n\n"
            "This will completely purge the image file from disk, gallery history, "
            "creative works, and ChromaDB memory.",
            parent=self.winfo_toplevel()
        )
        if not confirm:
            return

        if self.memory_engine and hasattr(self.memory_engine, "purge_image_asset"):
            self.memory_engine.purge_image_asset(img_path)
        else:
            standalone_purge_image_asset(img_path)

        # Remove from in-memory lists and refresh
        self.all_entries = [e for e in self.all_entries if e["file_name"] != entry["file_name"]]
        self._apply_filter()
        self.status_lbl.configure(text=f"🗑️ Purged '{entry['file_name']}' completely.")


class ScrapbookWindow(ctk.CTkToplevel):
    """Toplevel modal window launched from Calypso's GUIEngine."""
    def __init__(
        self,
        parent,
        album_dir: str | Path = None,
        media_processor: Optional[MediaProcessor] = None,
        memory_engine=None,
        scenario_engine=None,
        input_queue=None,
        open_viewer_callback=None,
        initial_filter: Optional[str] = None
    ):
        super().__init__(parent)
        self.title("✨ Calypso's Digital Scrapbook Album ✨")
        self.geometry("1140x780")
        self.minsize(980, 680)
        self.configure(fg_color="#10131a")

        self.view = ScrapbookView(
            self,
            album_dir=album_dir,
            media_processor=media_processor,
            memory_engine=memory_engine,
            scenario_engine=scenario_engine,
            input_queue=input_queue,
            open_viewer_callback=open_viewer_callback,
            initial_filter=initial_filter
        )
        self.view.pack(fill="both", expand=True)

        # Keyboard navigation shortcuts (active when typing isn't focused in textbox)
        self.bind("<Left>", self._handle_left_key)
        self.bind("<Right>", self._handle_right_key)
        self.bind("<Escape>", lambda e: self.destroy())

        self.after(100, self.lift)
        self.after(120, self.focus_force)

    def _handle_left_key(self, event):
        if isinstance(event.widget, tk.Text):
            return
        self.view.prev_page()

    def _handle_right_key(self, event):
        if isinstance(event.widget, tk.Text):
            return
        self.view.next_page()


class ScrapbookApp(ctk.CTk):
    """Standalone application wrapper for running modules/scrap_book.py directly."""
    def __init__(self, album_dir: str | Path = None):
        super().__init__()
        self.title("✨ Calypso's Digital Scrapbook Album ✨")
        self.geometry("1140x780")
        self.minsize(980, 680)

        self.view = ScrapbookView(self, album_dir=album_dir or config.IMAGES_OUTPUT_DIR)
        self.view.pack(fill="both", expand=True)


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    os.makedirs(config.IMAGES_OUTPUT_DIR, exist_ok=True)
    app = ScrapbookApp(config.IMAGES_OUTPUT_DIR)
    app.mainloop()
