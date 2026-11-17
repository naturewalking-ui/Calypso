# modules/alarm_service.py

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Optional, Tuple
from modules.config import config

logger = logging.getLogger("Calypso.Alarm")


class AlarmService:
    def __init__(self):
        self.storage_file = config.MEMORY_DIR / "alarm_state.json"
        self.target_time_str: Optional[str] = None  # Stored as "HH:MM" 24h
        self.is_active: bool = False
        self.last_triggered_date: Optional[str] = None
        self.load_state()

    def set_alarm(self, time_input: str) -> Tuple[bool, str]:
        """
        Parses inputs like '7:30', '07:30', '7:30am', '8pm', '22:15'
        and arms the alarm.
        """
        clean_input = time_input.strip().lower()
        match = re.search(r'(\d{1,2}):?(\d{2})?\s*(am|pm)?', clean_input)

        if not match:
            return False, f"Could not parse time format: '{time_input}'. Use '7:30am' or '22:00'."

        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        meridiem = match.group(3)

        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return False, f"Invalid time: {hour:02d}:{minute:02d}"

        self.target_time_str = f"{hour:02d}:{minute:02d}"
        self.is_active = True
        self.last_triggered_date = None
        self.save_state()

        disp_meridiem = "AM" if hour < 12 else "PM"
        disp_hour = hour if 1 <= hour <= 12 else (hour - 12 if hour > 12 else 12)
        formatted_display = f"{disp_hour}:{minute:02d} {disp_meridiem}"

        logger.info(f"[Alarm] Armed for {self.target_time_str} ({formatted_display})")
        return True, f"Alarm set for {formatted_display}."

    def snooze(self, minutes: int = 10) -> str:
        """Pushes the target alarm time forward by X minutes."""
        now = datetime.now()
        snooze_target = now + timedelta(minutes=minutes)
        self.target_time_str = snooze_target.strftime("%H:%M")
        self.is_active = True
        self.last_triggered_date = None
        self.save_state()
        return f"Snoozed for {minutes} minutes. Alarm will trigger at {self.target_time_str}."

    def clear_alarm(self) -> str:
        self.is_active = False
        self.target_time_str = None
        self.save_state()
        return "Alarm disabled."

    def check_alarm_triggered(self) -> bool:
        """Polls whether current system clock matches the armed alarm."""
        if not self.is_active or not self.target_time_str:
            return False

        now = datetime.now()
        current_hm = now.strftime("%H:%M")
        today_str = now.strftime("%Y-%m-%d")

        if current_hm == self.target_time_str and self.last_triggered_date != today_str:
            self.last_triggered_date = today_str
            self.is_active = False  # Disarm after firing (or keep for repeat)
            self.save_state()
            return True

        return False

    def get_status_prompt(self) -> str:
        if not self.is_active or not self.target_time_str:
            return "No morning alarm is set."
        return f"Alarm armed for {self.target_time_str}."

    def save_state(self):
        try:
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump({
                    "target_time_str": self.target_time_str,
                    "is_active": self.is_active,
                    "last_triggered_date": self.last_triggered_date
                }, f, indent=2)
        except Exception as e:
            logger.error(f"[Alarm] Failed to save state: {e}")

    def load_state(self):
        if self.storage_file.exists():
            try:
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.target_time_str = data.get("target_time_str")
                    self.is_active = bool(data.get("is_active", False))
                    self.last_triggered_date = data.get("last_triggered_date")
            except Exception as e:
                logger.error(f"[Alarm] Failed to load state: {e}")
