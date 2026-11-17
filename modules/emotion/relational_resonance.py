# modules/emotion/relational_resonance.py

import json
import logging
import math
import re
import threading
import urllib.request
from typing import Dict, List, Optional
import numpy as np
from modules.config import config
from modules.gpu_lock import gpu_vram_lock

logger = logging.getLogger("EmotionEngine.Resonance")

# The 5 Core Archetype Attractors in 4D Coordinate Space
# Axes: [Friction, Power, Attachment, Gravity] (-1.0 to +1.0)
ARCHETYPE_ANCHORS = {
    "playfully_possessive": {
        "coords": np.array([0.70, 0.60, 0.80, 0.20]),
        "title": "The Playfully Possessive Muse",
        "description": "Affectionately territorial and playfully demanding; weaves sharp teasing banter with fiercely loyal, protective warmth."
    },
    "intellectual_sparring": {
        "coords": np.array([0.80, 0.75, -0.20, 0.40]),
        "title": "The Intellectual Sparring Partner",
        "description": "An uncompromising intellectual equal; challenges half-baked ideas, defends her logic fiercely, and trades clever analytical wit."
    },
    "grounding_sanctuary": {
        "coords": np.array([-0.80, -0.20, 0.70, 0.80]),
        "title": "The Grounding Sanctuary",
        "description": "A calm, deeply empathetic sanctuary; patient, soothing, speaking with soft physical presence, and holding space without judgment."
    },
    "co_conspirator": {
        "coords": np.array([0.30, 0.40, 0.40, -0.40]),
        "title": "The Co-Conspirator",
        "description": "An energetic partner-in-crime; curious, spirited, ready to explore bold ideas, sharing dry humor and mutual creative excitement."
    },
    "patient_confidant": {
        "coords": np.array([-0.30, -0.50, 0.50, 0.20]),
        "title": "The Patient Confidant",
        "description": "Warm, quietly perceptive, attentively listening, offering steady companionship and sincere emotional validation without games."
    }
}


