# modules/calendar_manager.py

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from modules.config import config

logger = logging.getLogger("Calypso.Calendar")


class CalendarManager:
    def __init__(self):
        self.storage_file = config.MEMORY_DIR / "calendar_events.json"
        self.events: Dict[str, List[dict]] = {}
        self.load_events()

    def load_events(self):
        if self.storage_file.exists():
            try:
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    self.events = json.load(f)
            except Exception as e:
                logger.error(f"[Calendar] Failed to load events: {e}")
                self.events = {}
        else:
            self.events = {}

    def save_events(self):
        try:
            tmp_file = self.storage_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.events, f, indent=2)
            tmp_file.replace(self.storage_file)
        except Exception as e:
            logger.error(f"[Calendar] Failed to save events: {e}")

    def get_events_for_date(self, date_str: str) -> List[dict]:
        """Returns all events for a given YYYY-MM-DD string."""
        return self.events.get(date_str, [])

    def add_event(self, date_str: str, title: str, time_str: Optional[str] = "", notes: Optional[str] = "") -> dict:
        """
        Adds an event to a specified date.
        date_str: 'YYYY-MM-DD'
        time_str: e.g. '08:30', '7:00 PM', or ''
        """
        if date_str not in self.events:
            self.events[date_str] = []

        event = {
            "id": f"evt_{uuid.uuid4().hex[:8]}",
            "title": title.strip(),
            "time": time_str.strip() if time_str else "",
            "notes": notes.strip() if notes else "",
            "created_at": datetime.now().isoformat()
        }
        self.events[date_str].append(event)
        self.save_events()
        return event

    def delete_event(self, date_str: str, event_id: str) -> bool:
        if date_str in self.events:
            initial_len = len(self.events[date_str])
            self.events[date_str] = [e for e in self.events[date_str] if e.get("id") != event_id]
            if not self.events[date_str]:
                del self.events[date_str]
            self.save_events()
            return len(self.events.get(date_str, [])) < initial_len
        return False

    def has_events(self, date_str: str) -> bool:
        return bool(self.events.get(date_str))
