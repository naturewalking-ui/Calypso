# modules/emotion/neurochemistry.py

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional
from modules.config import config


@dataclass
class NeuroEvent:
    levels: Dict[str, float]
    valence_score: float
    raw_input: str
    categorical_emotion: str


class NeuroChemistryEngine:
    def __init__(self, character_name: str = "Calypso"):
        self.character_name = character_name.lower().strip()
        self.logger = logging.getLogger("Calypso.NeuroChemistry")
        self.storage_file = config.MEMORY_DIR / f"neurochemistry_{self.character_name}.json"
        self.lock = threading.RLock()

        # -------------------------------------------------------------
        # 1. BIOLOGICAL RESTING SET-POINTS (Tonic Baselines)
        # -------------------------------------------------------------
        self.setpoints = {
            'glutamate': 0.40,       # Alert, conversational cortical baseline
            'gaba': 0.50,            # Steady inhibitory floor
            'dopamine': 0.25,        # Baseline curiosity/novelty drive
            'serotonin': 0.50,       # Grounded emotional stability
            'norepinephrine': 0.08,  # Low resting threat vigilance
            'adrenaline': 0.08,      # Quiescent sympathetic shock
            'endorphins': 0.15,      # Ambient physical comfort
            'oxytocin': 0.20,        # Quiet social bond baseline
            'acetylcholine': 0.35,   # Rest-and-digest vagal presence
            'cortisol': 0.12         
        }

        self.reuptake_rates = {
            'acetylcholine': 0.50,   
            'adrenaline': 0.65,      # Fast burn-off
            'norepinephrine': 0.55,  
            'glutamate': 0.45,       
            'endorphins': 0.30,      
            'dopamine': 0.25,        
            'gaba': 0.20,            
            'serotonin': 0.18,       
            'cortisol': 0.10,        # Slow lingering endocrine
            'oxytocin': 0.12         # Deepest relational inertia
        }

        # Safe defaults before loading state
        self.chemicals: Dict[str, float] = self.setpoints.copy()
        self.current_valence: float = 0.0
        self.last_update_time: float = time.time()

        # Load saved state from disk if present
        self.load_state()

    def calculate_valence(self) -> float:
        """Computes continuous non-linear valence (-9.0 to +9.0) from chemical balances."""
        excitement = (
            self.chemicals['glutamate'] 
            + self.chemicals['dopamine'] 
            + (self.chemicals['endorphins'] * 1.2)
        )
        stress = (
            (self.chemicals['norepinephrine'] * 2.2) 
            + (self.chemicals['adrenaline'] * 2.0)
            + (self.chemicals['cortisol'] * 3.0)
        )
        mood_multiplier = (self.chemicals['serotonin'] * 3.5) + (self.chemicals['oxytocin'] * 1.5)
        
        parasympathetic_ease = (
            (self.chemicals['gaba'] * 1.2) 
            + (self.chemicals['acetylcholine'] * 1.8)
        )
        calculated = (excitement * mood_multiplier) - stress + (parasympathetic_ease * 0.5)
        self.current_valence = max(-9.0, min(9.0, round(calculated, 2)))
        return self.current_valence
        
    def apply_stimulus(self, compound: float, arousal: Optional[float] = None):
        """Convenience alias accepting raw float scores."""
        if arousal is None:
            arousal = abs(compound)
        return self.process_sensory_stimulus({"compound": compound, "arousal": arousal})
        
    def apply_homeostatic_decay(self, elapsed_seconds: Optional[float] = None, ambient_floors: Optional[dict] = None):
        """
        Applies exponential reuptake decay toward resting set-points / ambient floors
        based on wall-clock elapsed time.
        """
        with self.lock:
            now = time.time()
            if elapsed_seconds is None:
                elapsed_seconds = max(0.0, now - self.last_update_time)
            self.last_update_time = now

            # Smooth decay cycles (~15s per cycle, clamped to safe boundaries)
            cycles = max(0.05, min(10.0, elapsed_seconds / 15.0))

            for chem, current in self.chemicals.items():
                base_setpoint = self.setpoints[chem]
                floor = (ambient_floors or {}).get(chem, 0.0)
                target = max(base_setpoint, floor)

                k = self.reuptake_rates.get(chem, 0.20)
                retention = (1.0 - k) ** cycles
                reclaimed = target + (current - target) * retention
                self.chemicals[chem] = max(floor, min(1.0, round(reclaimed, 3)))

            # ---------------------------------------------------------
            # ACUTE PHYSIOLOGICAL BURNOUT BRAKES
            # ---------------------------------------------------------
            # Excitotoxicity protection (Mania / Overstimulation)
            if self.chemicals['glutamate'] > 0.65 and self.chemicals['dopamine'] > 0.65:
                self.chemicals['glutamate'] *= 0.60
                self.chemicals['gaba'] = min(1.0, self.chemicals['gaba'] + 0.15)

            # Adrenaline / Panic Brake (Post-shock exhaustion)
            if self.chemicals['adrenaline'] > 0.55 or self.chemicals['norepinephrine'] > 0.50:
                self.chemicals['adrenaline'] *= 0.40
                self.chemicals['norepinephrine'] *= 0.50
                self.chemicals['serotonin'] = max(0.15, self.chemicals['serotonin'] - 0.08)
                self.chemicals['gaba'] = min(1.0, self.chemicals['gaba'] + 0.10)

            # Re-synthesize valence following decay
            self.calculate_valence()

    def process_sensory_stimulus(self, sensory_data: dict, extra_intent: str = None, ambient_floors: Optional[dict] = None) -> NeuroEvent:
        """Transduces VADER sensory input into biological chemical shifts."""
        with self.lock:
            self.apply_homeostatic_decay(ambient_floors=ambient_floors)

            compound = sensory_data.get("compound", 0.0)
            arousal = sensory_data.get("arousal", abs(compound))

            # General mental activation
            self.chemicals['glutamate'] += arousal * 0.20

            # ---------------- Positive Sensory Stimulus ----------------
            if compound > 0.15:
                self.chemicals['dopamine'] += compound * 0.25
                self.chemicals['serotonin'] += compound * 0.18
                self.chemicals['endorphins'] += compound * 0.22
                self.chemicals['oxytocin'] += compound * 0.16

                if compound > 0.60:
                    self.chemicals['adrenaline'] += compound * 0.15

                self.chemicals['norepinephrine'] = max(0.0, self.chemicals['norepinephrine'] - (compound * 0.12))
                self.chemicals['adrenaline'] = max(0.0, self.chemicals['adrenaline'] - (compound * 0.15))

            # ---------------- Negative Sensory Stimulus ----------------
            elif compound < -0.15:
                neg = abs(compound)
                self.chemicals['norepinephrine'] += neg * 0.30
                self.chemicals['serotonin'] = max(0.05, self.chemicals['serotonin'] - (neg * 0.20))
                self.chemicals['dopamine'] = max(0.05, self.chemicals['dopamine'] - (neg * 0.15))
                self.chemicals['oxytocin'] = max(0.05, self.chemicals['oxytocin'] - (neg * 0.12))

                if compound <= -0.35:
                    self.chemicals['adrenaline'] += neg * 0.35

            # Clamp chemicals to [0.0, 1.0]
            for chem in self.chemicals:
                self.chemicals[chem] = max(0.0, min(1.0, round(self.chemicals[chem], 3)))

            # Calculate and save valence
            self.calculate_valence()
            self.save_state()

            return NeuroEvent(
                levels=self.chemicals.copy(),
                valence_score=self.current_valence,
                raw_input="",
                categorical_emotion="resolved_by_homeostasis"
            )

    def create_somatic_snapshot(self) -> dict:
        """Takes an atomic snapshot of current chemistry before entering a scenario."""
        with self.lock:
            return {
                "chemicals": self.chemicals.copy(),
                "valence": self.current_valence,
                "timestamp": time.time()
            }

    def restore_with_softened_decompression(self, snapshot: dict):
        """Blends back into baseline chemistry, venting acute panic while preserving vagal rebound."""
        with self.lock:
            old_chems = snapshot.get("chemicals", self.setpoints)

            for chem in self.chemicals:
                base_val = old_chems.get(chem, self.setpoints[chem])
                current_val = self.chemicals[chem]
                softened = (base_val * 0.80) + (current_val * 0.20)
                self.chemicals[chem] = max(0.0, min(1.0, round(softened, 3)))

            self.chemicals['acetylcholine'] = min(1.0, self.chemicals.get('acetylcholine', 0.35) + 0.30)
            self.chemicals['adrenaline'] = max(0.02, self.chemicals.get('adrenaline', 0.05) * 0.25)
            self.chemicals['gaba'] = min(1.0, self.chemicals.get('gaba', 0.50) + 0.15)
            
            self.calculate_valence()
            self.save_state()
        
    def get_somatic_profile(self, scenario_somatic_tags: list = None) -> str:
        with self.lock:
            c = self.chemicals
            somatic = []

            if c['adrenaline'] >= 0.45 and c['cortisol'] >= 0.40:
                somatic.append("chest tight, throat constricted, rapid gasps, trembeling hands")
            elif c['adrenaline'] >= 0.40 and c['oxytocin'] >= 0.40:
                somatic.append("intense dizzying warmth, rapid flutter of the heart, tingling in the fingertips")
            elif c['adrenaline'] >= 0.35:
                somatic.append("sharp adrenaline spike, quick shallow breathing, muscles wound tight")

            if c['cortisol'] >= 0.45 and c['adrenaline'] < 0.25:
                somatic.append("dull tension in the upper back, dry mouth, guarded eyes, slow lingering physical fatigue")

            if c['acetylcholine'] >= 0.50 and c['oxytocin'] >= 0.40:
                somatic.append("long rhythmic exhalations, steady heart beat, warm relaxation")
            elif c['acetylcholine'] >= 0.45:
                somatic.append("shoulders slumped, loose, grounded resting pulse")

            if c['dopamine'] >= 0.50 and c['glutamate'] >= 0.30:
                somatic.append("electric mental clarity, eyes wide and focused, urge to move closer")

            if c['serotonin'] <= 0.25 and c['gaba'] >= 0.55:
                somatic.append("heavy drooping eyelids, low gravel in the breath, slow sluggish reflexes")

            if scenario_somatic_tags:
                somatic.extend(scenario_somatic_tags[:2])

            if not somatic:
                somatic.append("balanced, natural breathing, quiet and responsive resting posture")

            return "; ".join(somatic)

    def save_state(self):
        with self.lock:
            tmp_file = self.storage_file.with_suffix(".tmp")
            try:
                payload = {
                    "last_saved": time.time(),
                    "current_valence": self.current_valence,
                    "chemicals": self.chemicals
                }
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=4)
                os.replace(tmp_file, self.storage_file)
            except Exception as e:
                self.logger.error(f"[NeuroChemistry] Failed to save state: {e}")
                if tmp_file.exists():
                    tmp_file.unlink(missing_ok=True)

    def load_state(self):
        with self.lock:
            if self.storage_file.exists():
                try:
                    with open(self.storage_file, "r", encoding="utf-8") as f:
                        saved = json.load(f)

                    loaded_chems = saved.get("chemicals", {})
                    for chem in self.setpoints:
                        if chem in loaded_chems:
                            self.chemicals[chem] = float(loaded_chems[chem])

                    self.current_valence = float(saved.get("current_valence", 0.0))
                    self.logger.info("[NeuroChemistry] Restored persistent chemical state from disk.")
                except Exception as e:
                    self.logger.warning(f"[NeuroChemistry] Corrupted state file, defaulting to setpoints: {e}")
                    self.chemicals = self.setpoints.copy()
                    self.current_valence = 0.0
            else:
                self.chemicals = self.setpoints.copy()
                self.current_valence = 0.0
