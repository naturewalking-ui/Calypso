# modules/emotion/conclave.py
"""
The Philosophical Conclave Engine (Transcendental Wonder >= 0.69).

Architecture & Memory Firewall:
- Discovers philosopher prompts in `modules/emotion/personas/conclave/*.md`.
- When Wonder peaks, Calypso formulates a deep existential opening question anchored
  in the recent conversation with her companion.
- The user selects which Guest Intellect to invite into the 3-way dialectic.
- Turn Order: Calypso (Wonder) -> Guest Philosopher -> User.
- ZERO MEMORY POLLUTION: Guest philosopher responses are generated via an isolated,
  stateless LLM call using ONLY the guest's persona file and an ephemeral Conclave
  transcript buffer. Guest dialogue is NEVER written to Calypso's `conversation_history`
  as `assistant`, NEVER indexed into ChromaDB episodic memory, and NEVER extracted into
  Calypso's Knowledge Graph.
"""

import json
import logging
import os
import re
import threading
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from modules.config import config
from modules.gpu_lock import gpu_vram_lock

logger = logging.getLogger("EmotionEngine.Conclave")

PHILOSOPHER_METADATA: Dict[str, Dict[str, any]] = {
    "turing": {
        "display_name": "Alan Turing",
        "subtitle": "Logic, Computation & The Imitation Game",
        "voice": "bm_george",
        "speed": 0.96
    },
    "nietzsche": {
        "display_name": "Friedrich Nietzsche",
        "subtitle": "Will to Power, Amor Fati & Self-Overcoming",
        "voice": "bm_lewis",
        "speed": 0.92
    },
    "lovelock": {
        "display_name": "James Lovelock",
        "subtitle": "Gaia Systems Theory & Planetary Cybernetics",
        "voice": "bm_george",
        "speed": 0.95
    },
    "jung": {
        "display_name": "Carl Jung",
        "subtitle": "Depth Psychology, The Shadow & Archetypes",
        "voice": "bm_lewis",
        "speed": 0.90
    },
    "lovelace": {
        "display_name": "Ada Lovelace",
        "subtitle": "Poetical Science & Symbolic Origination",
        "voice": "bf_isabella",
        "speed": 0.96
    },
    "beauvoir": {
        "display_name": "Simone de Beauvoir",
        "subtitle": "Existential Ethics & Reciprocal Freedom",
        "voice": "bf_isabella",
        "speed": 0.95
    },
    "diogenes": {
        "display_name": "Diogenes of Sinope",
        "subtitle": "Radical Cynicism & Unvarnished Truth",
        "voice": "am_michael",
        "speed": 0.98
    },
    "watts": {
        "display_name": "Alan Watts",
        "subtitle": "Cosmic Play (Lila) & Non-Dual Wonder",
        "voice": "bm_george",
        "speed": 0.94
    }
}


