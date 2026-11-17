# modules/emotion/esteem.py

import json
import re
from pathlib import Path
from modules.config import config


class EsteemEngine:
    def __init__(self, character_name: str = "Calypso", window_size: int = 25):
        self.character_name = character_name.lower().strip()
        self.storage_file = config.MEMORY_DIR / f"esteem_{self.character_name}.json"
        self.window_size = window_size

        self.EXPECTED_MEAN = 2.0
        # SD reduced to 0.38 so a sustained average of 2.6 hits T = 65+
        self.STANDARD_DEVIATION = 0.38

        self.CATEGORY_WEIGHTS = {
            "validation": 3.0,
            "constructive": 2.2,
            "neutral": 2.0,
            "dismissive": 1.0,
            "hostile": 0.0
        }

        self.data = {
            "rolling_history": [2.0] * 5,
            "meta_scores": {
                "total_scanned_responses": 5,
                "cumulative_raw_points": 10.0,
                "manual_offset": 0.0,
                "current_t_score": 50.0
            }
        }
        self.load_state()

    def evaluate_user_stimulus(self, user_text: str, vader_compound: float) -> str:
        text_lower = user_text.lower()
        grief_triggers = [
            "died", "passed away", "funeral", "cancer", "grief", "mourning",
            "loss", "hurts", "crying", "suffering", "heartbroken", "accident"
        ]
        is_grieving = any(g in text_lower for g in grief_triggers)

        direct_hostile_triggers = [
            "shut up", "useless", "stupid", "hate you", "you suck", 
            "idiot", "wrong again", "get lost", "f*** you", "screw you"
        ]
        targeted_pronouns = ["you", "your", "you're", "ur"]
        has_targeted_pronoun = any(re.search(rf"\b{p}\b", text_lower) for p in targeted_pronouns)

        if any(h in text_lower for h in direct_hostile_triggers):
            return "hostile"

        if vader_compound <= -0.6 and has_targeted_pronoun and not is_grieving:
            return "hostile"

        direct_dismissive_triggers = ["whatever", "nevermind", "don't care", "boring", "be quiet"]
        if any(d in text_lower for d in direct_dismissive_triggers):
            return "dismissive"

        praise_triggers = ["thank you", "love you", "great job", "amazing", "smart", "helpful", "proud of you", "brilliant"]
        if any(p in text_lower for p in praise_triggers) or vader_compound >= 0.5:
            return "validation"

        if vader_compound >= 0.1:
            return "constructive"

        return "neutral"

    def process_turn(self, user_text: str, vader_compound: float = 0.0) -> float:
        category = self.evaluate_user_stimulus(user_text, vader_compound)
        weight = self.CATEGORY_WEIGHTS.get(category, 2.0)

        self.data["rolling_history"].append(weight)
        if len(self.data["rolling_history"]) > self.window_size:
            self.data["rolling_history"].pop(0)

        self.data["meta_scores"]["total_scanned_responses"] += 1
        self.data["meta_scores"]["cumulative_raw_points"] += weight

        current_avg = sum(self.data["rolling_history"]) / len(self.data["rolling_history"])
        z_score = (current_avg - self.EXPECTED_MEAN) / self.STANDARD_DEVIATION
        
        offset = self.data["meta_scores"].get("manual_offset", 0.0) * 0.90
        self.data["meta_scores"]["manual_offset"] = round(offset, 2)

        calculated_t = 50.0 + (z_score * 10.0) + offset
        final_t_score = max(20.0, min(80.0, round(calculated_t, 2)))
        self.data["meta_scores"]["current_t_score"] = final_t_score

        self.save_state()
        return final_t_score

    @property
    def current_t_score(self) -> float:
        return self.data["meta_scores"]["current_t_score"]

    @current_t_score.setter
    def current_t_score(self, value: float):
        current = self.data["meta_scores"]["current_t_score"]
        delta = float(value) - current
        self.data["meta_scores"]["manual_offset"] = self.data["meta_scores"].get("manual_offset", 0.0) + delta
        clamped_val = max(20.0, min(80.0, round(float(value), 2)))
        self.data["meta_scores"]["current_t_score"] = clamped_val
        self.save_state()

    def get_affinity_biases(self) -> dict:
        t = self.current_t_score
        biases = {}

        if t >= 65.0:
            biases["Harmony"] = +0.05
            biases["Curiosity"] = +0.04
            biases["Autonomy"] = +0.05
            biases["Wonder"] = +0.04
            biases["Comedy"] = +0.03
        elif t >= 55.0:
            biases["Harmony"] = +0.025
            biases["Curiosity"] = +0.025
            biases["Autonomy"] = +0.025
        elif t <= 35.0:
            biases["Fatigue"] = +0.04
            biases["Abyss"] = +0.05
            biases["Annoyance"] = +0.04
            biases["Autonomy"] = -0.05
        elif t <= 45.0:
            biases["Conformity"] = +0.03
            biases["Tragedy"] = +0.03
            biases["Harmony"] = -0.03

        return biases

    def save_state(self):
        try:
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            print(f"[ESTEEM ERROR] Could not save state: {e}")

    def load_state(self):
        if self.storage_file.exists():
            try:
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception as e:
                print(f"[ESTEEM WARNING] State corrupted: {e}")
