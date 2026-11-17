# modules/emotion/temporal.py

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from modules.config import config
from modules.settings_manager import settings_manager

logger = logging.getLogger("EmotionEngine.Temporal")


class TemporalEngine:
    """
    Lightweight Temporal Ledger & Calendar Index for Calypso.
    Tracks:
      1. Annual Recurring Key Dates (birthdays, milestone anniversaries)
      2. One-off Scheduled Events (upcoming plans, appointments, deadlines)
      3. Post-Event Follow-ups (asking how a recent event went)
    """

    def __init__(self, character_name: str = None, memory_engine=None):
        if not character_name:
            character_name = settings_manager.get("ai_name", "Calypso")
        self.character_name = character_name.lower().strip()
        self.memory_dir = config.MEMORY_DIR
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self.ledger_file = self.memory_dir / f"temporal_ledger_{self.character_name}.json"
        self.lock = threading.RLock()

        self.data = self._load_or_init_ledger()
        if memory_engine:
            self.sync_milestone_anniversaries(memory_engine)

    def _load_or_init_ledger(self) -> dict:
        if self.ledger_file.exists():
            try:
                with open(self.ledger_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        loaded.setdefault("recurring_dates", [])
                        loaded.setdefault("events", [])
                        loaded.setdefault("last_daily_boost_date", "")
                        return loaded
            except Exception as e:
                logger.error(f"[Temporal] Failed to load ledger: {e}")

        defaults = {
            "recurring_dates": [],
            "events": [],
            "last_daily_boost_date": ""
        }
        self.save_ledger(defaults)
        return defaults

    def save_ledger(self, data_dict: dict = None):
        with self.lock:
            target = data_dict if data_dict is not None else self.data
            tmp_file = self.ledger_file.with_suffix(".tmp")
            try:
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(target, f, indent=4)
                os.replace(tmp_file, self.ledger_file)
                self.data = target
            except Exception as e:
                logger.error(f"[Temporal] Failed to save ledger: {e}")
                if tmp_file.exists():
                    tmp_file.unlink(missing_ok=True)

    # -------------------------------------------------------------------------
    # MILESTONE ANNIVERSARY SEEDING
    # -------------------------------------------------------------------------
    def sync_milestone_anniversaries(self, memory_engine) -> int:
        """
        Seeds anchored milestones from core_facts into recurring_dates if they have
        a valid created_at timestamp and aren't already tracked.
        """
        if not memory_engine or not hasattr(memory_engine, "core_facts"):
            return 0

        milestones = memory_engine.core_facts.get("key_milestones", [])
        added = 0
        with self.lock:
            existing_titles = {
                r.get("title", "").lower() for r in self.data.get("recurring_dates", [])
            }
            for m in milestones:
                if not isinstance(m, dict) or not m.get("is_anchor"):
                    continue
                m_text = m.get("text", "").strip()
                created_at = m.get("created_at", "").strip()
                if not m_text or not created_at:
                    continue

                anniv_title = f"Anniversary: {m_text}"
                if anniv_title.lower() in existing_titles or m_text.lower() in existing_titles:
                    continue

                try:
                    dt = datetime.strptime(created_at[:10], "%Y-%m-%d")
                    self.data["recurring_dates"].append({
                        "id": f"anniv_{uuid.uuid4().hex[:6]}",
                        "title": anniv_title,
                        "month": dt.month,
                        "day": dt.day,
                        "origin_year": dt.year,
                        "category": "anniversary",
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                    })
                    existing_titles.add(anniv_title.lower())
                    added += 1
                except Exception:
                    continue

            if added > 0:
                self.save_ledger()
                logger.info(f"[Temporal] Seeded {added} anchored milestone anniversary date(s).")
        return added

    # -------------------------------------------------------------------------
    # ADD / REMOVE / PARSE DATES
    # -------------------------------------------------------------------------
    def add_entry(
        self,
        date_str: str,
        title: str,
        recurrence: str = "once",
        category: str = "general",
        notes: str = ""
    ) -> Tuple[bool, str, Optional[dict]]:
        """
        Adds either an annual recurring date or a one-time scheduled event.
        Accepts YYYY-MM-DD or MM-DD.
        """
        clean_title = (title or "").strip().rstrip(".")
        if not clean_title:
            return False, "Event title cannot be empty.", None

        clean_date = (date_str or "").strip()
        rec_mode = (recurrence or "once").strip().lower()
        is_annual = rec_mode in ("annual", "recurring", "yearly", "birthday", "anniversary")

        now_today = date.today()
        parsed_date = None

        # Try YYYY-MM-DD
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m-%d", "%m/%d", "%B %d", "%b %d", "%B %d, %Y", "%b %d, %Y"):
            try:
                dt = datetime.strptime(clean_date, fmt)
                if "%Y" not in fmt:
                    year = now_today.year
                    candidate = date(year, dt.month, dt.day)
                    if candidate < now_today and not is_annual:
                        candidate = date(year + 1, dt.month, dt.day)
                    parsed_date = candidate
                else:
                    parsed_date = dt.date()
                break
            except ValueError:
                continue

        if not parsed_date:
            return False, f"Unrecognized date format '{clean_date}'. Use YYYY-MM-DD or MM-DD.", None

        with self.lock:
            if is_annual:
                # Avoid duplicate recurring entries
                for r in self.data["recurring_dates"]:
                    if r.get("title", "").lower() == clean_title.lower() and r.get("month") == parsed_date.month and r.get("day") == parsed_date.day:
                        return False, f"Recurring date '{clean_title}' is already on the calendar.", r

                cat = "birthday" if "birthday" in clean_title.lower() else ("anniversary" if "anniv" in clean_title.lower() else category)
                entry = {
                    "id": f"rec_{uuid.uuid4().hex[:6]}",
                    "title": clean_title,
                    "month": parsed_date.month,
                    "day": parsed_date.day,
                    "origin_year": parsed_date.year,
                    "category": cat,
                    "notes": notes,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                }
                self.data["recurring_dates"].append(entry)
                self.save_ledger()
                pretty_d = parsed_date.strftime("%B %d")
                logger.info(f"[Temporal] Added annual key date: '{clean_title}' on {pretty_d}")
                return True, f"Saved annual date: '{clean_title}' ({pretty_d})", entry

            else:
                target_iso = parsed_date.strftime("%Y-%m-%d")
                for e in self.data["events"]:
                    if e.get("title", "").lower() == clean_title.lower() and e.get("target_date") == target_iso:
                        return False, f"Event '{clean_title}' on {target_iso} is already logged.", e

                target_dt = datetime.combine(parsed_date, datetime.min.time())
                entry = {
                    "id": f"evt_{uuid.uuid4().hex[:6]}",
                    "title": clean_title,
                    "target_date": target_iso,
                    "target_epoch": int(target_dt.timestamp()),
                    "category": category,
                    "notes": notes,
                    "followed_up": False,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                }
                self.data["events"].append(entry)
                # Keep events sorted chronologically
                self.data["events"].sort(key=lambda x: x.get("target_date", "9999-99-99"))
                self.save_ledger()
                pretty_d = parsed_date.strftime("%A, %b %d, %Y")
                logger.info(f"[Temporal] Added event: '{clean_title}' on {target_iso}")
                return True, f"Scheduled '{clean_title}' for {pretty_d}", entry

    def parse_and_add_tag(self, raw_tag_val: str) -> Tuple[bool, str, Optional[dict]]:
        """
        Parses protocol tag payload: 'YYYY-MM-DD | Event Title | once/annual'
        """
        if not raw_tag_val:
            return False, "Empty tag payload.", None
        parts = [p.strip() for p in raw_tag_val.split("|")]
        if len(parts) < 2:
            return False, f"Malformed REMEMBER_DATE tag: '{raw_tag_val}'", None

        date_part = parts[0]
        title_part = parts[1]
        rec_part = parts[2].lower() if len(parts) >= 3 else "once"
        if any(w in title_part.lower() for w in ("birthday", "anniversary")):
            rec_part = "annual"

        return self.add_entry(date_str=date_part, title=title_part, recurrence=rec_part)

    def remove_entry(self, query_id_or_title: str) -> Tuple[bool, str]:
        q = (query_id_or_title or "").strip().lower()
        if not q:
            return False, "Specify an event ID or title to remove."

        with self.lock:
            for lst_key in ("events", "recurring_dates"):
                original_len = len(self.data[lst_key])
                kept = []
                removed_title = None
                for item in self.data[lst_key]:
                    if item.get("id", "").lower() == q or q in item.get("title", "").lower():
                        if removed_title is None:
                            removed_title = item.get("title")
                        else:
                            kept.append(item)
                    else:
                        kept.append(item)
                if len(kept) < original_len:
                    self.data[lst_key] = kept
                    self.save_ledger()
                    return True, f"Removed '{removed_title}' from Temporal Ledger."

        return False, f"No calendar entry matching '{query_id_or_title}' found."

    # -------------------------------------------------------------------------
    # RADAR SCAN & PROMPT INJECTION
    # -------------------------------------------------------------------------
    def scan_radar(self, lookahead_days: int = 7, lookback_days: int = 4) -> dict:
        """
        Scans the ledger relative to today's date and returns categorized items:
          - today_items: list of dicts
          - upcoming_items: list of (days_away, dict)
          - needs_followup: list of (days_ago, dict)
        """
        today = date.today()
        today_items = []
        upcoming_items = []
        needs_followup = []

        with self.lock:
            # 1. Check Annual Recurring Dates
            for rec in self.data.get("recurring_dates", []):
                try:
                    m = int(rec.get("month", 1))
                    d = int(rec.get("day", 1))
                    try:
                        next_occ = date(today.year, m, d)
                    except ValueError:
                        # Handle Feb 29 on non-leap years
                        next_occ = date(today.year, m, 28)

                    if next_occ < today:
                        try:
                            next_occ = date(today.year + 1, m, d)
                        except ValueError:
                            next_occ = date(today.year + 1, m, 28)

                    delta_days = (next_occ - today).days
                    if delta_days == 0:
                        today_items.append({"type": "recurring", "entry": rec, "date_obj": next_occ})
                    elif 0 < delta_days <= lookahead_days:
                        upcoming_items.append((delta_days, {"type": "recurring", "entry": rec, "date_obj": next_occ}))
                except Exception:
                    continue

            # 2. Check One-Off Events
            for evt in self.data.get("events", []):
                try:
                    t_date = datetime.strptime(evt.get("target_date", ""), "%Y-%m-%d").date()
                    delta_days = (t_date - today).days

                    if delta_days == 0:
                        today_items.append({"type": "event", "entry": evt, "date_obj": t_date})
                    elif 0 < delta_days <= lookahead_days:
                        upcoming_items.append((delta_days, {"type": "event", "entry": evt, "date_obj": t_date}))
                    elif -lookback_days <= delta_days < 0 and not evt.get("followed_up", False):
                        needs_followup.append((abs(delta_days), {"type": "event", "entry": evt, "date_obj": t_date}))
                except Exception:
                    continue

        upcoming_items.sort(key=lambda x: x[0])
        needs_followup.sort(key=lambda x: x[0])

        return {
            "today": today_items,
            "upcoming": upcoming_items,
            "followup": needs_followup
        }

    def mark_followups_completed(self, followup_items: list):
        """Marks recently passed events as followed_up=True so Calypso only asks once."""
        if not followup_items:
            return
        with self.lock:
            changed = False
            target_ids = {item[1]["entry"].get("id") for item in followup_items if "entry" in item[1]}
            for evt in self.data.get("events", []):
                if evt.get("id") in target_ids and not evt.get("followed_up"):
                    evt["followed_up"] = True
                    changed = True
            if changed:
                self.save_ledger()

    def apply_daily_limbic_resonance(self, neuro=None, affinity=None, gui=None):
        """
        If today matches a special date or scheduled event, applies a once-per-day
        limbic & affinity charge so Calypso genuinely feels the occasion.
        """
        today_iso = date.today().strftime("%Y-%m-%d")
        with self.lock:
            if self.data.get("last_daily_boost_date") == today_iso:
                return
            radar = self.scan_radar(lookahead_days=2, lookback_days=1)
            today_matches = radar.get("today", [])
            if not today_matches:
                return

            self.data["last_daily_boost_date"] = today_iso
            self.save_ledger()

        titles = [m["entry"].get("title", "Special Event") for m in today_matches]
        joined_titles = ", ".join(titles)

        if neuro:
            with neuro.lock:
                neuro.chemicals["dopamine"] = min(1.0, neuro.chemicals.get("dopamine", 0.5) + 0.22)
                neuro.chemicals["oxytocin"] = min(1.0, neuro.chemicals.get("oxytocin", 0.5) + 0.25)
                neuro.chemicals["serotonin"] = min(1.0, neuro.chemicals.get("serotonin", 0.5) + 0.15)
                neuro.calculate_valence()
                neuro.save_state()

        if affinity:
            affinity.add_charge("Romance", 0.20)
            affinity.add_charge("Harmony", 0.20)
            affinity.add_charge("Nostalgia", 0.20)

        if gui and hasattr(gui, "append_system_notice"):
            gui.append_system_notice(f"📅 [Key Date Today]: {joined_titles} — Limbic warmth & anticipation elevated.")

    def get_calendar_prompt_block(self, mark_followed_up: bool = True) -> str:
        """
        Returns a compact markdown section to append to ### TEMPORAL ORIENTATION
        when there are active today events, upcoming events (next 7 days), or follow-ups.
        """
        radar = self.scan_radar(lookahead_days=7, lookback_days=4)
        lines = []

        for item in radar["today"]:
            e = item["entry"]
            lines.append(f"- 🌟 TODAY'S KEY EVENT: \"{e.get('title')}\" (Acknowledge or celebrate naturally!)")

        for days_away, item in radar["upcoming"]:
            e = item["entry"]
            dt_str = item["date_obj"].strftime("%a, %b %d")
            day_word = "Tomorrow" if days_away == 1 else f"In {days_away} days ({dt_str})"
            lines.append(f"- Upcoming ({day_word}): \"{e.get('title')}\"")

        if radar["followup"]:
            for days_ago, item in radar["followup"]:
                e = item["entry"]
                ago_word = "Yesterday" if days_ago == 1 else f"{days_ago} days ago"
                lines.append(
                    f"- Recent Event Follow-Up ({ago_word}): \"{e.get('title')}\" just passed—ask your companion how it went!"
                )
            if mark_followed_up:
                self.mark_followups_completed(radar["followup"])

        if not lines:
            return ""

        return "### CALENDAR & KEY DATES RADAR:\n" + "\n".join(lines)

    def format_ledger_summary(self) -> str:
        """Formats all recurring dates and upcoming events for the /calendar slash command."""
        with self.lock:
            rec_list = self.data.get("recurring_dates", [])
            evt_list = self.data.get("events", [])

            out = ["📅 [Temporal Ledger — Key Dates & Events]"]
            if rec_list:
                out.append("  • Annual Key Dates:")
                for r in rec_list:
                    d_str = f"{int(r.get('month', 1)):02d}-{int(r.get('day', 1)):02d}"
                    out.append(f"    - [{r.get('id')}] {d_str}: {r.get('title')}")
            else:
                out.append("  • Annual Key Dates: None")

            upcoming = [e for e in evt_list if not e.get("followed_up", False)]
            if upcoming:
                out.append("  • Scheduled Events:")
                for e in upcoming:
                    out.append(f"    - [{e.get('id')}] {e.get('target_date')}: {e.get('title')}")
            else:
                out.append("  • Scheduled Events: None")

            out.append("  (Usage: /calendar add YYYY-MM-DD | Title | once/annual  OR  /calendar del <id>)")
            return "\n".join(out)