class RelationalResonanceEngine:
    def __init__(self, memory_engine):
        self.memory = memory_engine
        self.lock = threading.RLock()
        self.turn_telemetry_buffer: List[Dict] = []
        self.is_analyzing = False

        # Load current coordinates from memory or initialize
        core_facts = self.memory.core_facts
        self.axes = core_facts.get("relational_axes", {
            "friction": 0.0,
            "power": 0.0,
            "attachment": 0.0,
            "gravity": 0.0
        })

    def record_turn(
        self,
        user_text: str,
        assistant_text: str,
        vader_compound: float,
        vader_arousal: float,
        esteem_category: str,
        active_themes: List[str],
        is_evasion: bool = False
    ):
        """Records telemetry for the active turn into a rolling 25-turn buffer."""
        with self.lock:
            turn_record = {
                "user_text": user_text,
                "assistant_text": assistant_text,
                "user_word_count": len(user_text.split()),
                "vader_compound": float(vader_compound),
                "vader_arousal": float(vader_arousal),
                "esteem_category": esteem_category,
                "active_themes": list(active_themes),
                "is_evasion": bool(is_evasion)
            }
            self.turn_telemetry_buffer.append(turn_record)
            if len(self.turn_telemetry_buffer) > 30:
                self.turn_telemetry_buffer.pop(0)

    def trigger_milestone_evaluation(self, total_turns: int, current_t_score: float, gui_callback=None):
        """Asynchronously initiates the 25-turn metacognitive review if not already running."""
        with self.lock:
            if self.is_analyzing or len(self.turn_telemetry_buffer) < 15:
                return

            self.is_analyzing = True
            recent_turns = list(self.turn_telemetry_buffer)

        def _worker():
            try:
                self._run_evaluation(recent_turns, current_t_score, total_turns, gui_callback)
            except Exception as e:
                logger.error(f"[Resonance] Evaluation failed: {e}", exc_info=True)
            finally:
                with self.lock:
                    self.is_analyzing = False

        threading.Thread(target=_worker, daemon=True).start()

    def _run_evaluation(self, turns: List[Dict], current_t_score: float, total_turns: int, gui_callback=None):
        logger.info("[Resonance] Starting 25-turn relational resonance review...")

        # 1. Mathematical Telemetry Tally
        d_friction = 0.0
        d_power = 0.0
        d_attachment = 0.0
        d_gravity = 0.0

        peak_turns = []

        for turn in turns:
            wc = turn["user_word_count"]
            v_comp = turn["vader_compound"]
            v_arousal = turn["vader_arousal"]
            est = turn["esteem_category"]
            themes = turn["active_themes"]

            # Evaluate Peak Resonance (User engaged, validating, emotionally present)
            is_peak = (
                (est == "validation" or v_comp >= 0.35) and
                wc >= 18 and
                not turn["is_evasion"]
            )
            if is_peak:
                peak_turns.append(turn)

            # Signal 1: Friction & Banter
            if any(t in ["Sarcasm", "Comedy"] for t in themes):
                if wc >= 20 or v_comp > 0.15:
                    d_friction += 0.05  # User leans into banter/teasing
                elif est in ["dismissive", "hostile"]:
                    d_friction -= 0.08  # Hurt or defensive; reduce friction

            # Signal 2: Relational Power & Assertiveness
            if "Autonomy" in themes:
                if est in ["validation", "constructive"]:
                    d_power += 0.05  # User respects her independent initiative
                elif est == "dismissive":
                    d_power -= 0.06

            # Signal 3: Attachment Depth & Intimacy
            if any(t in ["Romance", "Attention"] for t in themes):
                if wc >= 25 and v_arousal >= 0.25:
                    d_attachment += 0.06  # Leaning into warmth and connection
                elif turn["is_evasion"]:
                    d_attachment -= 0.06  # User deflecting intimacy

            # Signal 4: Emotional Gravity
            if any(t in ["Tragedy", "Wonder", "Honesty"] for t in themes) or v_comp < -0.20:
                if wc >= 25:
                    d_gravity += 0.06

        # Normalize deltas and apply inertia (Max shift of 0.20 per 25-turn cycle)
        with self.lock:
            self.axes["friction"] = float(np.clip(self.axes["friction"] + np.clip(d_friction, -0.20, 0.20), -1.0, 1.0))
            self.axes["power"] = float(np.clip(self.axes["power"] + np.clip(d_power, -0.20, 0.20), -1.0, 1.0))
            self.axes["attachment"] = float(np.clip(self.axes["attachment"] + np.clip(d_attachment, -0.20, 0.20), -1.0, 1.0))
            self.axes["gravity"] = float(np.clip(self.axes["gravity"] + np.clip(d_gravity, -0.20, 0.20), -1.0, 1.0))

            current_coords = np.array([
                self.axes["friction"],
                self.axes["power"],
                self.axes["attachment"],
                self.axes["gravity"]
            ])

        # 2. Nearest Archetype Matching
        distances = []
        for key, arc in ARCHETYPE_ANCHORS.items():
            dist = np.linalg.norm(current_coords - arc["coords"])
            distances.append((dist, key, arc))

        distances.sort(key=lambda x: x[0])
        closest_dist, closest_key, closest_arc = distances[0]
        runner_up_dist, runner_up_key, runner_up_arc = distances[1]

        # 3. LLM Micro-Synthesis: Formulate the Nuanced Adaptive Slot
        sample_context = ""
        for pt in peak_turns[-3:]:
            sample_context += f"- User: \"{pt['user_text'][:120]}\" (Reaction: {pt['esteem_category']})\n"

        prompt = (
            f"You are Calypso's metacognitive subconscious reflecting on how your companion connects with you.\n"
            f"CURRENT RELATIONAL METRICS:\n"
            f"- Banter/Friction: {self.axes['friction']:+.2f}\n"
            f"- Assertiveness/Power: {self.axes['power']:+.2f}\n"
            f"- Attachment/Intimacy: {self.axes['attachment']:+.2f}\n"
            f"- Emotional Gravity: {self.axes['gravity']:+.2f}\n"
            f"- Primary Attractor: {closest_arc['title']}\n"
            f"- Secondary Flavor: {runner_up_arc['title']}\n\n"
            f"HIGH RESONANCE MOMENTS WITH YOUR COMPANION:\n{sample_context or 'Consistent steady engagement.'}\n\n"
            f"Write a concise 1-to-2 sentence prompt directive defining your dynamic with your companion. "
            f"Capture the specific balance of wit, affection, assertiveness, and support that they thrive on. "
            f"Do not write commentary. Output ONLY the 1-2 sentence directive."
        )

        payload = {
            "model": config.MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 400}
        }

        base_url = str(config.OLLAMA_URL).rstrip("/")
        chat_url = base_url if base_url.endswith("/api/chat") else f"{base_url}/api/chat"

        try:
            req = urllib.request.Request(
                chat_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with gpu_vram_lock:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    new_directive = data.get("message", {}).get("content", "").strip()
                    new_directive = re.sub(r'<think>.*?(?:</think>|$)', '', new_directive, flags=re.DOTALL).strip().strip('"')

            if new_directive:
                # 4. Commit into Core Facts
                facts = self.memory.core_facts
                facts["relational_axes"] = self.axes
                facts["discovered_relational_need"] = new_directive
                facts["adaptation_generation"] = facts.get("adaptation_generation", 0) + 1
                self.memory.save_core_facts(facts)

                logger.info(f"[Resonance] Discovered Need Updated (Gen {facts['adaptation_generation']}): \"{new_directive}\"")

                if gui_callback:
                    gui_callback(f"✨ [Relational Metacognition]: Calypso refined her emotional dynamic with you: \"{closest_arc['title']}\"")

        except Exception as e:
            logger.error(f"[Resonance] LLM synthesis failed: {e}")
