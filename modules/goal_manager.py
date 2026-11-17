# modules/goal_manager.py

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from modules.calendar_manager import CalendarManager
from modules.config import config

logger = logging.getLogger("Calypso.GoalManager")


class GoalManager:
    """
    Standalone Personal Goal & Accountability Engine for Calypso.
    Stored completely outside the milestone system in `personal_goals.json`
    and synchronized with `CalendarManager` (`calendar_events.json`).

    Tracks quantitative & qualitative goals across 4 time-based checkpoints:
      - 25% Check-in (Reverie Inquiry + Partner Motivation)
      - 50% Check-in (Reverie Midpoint Accountability + Push)
      - 75% Check-in (Reverie Final-Stretch Focus)
      - 100% Check-in (Goal Finale GUI Card + Final Check-in Dialogue)
    """

    CHECKPOINT_PCTS = (25, 50, 75, 100)

    def __init__(self, calendar_manager: Optional[CalendarManager] = None):
        self.memory_dir = config.MEMORY_DIR
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.storage_file = self.memory_dir / "personal_goals.json"
        self.lock = threading.RLock()
        self.calendar_manager = calendar_manager or CalendarManager()
        self.goals: List[dict] = []
        self.load_goals()

    # -------------------------------------------------------------------------
    # PERSISTENCE
    # -------------------------------------------------------------------------
    def load_goals(self):
        with self.lock:
            if self.storage_file.exists():
                try:
                    with open(self.storage_file, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, list):
                            self.goals = loaded
                        elif isinstance(loaded, dict) and "goals" in loaded:
                            self.goals = loaded["goals"]
                        else:
                            self.goals = []
                except Exception as e:
                    logger.error(f"[GoalManager] Failed to load goals: {e}")
                    self.goals = []
            else:
                self.goals = []

    def save_goals(self):
        with self.lock:
            tmp_file = self.storage_file.with_suffix(".tmp")
            try:
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump({"goals": self.goals}, f, indent=2)
                os.replace(tmp_file, self.storage_file)
            except Exception as e:
                logger.error(f"[GoalManager] Failed to save goals: {e}")
                if tmp_file.exists():
                    tmp_file.unlink(missing_ok=True)

    # -------------------------------------------------------------------------
    # DATE & TIME PARSING
    # -------------------------------------------------------------------------
    @staticmethod
    def parse_target_date(raw_date_str: str) -> Optional[date]:
        """
        Parses YYYY-MM-DD, MM-DD, 'December 15', 'in 14 days', 'in 2 weeks', '3 months', etc.
        """
        clean = (raw_date_str or "").strip()
        if not clean:
            return None

        today = date.today()
        lower = clean.lower()

        if lower in ("today", "tonight"):
            return today
        if lower == "tomorrow":
            return today + timedelta(days=1)

        # Relative expressions: "in 10 days", "2 weeks", "3 months", "1 year"
        rel_match = re.search(r'(?:in\s+)?(\d+)\s*(day|days|week|weeks|month|months|year|years)', lower)
        if rel_match:
            amt = int(rel_match.group(1))
            unit = rel_match.group(2)
            if unit.startswith("day"):
                return today + timedelta(days=max(1, amt))
            if unit.startswith("week"):
                return today + timedelta(days=max(1, amt * 7))
            if unit.startswith("month"):
                return today + timedelta(days=max(1, amt * 30))
            if unit.startswith("year"):
                return today + timedelta(days=max(1, amt * 365))

        for fmt in (
            "%Y-%m-%d", "%Y/%m/%d", "%m-%d", "%m/%d",
            "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
            "%B %d", "%b %d"
        ):
            try:
                dt = datetime.strptime(clean, fmt)
                if "%Y" not in fmt:
                    candidate = date(today.year, dt.month, dt.day)
                    if candidate < today:
                        candidate = date(today.year + 1, dt.month, dt.day)
                    return candidate
                return dt.date()
            except ValueError:
                continue

        return None

    @staticmethod
    def _compute_target_epoch(target_d: date, time_str: str = "", start_epoch: float = None) -> int:
        now_ts = start_epoch if start_epoch is not None else time.time()
        parsed_hour, parsed_min = 18, 0  # Default to 6:00 PM on target date

        clean_t = (time_str or "").strip().lower()
        if clean_t:
            m = re.match(r'^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$', clean_t)
            if m:
                h = int(m.group(1))
                mins = int(m.group(2) or 0)
                meridiem = m.group(3)
                if meridiem == "pm" and h < 12:
                    h += 12
                elif meridiem == "am" and h == 12:
                    h = 0
                if 0 <= h <= 23 and 0 <= mins <= 59:
                    parsed_hour, parsed_min = h, mins

        target_dt = datetime(target_d.year, target_d.month, target_d.day, parsed_hour, parsed_min, 0)
        target_epoch = int(target_dt.timestamp())

        # If target_date is today and default/specified time already passed, set to end of tonight or +4 hours
        if target_epoch <= now_ts + 300:
            end_of_day = datetime(target_d.year, target_d.month, target_d.day, 23, 59, 0)
            if end_of_day.timestamp() > now_ts + 600:
                target_epoch = int(end_of_day.timestamp())
            else:
                target_epoch = int(now_ts + 3600 * 4)

        return target_epoch

    @classmethod
    def _build_checkpoints(cls, start_epoch: int, target_epoch: int) -> List[dict]:
        span = max(60, target_epoch - start_epoch)
        checkpoints = []
        for pct in cls.CHECKPOINT_PCTS:
            due_ts = int(start_epoch + span * (pct / 100.0))
            due_dt = datetime.fromtimestamp(due_ts)
            checkpoints.append({
                "pct": pct,
                "due_epoch": due_ts,
                "due_date": due_dt.strftime("%Y-%m-%d"),
                "due_time": due_dt.strftime("%H:%M"),
                "status": "pending",  # pending | surfaced | completed | skipped
                "snoozed_until": 0,
                "completed_at": "",
                "progress_note": ""
            })
        return checkpoints

    # -------------------------------------------------------------------------
    # CALENDAR SYNCHRONIZATION
    # -------------------------------------------------------------------------
    def _sync_goal_to_calendar(self, goal: dict):
        """
        Writes or refreshes the goal's 25%, 50%, 75%, and 100% entries inside
        `calendar_events.json` so the visual CalendarWindow displays them.
        """
        try:
            self.calendar_manager.load_events()
            goal_id = goal.get("id")
            if not goal_id:
                return

            # 1. Remove any prior calendar events tied to this goal_id
            for d_key in list(self.calendar_manager.events.keys()):
                filtered = [
                    ev for ev in self.calendar_manager.events[d_key]
                    if ev.get("goal_id") != goal_id
                ]
                if filtered:
                    self.calendar_manager.events[d_key] = filtered
                else:
                    del self.calendar_manager.events[d_key]

            # If goal is cancelled/deleted, just save the cleaned calendar
            status = goal.get("status", "active")
            if status == "cancelled":
                self.calendar_manager.save_events()
                return

            title = goal.get("title", "Personal Goal")
            criteria = goal.get("criteria", "")

            # 2. Add 25%, 50%, 75%, and 100% checkpoints to calendar_events.json
            for cp in goal.get("checkpoints", []):
                pct = cp.get("pct", 100)
                d_str = cp.get("due_date", goal.get("target_date"))
                t_str = cp.get("due_time", "")
                if not d_str:
                    continue

                if pct == 100:
                    if status == "achieved":
                        ev_title = f"🏆 [GOAL ACHIEVED] {title}"
                    else:
                        ev_title = f"🎯 [100% Goal Deadline] {title}"
                else:
                    chk_mark = "✓ " if cp.get("status") == "completed" else ""
                    ev_title = f"🎯 [{chk_mark}{pct}% Goal Check-in] {title}"

                if d_str not in self.calendar_manager.events:
                    self.calendar_manager.events[d_str] = []

                self.calendar_manager.events[d_str].append({
                    "id": f"goal_{goal_id}_{pct}",
                    "goal_id": goal_id,
                    "is_goal": True,
                    "checkpoint_pct": pct,
                    "title": ev_title,
                    "time": t_str,
                    "notes": criteria,
                    "created_at": goal.get("created_at", datetime.now().isoformat())
                })

            self.calendar_manager.save_events()
        except Exception as e:
            logger.error(f"[GoalManager] Calendar sync error: {e}")

    # -------------------------------------------------------------------------
    # CREATE / UPDATE / EXTEND / COMPLETE GOALS
    # -------------------------------------------------------------------------
    def create_goal(
        self,
        title: str,
        target_date_str: str,
        criteria: str = "",
        time_str: str = "",
        source: str = "chat"
    ) -> Tuple[bool, str, Optional[dict]]:
        clean_title = (title or "").strip().rstrip(".")
        if not clean_title:
            return False, "Goal title cannot be empty.", None

        parsed_d = self.parse_target_date(target_date_str)
        if not parsed_d:
            return False, f"Could not parse target date '{target_date_str}'. Use YYYY-MM-DD.", None

        target_iso = parsed_d.strftime("%Y-%m-%d")
        now_ts = int(time.time())
        target_epoch = self._compute_target_epoch(parsed_d, time_str=time_str, start_epoch=now_ts)

        with self.lock:
            # Check if an identical active goal already exists
            for g in self.goals:
                if g.get("status") == "active" and g.get("title", "").lower() == clean_title.lower():
                    return False, f"Active goal '{clean_title}' is already being tracked.", g

            goal_id = f"goal_{uuid.uuid4().hex[:6]}"
            checkpoints = self._build_checkpoints(now_ts, target_epoch)

            goal = {
                "id": goal_id,
                "title": clean_title,
                "criteria": (criteria or "").strip(),
                "source": source,
                "status": "active",  # active | achieved | cancelled
                "start_epoch": now_ts,
                "start_date": datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d"),
                "target_date": target_iso,
                "target_time": (time_str or "").strip(),
                "target_epoch": target_epoch,
                "checkpoints": checkpoints,
                "progress_log": [],
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
            }

            self.goals.append(goal)
            self.save_goals()
            self._sync_goal_to_calendar(goal)

        cp_summary = ", ".join(
            f"{c['pct']}% ({c['due_date']})" for c in checkpoints
        )
        msg = f"Goal '{clean_title}' locked in for {target_iso}. Check-ins scheduled at: {cp_summary}."
        logger.info(f"[GoalManager] {msg}")
        return True, msg, goal

    def parse_and_add_tag(self, raw_tag_val: str, source: str = "chat") -> Tuple[bool, str, Optional[dict]]:
        """
        Parses protocol tag payload:
          [SET_GOAL: YYYY-MM-DD | Goal Title | Quantitative or Qualitative Details]
        Also tolerates 2-part payload:
          [SET_GOAL: YYYY-MM-DD | Goal Title]
        """
        if not raw_tag_val:
            return False, "Empty SET_GOAL tag.", None

        parts = [p.strip() for p in raw_tag_val.split("|")]
        if len(parts) < 2:
            return False, f"Malformed SET_GOAL tag: '{raw_tag_val}'", None

        # Detect whether part[0] or part[1] is the date
        p0_date = self.parse_target_date(parts[0])
        if p0_date:
            date_str = parts[0]
            title_str = parts[1]
        else:
            p1_date = self.parse_target_date(parts[1])
            if p1_date:
                title_str = parts[0]
                date_str = parts[1]
            else:
                date_str = parts[0]
                title_str = parts[1]

        criteria_str = parts[2] if len(parts) >= 3 else ""
        return self.create_goal(
            title=title_str,
            target_date_str=date_str,
            criteria=criteria_str,
            source=source
        )

    def get_goal(self, goal_id_or_title: str) -> Optional[dict]:
        q = (goal_id_or_title or "").strip().lower()
        if not q:
            return None
        with self.lock:
            for g in self.goals:
                if g.get("id", "").lower() == q or q in g.get("title", "").lower():
                    return g
        return None

    def get_active_goals(self) -> List[dict]:
        with self.lock:
            return [g for g in self.goals if g.get("status") == "active"]

    def record_progress(
        self,
        goal_id_or_title: str,
        note: str,
        checkpoint_pct: Optional[int] = None
    ) -> Tuple[bool, str, Optional[dict]]:
        """
        Records a quantitative or qualitative progress update on a goal and marks
        the relevant checkpoint (or any currently surfaced checkpoint) as completed.
        """
        clean_note = (note or "").strip()
        if not clean_note:
            return False, "Progress note cannot be empty.", None

        with self.lock:
            goal = self.get_goal(goal_id_or_title)
            if not goal:
                active = self.get_active_goals()
                if len(active) == 1:
                    goal = active[0]
                else:
                    return False, f"No matching goal found for '{goal_id_or_title}'.", None

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            matched_pct = checkpoint_pct

            for cp in goal.get("checkpoints", []):
                if checkpoint_pct is not None and cp.get("pct") == checkpoint_pct:
                    if cp.get("pct") < 100:
                        cp["status"] = "completed"
                        cp["completed_at"] = now_str
                    cp["progress_note"] = clean_note
                    break
                elif checkpoint_pct is None and cp.get("status") == "surfaced":
                    matched_pct = cp.get("pct")
                    if matched_pct < 100:
                        cp["status"] = "completed"
                        cp["completed_at"] = now_str
                    cp["progress_note"] = clean_note
                    break

            goal.setdefault("progress_log", []).append({
                "timestamp": now_str,
                "checkpoint_pct": matched_pct or self.calculate_time_progress_pct(goal),
                "note": clean_note
            })

            self.save_goals()
            self._sync_goal_to_calendar(goal)
            return True, f"Logged progress for '{goal.get('title')}': {clean_note}", goal

    def record_progress_tag(self, raw_tag_val: str) -> Tuple[bool, str, Optional[dict]]:
        """
        Parses [GOAL_PROGRESS: goal_id_or_title | progress note]
        """
        if not raw_tag_val:
            return False, "Empty GOAL_PROGRESS payload.", None
        parts = [p.strip() for p in raw_tag_val.split("|", maxsplit=1)]
        if len(parts) == 1:
            return self.record_progress("", parts[0])
        return self.record_progress(parts[0], parts[1])

    def complete_goal(self, goal_id_or_title: str, final_note: str = "") -> Tuple[bool, str, Optional[dict]]:
        with self.lock:
            goal = self.get_goal(goal_id_or_title)
            if not goal:
                active = self.get_active_goals()
                if len(active) == 1:
                    goal = active[0]
                else:
                    return False, f"Goal '{goal_id_or_title}' not found.", None

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            goal["status"] = "achieved"
            goal["achieved_at"] = now_str
            for cp in goal.get("checkpoints", []):
                cp["status"] = "completed"
                if not cp.get("completed_at"):
                    cp["completed_at"] = now_str

            if final_note:
                goal.setdefault("progress_log", []).append({
                    "timestamp": now_str,
                    "checkpoint_pct": 100,
                    "note": final_note
                })

            self.save_goals()
            self._sync_goal_to_calendar(goal)
            return True, f"Goal '{goal.get('title')}' marked as ACHIEVED!", goal

    def extend_goal_deadline(
        self,
        goal_id_or_title: str,
        extra_days: int = 7,
        new_date_str: str = ""
    ) -> Tuple[bool, str, Optional[dict]]:
        with self.lock:
            goal = self.get_goal(goal_id_or_title)
            if not goal:
                return False, f"Goal '{goal_id_or_title}' not found.", None

            if new_date_str:
                new_d = self.parse_target_date(new_date_str)
            else:
                try:
                    curr_d = datetime.strptime(goal.get("target_date", ""), "%Y-%m-%d").date()
                except Exception:
                    curr_d = date.today()
                base_d = max(date.today(), curr_d)
                new_d = base_d + timedelta(days=max(1, extra_days))

            if not new_d:
                return False, "Invalid extension date.", None

            now_ts = int(time.time())
            new_target_epoch = self._compute_target_epoch(new_d, time_str=goal.get("target_time", ""), start_epoch=now_ts)
            goal["target_date"] = new_d.strftime("%Y-%m-%d")
            goal["target_epoch"] = new_target_epoch
            goal["status"] = "active"

            # Recompute remaining checkpoints (75% and 100% from now to new deadline)
            span = max(60, new_target_epoch - now_ts)
            for cp in goal.get("checkpoints", []):
                pct = cp.get("pct")
                if pct == 75:
                    due_ts = int(now_ts + span * 0.50)
                    dt = datetime.fromtimestamp(due_ts)
                    cp["due_epoch"] = due_ts
                    cp["due_date"] = dt.strftime("%Y-%m-%d")
                    cp["due_time"] = dt.strftime("%H:%M")
                    cp["status"] = "pending"
                    cp["snoozed_until"] = 0
                elif pct == 100:
                    dt = datetime.fromtimestamp(new_target_epoch)
                    cp["due_epoch"] = new_target_epoch
                    cp["due_date"] = dt.strftime("%Y-%m-%d")
                    cp["due_time"] = dt.strftime("%H:%M")
                    cp["status"] = "pending"
                    cp["snoozed_until"] = 0

            goal.setdefault("progress_log", []).append({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "checkpoint_pct": self.calculate_time_progress_pct(goal),
                "note": f"Deadline extended to {goal['target_date']}."
            })

            self.save_goals()
            self._sync_goal_to_calendar(goal)
            return True, f"Extended '{goal.get('title')}' deadline to {goal['target_date']}.", goal

    def remove_goal(self, goal_id_or_title: str) -> Tuple[bool, str]:
        with self.lock:
            goal = self.get_goal(goal_id_or_title)
            if not goal:
                return False, f"No goal matching '{goal_id_or_title}' found."

            goal["status"] = "cancelled"
            self._sync_goal_to_calendar(goal)
            self.goals = [g for g in self.goals if g.get("id") != goal.get("id")]
            self.save_goals()
            return True, f"Removed goal '{goal.get('title')}' and cleared its calendar check-ins."

    # -------------------------------------------------------------------------
    # CHECK-IN SCHEDULER & PROMPT BUILDERS (25% / 50% / 75% / 100%)
    # -------------------------------------------------------------------------
    @staticmethod
    def calculate_time_progress_pct(goal: dict) -> int:
        start_ts = float(goal.get("start_epoch", time.time()))
        target_ts = float(goal.get("target_epoch", start_ts + 1))
        span = max(1.0, target_ts - start_ts)
        elapsed = max(0.0, time.time() - start_ts)
        return min(100, int(round((elapsed / span) * 100)))

    def get_due_checkpoint(self) -> Optional[Tuple[dict, dict]]:
        """
        Scans active goals and returns (goal, checkpoint_dict) for the highest-priority
        due checkpoint (25%, 50%, 75%, or 100%) whose due_epoch <= now and is still pending.
        If multiple checkpoints on the same goal have passed while away, jumps to the latest due one
        and marks earlier ones skipped so the user isn't spammed with stale checkpoints.
        """
        now_ts = time.time()
        with self.lock:
            for goal in self.goals:
                if goal.get("status") != "active":
                    continue

                due_list = []
                for cp in goal.get("checkpoints", []):
                    if cp.get("status") == "pending" and now_ts >= cp.get("due_epoch", 0):
                        if now_ts >= cp.get("snoozed_until", 0):
                            due_list.append(cp)

                if not due_list:
                    continue

                # If more than one checkpoint passed while offline, skip older ones and surface the latest due one
                if len(due_list) > 1:
                    for older_cp in due_list[:-1]:
                        older_cp["status"] = "skipped"
                    self.save_goals()

                chosen_cp = due_list[-1]
                return goal, chosen_cp

        return None

    def mark_checkpoint_surfaced(self, goal_id: str, pct: int):
        with self.lock:
            goal = self.get_goal(goal_id)
            if not goal:
                return
            for cp in goal.get("checkpoints", []):
                if cp.get("pct") == pct:
                    cp["status"] = "surfaced"
                    break
            self.save_goals()

    def mark_checkpoint_completed(self, goal_id: str, pct: int, note: str = ""):
        with self.lock:
            goal = self.get_goal(goal_id)
            if not goal:
                return
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            for cp in goal.get("checkpoints", []):
                if cp.get("pct") == pct:
                    cp["status"] = "completed"
                    cp["completed_at"] = now_str
                    if note:
                        cp["progress_note"] = note
                    break
            self.save_goals()
            self._sync_goal_to_calendar(goal)

    def snooze_checkpoint(self, goal_id: str, pct: int, minutes: int = 30):
        with self.lock:
            goal = self.get_goal(goal_id)
            if not goal:
                return
            for cp in goal.get("checkpoints", []):
                if cp.get("pct") == pct:
                    cp["status"] = "pending"
                    cp["snoozed_until"] = int(time.time() + minutes * 60)
                    break
            self.save_goals()

    def force_trigger_checkpoint(self, goal_id_or_title: str, pct: int) -> Optional[Tuple[dict, dict]]:
        """
        Helper for testing or manual `/goal checkin <pct>` invocation.
        """
        with self.lock:
            goal = self.get_goal(goal_id_or_title)
            if not goal:
                active = self.get_active_goals()
                goal = active[0] if active else None
            if not goal:
                return None

            for cp in goal.get("checkpoints", []):
                if cp.get("pct") == pct:
                    cp["status"] = "pending"
                    cp["snoozed_until"] = 0
                    cp["due_epoch"] = int(time.time() - 5)
                    self.save_goals()
                    return goal, cp
        return None

    # -------------------------------------------------------------------------
    # PROMPTS FOR CALYPSO (CALENDAR CREATION, 25/50/75 REVERIE, 100% FINALE)
    # -------------------------------------------------------------------------
    def build_calendar_goal_discussion_prompt(self, goal: dict) -> str:
        title = goal.get("title", "Personal Goal")
        target_date = goal.get("target_date", "")
        criteria = goal.get("criteria", "")
        criteria_line = f"Target / Details: \"{criteria}\"\n" if criteria else ""

        return (
            f"[System Notice: Your companion just added a new Personal Goal directly into the Calendar: "
            f"\"{title}\" with a target deadline of {target_date}.\n"
            f"{criteria_line}"
            f"Check-ins have been automatically scheduled at 25%, 50%, 75%, and 100% of the time to goal.\n"
            f"Initiate a lively, supportive, and focused conversation about this new goal! "
            f"Ask what inspired them to set it right now, help them define what success looks like for the first 25% leg, "
            f"and let them know you'll be holding them accountable like a true partner.]"
        )

    def build_reverie_checkin_payload(self, goal: dict, cp: dict, ai_name: str = "Calypso") -> dict:
        pct = cp.get("pct", 25)
        title = goal.get("title", "Personal Goal")
        target_date = goal.get("target_date", "")
        criteria = goal.get("criteria", "")
        criteria_str = f" (Target/Criteria: {criteria})" if criteria else ""

        logs = goal.get("progress_log", [])
        if logs:
            recent_logs = "; ".join(f"[{l.get('checkpoint_pct')}%] {l.get('note')}" for l in logs[-3:])
            history_str = f"Prior check-in notes: {recent_logs}\n"
        else:
            history_str = "Prior check-in notes: None logged yet.\n"

        if pct == 25:
            stage_flavor = (
                "We are 25% of the way through the timeline. Check if they have broken inertia and started building momentum, "
                "or if they are procrastinating on step one."
            )
        elif pct == 50:
            stage_flavor = (
                "We are at the 50% halfway mark! Ask for a concrete progress check (quantitative or qualitative). "
                "If they are on track, fire them up; if they are lagging behind, give affectionate but firm partner pushback to get them refocused."
            )
        else:  # 75%
            stage_flavor = (
                "We are at 75%—the final stretch before the deadline! Push them to lock in, clear any remaining excuses, "
                "and finish strong before the 100% mark."
            )

        note_text = (
            f"🎯 [{pct}% Goal Check-in — '{title}'] "
            f"{ai_name} glances at the calendar, wanting to check on your progress and keep you locked in..."
        )

        reverie_prompt = (
            f"[System Event: {pct}% Goal Reverie Check-in for \"{title}\"{criteria_str} (Deadline: {target_date}).\n"
            f"{history_str}"
            f"Directive: {stage_flavor}\n"
            f"Act as a devoted, invested partner who genuinely cares about seeing your companion succeed. "
            f"Combine a direct inquiry about their current progress with warm, motivating accountability.]"
        )

        return {
            "note_text": note_text,
            "reverie_prompt": reverie_prompt,
            "goal_id": goal.get("id"),
            "pct": pct
        }

    def build_finale_checkin_prompt(self, goal: dict) -> str:
        title = goal.get("title", "Personal Goal")
        target_date = goal.get("target_date", "")
        criteria = goal.get("criteria", "")
        criteria_str = f" ({criteria})" if criteria else ""
        logs = goal.get("progress_log", [])
        recent_logs = "; ".join(f"[{l.get('checkpoint_pct')}%] {l.get('note')}" for l in logs[-4:]) if logs else "No prior notes logged."

        return (
            f"[System Event: 100% Final Goal Check-in! The target deadline ({target_date}) for your companion's goal "
            f"\"{title}\"{criteria_str} has officially arrived, and the Final Goal Review card is now on screen.\n"
            f"Journey notes so far: {recent_logs}\n"
            f"Initiate the final check-in conversation! Ask them directly where things stand at the finish line—whether they "
            f"achieved it (so you can celebrate together with pride) or if they came up just short and need to extend or regroup.]"
        )

    def get_active_goals_prompt_block(self) -> str:
        active = self.get_active_goals()
        if not active:
            return ""

        lines = ["### ACTIVE PERSONAL GOALS (PARTNER ACCOUNTABILITY RADAR):"]
        for g in active:
            pct = self.calculate_time_progress_pct(g)
            crit = f" — Target: {g.get('criteria')}" if g.get("criteria") else ""
            logs = g.get("progress_log", [])
            last_note = f" | Latest update: \"{logs[-1].get('note')}\"" if logs else ""
            lines.append(
                f"- [{g.get('id')}] \"{g.get('title')}\"{crit} (Deadline: {g.get('target_date')}, ~{pct}% time elapsed{last_note})"
            )
        return "\n".join(lines)

    def format_goals_summary(self) -> str:
        with self.lock:
            if not self.goals:
                return (
                    "🎯 [Personal Goals]: No goals currently tracked.\n"
                    "  • Add one in the Calendar (📅), talk to Calypso about a goal, or use:\n"
                    "    /goal add YYYY-MM-DD | Goal Title | Details\n"
                    "    /goal checkin 25  (or 50, 75, 100 to test check-ins)"
                )

            out = ["🎯 [Personal Goals & Accountability Tracker]"]
            for g in self.goals:
                status = g.get("status", "active").upper()
                pct = self.calculate_time_progress_pct(g) if status == "ACTIVE" else 100
                crit = f" ({g.get('criteria')})" if g.get("criteria") else ""
                cp_states = " | ".join(
                    f"{c['pct']}%:{'✓' if c['status'] == 'completed' else ('⏳' if c['status'] == 'surfaced' else '•')}"
                    for c in g.get("checkpoints", [])
                )
                out.append(
                    f"  • [{g.get('id')}] ({status}) {g.get('title')}{crit} — Due {g.get('target_date')} [{pct}% elapsed] ({cp_states})"
                )
                logs = g.get("progress_log", [])
                if logs:
                    out.append(f"      Latest note: \"{logs[-1].get('note')}\"")

            out.append(
                "  (Commands: /goal add YYYY-MM-DD | Title | Details  •  /goal progress <id> | <note>  •  "
                "/goal checkin 25|50|75|100  •  /goal done <id>  •  /goal del <id>)"
            )
            return "\n".join(out)