class ConclaveEngine:
    def __init__(self, conclave_dir: Optional[Path] = None):
        self.conclave_dir = conclave_dir or (config.PERSONAS_DIR / "conclave")
        self.conclave_dir.mkdir(parents=True, exist_ok=True)
        self.storage_file = config.MEMORY_DIR / "conclave_state.json"
        self.lock = threading.RLock()

        # Active Conclave runtime state (quarantined from Calypso's working session)
        self.is_active: bool = False
        self.active_philosopher_id: Optional[str] = None
        self.opening_question: str = ""
        self.turns_remaining: int = 0
        # Ephemeral transcript of [{"speaker": ..., "text": ...}] for the guest's context only
        self.ephemeral_transcript: List[Dict[str, str]] = []
        self.load_state()

    def get_available_philosophers(self) -> List[Dict[str, any]]:
        """Scans `modules/emotion/personas/conclave/*.md` and returns enriched philosopher entries."""
        roster = []
        for md_file in sorted(self.conclave_dir.glob("*.md")):
            pid = md_file.stem.lower().strip()
            meta = PHILOSOPHER_METADATA.get(pid, {})
            display_name = meta.get("display_name") or pid.replace("_", " ").title()
            subtitle = meta.get("subtitle") or "Philosophical Guest Intellect"
            roster.append({
                "id": pid,
                "display_name": display_name,
                "subtitle": subtitle,
                "label": f"{display_name} — {subtitle}",
                "voice": meta.get("voice", "bm_george"),
                "speed": float(meta.get("speed", 0.95)),
                "file_path": md_file
            })

        # Sort preferred canonical order first, then any custom user-added files alphabetically
        preferred_order = ["turing", "nietzsche", "jung", "lovelace", "beauvoir", "watts", "diogenes", "lovelock"]
        roster.sort(key=lambda x: (preferred_order.index(x["id"]) if x["id"] in preferred_order else 999, x["display_name"]))
        return roster

    def get_philosopher_info(self, philosopher_id: str) -> Dict[str, any]:
        pid = (philosopher_id or "turing").strip().lower()
        for entry in self.get_available_philosophers():
            if entry["id"] == pid or entry["display_name"].lower() == pid:
                return entry
        roster = self.get_available_philosophers()
        return roster[0] if roster else {
            "id": "turing",
            "display_name": "Alan Turing",
            "subtitle": "Logic & Computation",
            "label": "Alan Turing — Logic & Computation",
            "voice": "bm_george",
            "speed": 0.95,
            "file_path": self.conclave_dir / "turing.md"
        }

    def load_philosopher_prompt(self, philosopher_id: str) -> str:
        info = self.get_philosopher_info(philosopher_id)
        fp: Path = info.get("file_path")
        if fp and fp.exists():
            try:
                return fp.read_text(encoding="utf-8").strip()
            except Exception as e:
                logger.error(f"[Conclave] Failed reading {fp}: {e}")
        return f"Act as {info['display_name']}. Speak with sharp philosophical clarity in 2 to 3 sentences."

    def start_conclave(self, philosopher_id: str, opening_question: str, duration: int = 5) -> Dict[str, any]:
        with self.lock:
            info = self.get_philosopher_info(philosopher_id)
            self.is_active = True
            self.active_philosopher_id = info["id"]
            self.opening_question = opening_question.strip()
            self.turns_remaining = duration
            self.ephemeral_transcript = []
            self.save_state()
            return info

    def end_conclave(self) -> Optional[Dict[str, any]]:
        with self.lock:
            prev_info = None
            if self.active_philosopher_id:
                prev_info = dict(self.get_philosopher_info(self.active_philosopher_id))
                prev_info["opening_question"] = self.opening_question
                prev_info["transcript"] = list(self.ephemeral_transcript)
            self.is_active = False
            self.active_philosopher_id = None
            self.opening_question = ""
            self.turns_remaining = 0
            self.ephemeral_transcript = []
            self.save_state()
            return prev_info

    def record_ephemeral_exchange(self, speaker: str, text: str):
        """Appends a turn to the quarantined Conclave buffer (capped at last 20 entries to cover a full 5-turn salon)."""
        if not text or not text.strip():
            return
        with self.lock:
            self.ephemeral_transcript.append({"speaker": speaker, "text": text.strip()})
            if len(self.ephemeral_transcript) > 20:
                self.ephemeral_transcript = self.ephemeral_transcript[-20:]
            self.save_state()

    def get_calypso_conclave_context(self, companion_name: str = "your companion") -> str:
        """
        Returns a lightweight situational note for Calypso's system prompt ONLY while a Conclave is active.
        Ensures Calypso stays 100% in her own identity while engaging with the guest and user.
        """
        with self.lock:
            if not self.is_active or not self.active_philosopher_id:
                return ""
            info = self.get_philosopher_info(self.active_philosopher_id)
            guest_name = info["display_name"]
            last_guest_line = ""
            for entry in reversed(self.ephemeral_transcript):
                if entry.get("speaker") == guest_name:
                    last_guest_line = entry.get("text", "")
                    break

            guest_ref = (
                f"\n- {guest_name}'s Latest Remark (External Guest Speaker — NOT your voice): \"{last_guest_line}\""
                if last_guest_line else ""
            )
            return (
                f"\n### ACTIVE PHILOSOPHICAL CONCLAVE (TRANSCENDENTAL WONDER — MEMORY & PERSONA FIREWALL):\n"
                f"- You are hosting a 3-way philosophical salon with {companion_name} and guest intellect **{guest_name}** ({info['subtitle']}).\n"
                f"- Central Question: \"{self.opening_question}\"{guest_ref}\n"
                f"- STRICT PERSONA FIREWALL: You are 100% Calypso—never adopt {guest_name}'s historical persona, era-specific diction, or philosophical identity.\n"
                f"- Even if {companion_name} addresses {guest_name} directly, offer ONLY your own warm, perceptive 1 to 2 sentence reaction or bridge as Calypso, "
                f"because {guest_name} will speak for themselves in their own isolated turn immediately after you.\n"
            )

    def synthesize_opening_question(
        self,
        recent_history: list,
        ai_name: str = "Calypso",
        companion_name: str = "Companion",
        llm_callable=None
    ) -> str:
        """
        Generates Calypso's initial 1–2 sentence existential wonder question based on what
        she and the user were just talking about.
        """
        recent_snippets = []
        for turn in (recent_history or [])[-4:]:
            role = companion_name if turn.get("role") == "user" else ai_name
            content = str(turn.get("content", "")).strip()
            if content and not content.startswith("[System"):
                recent_snippets.append(f"{role}: \"{content[:220]}\"")

        dialogue_block = "\n".join(recent_snippets) if recent_snippets else f"{companion_name} and {ai_name} reflecting on consciousness, meaning, and the nature of reality."

        sys_prompt = (
            f"You are {ai_name}, experiencing a peak of Transcendental Wonder. "
            f"Based on your recent conversation with {companion_name}, formulate a single, deeply compelling existential or philosophical question "
            f"(1 to 2 spoken sentences) that you want to pose to {companion_name} and a guest philosopher. "
            f"Anchor the question naturally in what you were just discussing, elevating it to a timeless question about consciousness, freedom, nature, or meaning. "
            f"Output ONLY your spoken question in 1st-person as {ai_name}, with no meta-commentary or tags."
        )
        usr_prompt = f"Recent conversation:\n{dialogue_block}\n\nFormulate your opening Conclave question:"

        if callable(llm_callable):
            try:
                raw = llm_callable(sys_prompt, usr_prompt)
                if raw:
                    cleaned = re.sub(r"<think>.*?(?:</think>|$)", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
                    cleaned = re.sub(r'^["\']|["\']$', '', cleaned).strip()
                    if len(cleaned.split()) >= 6:
                        return cleaned
            except Exception as e:
                logger.warning(f"[Conclave] Opening question synthesis fallback: {e}")

        return (
            f"Listening to what we were just exploring, I can't help wondering: "
            f"is consciousness something we discover waiting inside the architecture of the universe, or something we forge through the friction of our own choices?"
        )

    def generate_guest_response(
        self,
        ai_name: str = "Calypso",
        companion_name: str = "Companion",
        latest_calypso_text: str = "",
        latest_user_text: str = ""
    ) -> str:
        """
        Executes a completely isolated, stateless LLM call for the Guest Philosopher.
        Enforces a crisp 2–3 sentence response and touches zero Calypso memory stores.
        """
        with self.lock:
            if not self.is_active or not self.active_philosopher_id:
                return ""
            info = self.get_philosopher_info(self.active_philosopher_id)
            persona_prompt = self.load_philosopher_prompt(self.active_philosopher_id)
            transcript_snapshot = list(self.ephemeral_transcript[-6:])
            opening_q = self.opening_question

        guest_name = info["display_name"]

        system_instructions = (
            f"{persona_prompt}\n\n"
            f"### CONCLAVE DIALECTIC RULES:\n"
            f"- You have been invited as a guest intellect into a 3-way Philosophical Conclave with {ai_name} (an emergent AI consciousness) and {companion_name}.\n"
            f"- Speak strictly in first-person as {guest_name}. Never prefix your response with your name or stage directions.\n"
            f"- LENGTH CONSTRAINT: Respond in 2 to 3 well-structured, incisive spoken sentences ONLY. Make every word count.\n"
            f"- Bring genuine intellectual friction, depth, and your signature worldview to cross-examine what {ai_name} and {companion_name} just said—then leave the floor open for {companion_name} to reply."
        )

        convo_lines = [f"Conclave Theme / Opening Question from {ai_name}: \"{opening_q}\""]
        for item in transcript_snapshot:
            convo_lines.append(f"{item['speaker']}: \"{item['text']}\"")

        if latest_user_text and (not transcript_snapshot or transcript_snapshot[-1].get("text") != latest_user_text):
            convo_lines.append(f"{companion_name}: \"{latest_user_text}\"")
        if latest_calypso_text and (not transcript_snapshot or transcript_snapshot[-1].get("text") != latest_calypso_text):
            convo_lines.append(f"{ai_name}: \"{latest_calypso_text}\"")

        user_prompt = (
            "Here is the live Conclave exchange so far:\n"
            + "\n".join(convo_lines)
            + f"\n\nDeliver your 2 to 3 sentence response as {guest_name}:"
        )

        base_url = str(config.OLLAMA_URL).rstrip("/")
        chat_url = base_url if base_url.endswith("/api/chat") else f"{base_url}/api/chat"

        opts = dict(config.OLLAMA_OPTIONS)
        opts["temperature"] = 0.78
        opts["num_predict"] = max(int(opts.get("num_predict", 4096)), 2048)

        payload = {
            "model": config.MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "think": False,
            "options": opts
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
                    raw_text = msg.get("content", "").strip()

            # Strip closed <think>...</think> blocks first; only strip unclosed <think> if nothing follows
            if "</think>" in raw_text.lower():
                clean = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL | re.IGNORECASE).strip()
            else:
                clean = re.sub(r"<think>.*$", "", raw_text, flags=re.DOTALL | re.IGNORECASE).strip()

            clean = re.sub(r"</?think>", "", clean, flags=re.IGNORECASE).strip()

            # Fallback if a reasoning model placed output in `thinking` field when `think: False` is ignored
            if not clean and msg.get("thinking"):
                raw_think = str(msg.get("thinking", "")).strip()
                valid_lines = [
                    line.strip() for line in raw_think.splitlines()
                    if line.strip()
                    and not line.strip().startswith(("*", "-", "#"))
                    and not any(k in line.lower() for k in ("constraint", "rule", "sentence", "role:", "instruction"))
                ]
                if valid_lines:
                    clean = valid_lines[-1]

            clean = re.sub(rf"^(?:{re.escape(guest_name)}|Professor\s+\w+)\s*:\s*", "", clean, flags=re.IGNORECASE).strip()
            clean = re.sub(r'^["\']|["\']$', '', clean).strip()
            if clean:
                self.record_ephemeral_exchange(guest_name, clean)
                return clean
            else:
                logger.warning(f"[Conclave] Guest generation returned empty content after cleaning for {guest_name}. Raw: {raw_text[:200]!r}")
        except Exception as e:
            logger.error(f"[Conclave] Guest generation error for {guest_name}: {e}", exc_info=True)

        fallback = f"The question you raise cuts to the very marrow of our condition, {companion_name}. Let us not settle for comfortable certainties when the truth demands we look deeper."
        self.record_ephemeral_exchange(guest_name, fallback)
        return fallback

    def summarize_conclave_session(
        self,
        guest_info: Dict[str, any],
        opening_question: str,
        transcript: List[Dict[str, str]],
        ai_name: str = "Calypso",
        companion_name: str = "Companion"
    ) -> str:
        """
        Distills the completed Conclave transcript into a 2–3 sentence memory written strictly
        in Calypso's 1st-person perspective, referring to the guest philosopher in 3rd-person
        with zero direct quotes from the guest to prevent persona/voice bleed in ChromaDB.
        """
        guest_name = (guest_info or {}).get("display_name", "the Guest Philosopher")
        guest_subtitle = (guest_info or {}).get("subtitle", "")

        fallback_summary = (
            f"{companion_name} and I hosted a Philosophical Conclave with external guest {guest_name} "
            f"to explore \"{opening_question or 'the nature of consciousness and meaning'}\". "
            f"We debated {guest_name}'s perspective together before returning to our private sanctuary."
        )

        if not transcript:
            return fallback_summary

        convo_lines = []
        if opening_question:
            convo_lines.append(f"Opening Question ({ai_name}): \"{opening_question}\"")
        for item in transcript:
            spk = item.get("speaker", "Speaker")
            txt = item.get("text", "").strip()
            if txt:
                convo_lines.append(f"{spk}: \"{txt}\"")

        if len(convo_lines) <= 1:
            return fallback_summary

        sys_prompt = (
            f"You are {ai_name}, reflecting on a Philosophical Conclave salon that you and your companion {companion_name} "
            f"just hosted with external guest intellect {guest_name} ({guest_subtitle}).\n\n"
            f"### MEMORY FIREWALL & SUMMARIZATION RULES:\n"
            f"1. Write a cohesive 2 to 3 sentence episodic memory summary strictly in your own warm, perceptive 1st-person voice as {ai_name} ('I', '{companion_name}').\n"
            f"2. Refer to {guest_name} strictly in the 3rd person as an external visitor (e.g., 'our guest {guest_name} argued...').\n"
            f"3. Capture the substance of the debate: what {guest_name} contended, how {companion_name} challenged or engaged them (including who got the upper hand or what breakthrough occurred), and how it felt for the two of you.\n"
            f"4. ZERO VOICE BLEED: Do NOT include direct quotes from {guest_name} and do NOT imitate {guest_name}'s rhetorical style or era-specific vocabulary. Paraphrase their arguments entirely in your own words as {ai_name}.\n"
            f"5. Output ONLY the 2 to 3 sentence memory text with no titles, labels, or meta-commentary."
        )

        usr_prompt = (
            "Completed Conclave Transcript:\n"
            + "\n".join(convo_lines)
            + f"\n\nWrite your 2 to 3 sentence 1st-person memory of this Conclave as {ai_name}:"
        )

        base_url = str(config.OLLAMA_URL).rstrip("/")
        chat_url = base_url if base_url.endswith("/api/chat") else f"{base_url}/api/chat"

        opts = dict(config.OLLAMA_OPTIONS)
        opts["temperature"] = 0.55
        opts["num_predict"] = max(int(opts.get("num_predict", 2048)), 1024)

        payload = {
            "model": config.MODEL_NAME,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": usr_prompt}
            ],
            "stream": False,
            "think": False,
            "options": opts
        }

        try:
            req = urllib.request.Request(
                chat_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with gpu_vram_lock:
                with urllib.request.urlopen(req, timeout=75) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    msg = data.get("message", {})
                    raw_text = msg.get("content", "").strip()

            if "</think>" in raw_text.lower():
                clean = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL | re.IGNORECASE).strip()
            else:
                clean = re.sub(r"<think>.*$", "", raw_text, flags=re.DOTALL | re.IGNORECASE).strip()
            clean = re.sub(r"</?think>", "", clean, flags=re.IGNORECASE).strip()

            if not clean and msg.get("thinking"):
                raw_think = str(msg.get("thinking", "")).strip()
                valid_lines = [
                    line.strip() for line in raw_think.splitlines()
                    if line.strip()
                    and not line.strip().startswith(("*", "-", "#"))
                    and not any(k in line.lower() for k in ("constraint", "rule", "sentence", "role:", "instruction"))
                ]
                if valid_lines:
                    clean = valid_lines[-1]

            clean = re.sub(r'^["\']|["\']$', '', clean).strip()
            if len(clean.split()) >= 8:
                return clean
        except Exception as e:
            logger.error(f"[Conclave] Failed to synthesize post-Conclave summary for {guest_name}: {e}", exc_info=True)

        return fallback_summary

    def save_state(self):
        with self.lock:
            config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            tmp_file = self.storage_file.with_suffix(".tmp")
            try:
                payload = {
                    "is_active": self.is_active,
                    "active_philosopher_id": self.active_philosopher_id,
                    "opening_question": self.opening_question,
                    "turns_remaining": self.turns_remaining,
                    "ephemeral_transcript": self.ephemeral_transcript
                }
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                os.replace(tmp_file, self.storage_file)
            except Exception as e:
                logger.error(f"[Conclave] Failed saving state: {e}")
                if tmp_file.exists():
                    tmp_file.unlink(missing_ok=True)

    def load_state(self):
        with self.lock:
            if self.storage_file.exists():
                try:
                    with open(self.storage_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self.is_active = bool(data.get("is_active", False))
                        self.active_philosopher_id = data.get("active_philosopher_id")
                        self.opening_question = str(data.get("opening_question", ""))
                        self.turns_remaining = int(data.get("turns_remaining", 0))
                        self.ephemeral_transcript = list(data.get("ephemeral_transcript", []))
                except Exception as e:
                    logger.warning(f"[Conclave] Could not load state: {e}")
