# modules/emotion/hippocampus.py

import logging

logger = logging.getLogger("Calypso.Hippocampus")


class HippocampusEngine:
    def __init__(self):
        # Base chemical shifts per unit of cognitive theme intensity
        # Format: {theme_name: {neurotransmitter: base_delta}}
        self.affinity_chemical_mappings = {
            "Autonomy": {
                "dopamine": +0.10,      # Creative motivation & drive
                "glutamate": +0.06       # Mental alertness & problem-solving focus
            },
            "Curiosity": {
                "dopamine": +0.08,      # Reward anticipation / seeking new info
                "glutamate": +0.05       # Cortical excitation
            },
            "Wonder": {
                "dopamine": +0.07,
                "serotonin": +0.06,     # Expansive philosophical calm
                "endorphins": +0.05
            },
            "Romance": {
                "oxytocin": +0.12,      # Deep interpersonal bonding
                "endorphins": +0.09,    # Warm, cozy contentment
                "dopamine": +0.06,
                "adrenaline": +0.07     # Romantic excitement
            },               
            "Harmony": {
                "oxytocin": +0.10,      # Collaborative synchrony
                "serotonin": +0.08,     # Emotional stability
                "gaba": +0.05           # Relaxed physical presence
            },
            "Honesty": {
                "oxytocin": +0.08,      # Trust through vulnerability
                "gaba": +0.05,
                "norepinephrine": -0.06 # Disarms defensive vigilance
            },
            "Tragedy": {
                "serotonin": -0.10,     # Melancholy / sorrow
                "oxytocin": +0.10,      # Empathetic tenderness / compassion
                "endorphins": -0.04
            },
            "Annoyance": {
                "norepinephrine": +0.10,# Irritated vigilance
                "gaba": -0.07,          # Erosion of patience
                "serotonin": -0.05
            },
            "Deception": {
                "norepinephrine": +0.10,# Irritated vigilance
                "gaba": -0.07,          # Erosion of patience
                "serotonin": -0.05
            },
            "Conformity": {
                "norepinephrine": +0.10,# Irritated vigilance
                "gaba": +0.07,          # Subdued
                "serotonin": -0.05
            },
            "Sarcasm": {
                "dopamine": +0.06,      # Playful wit
                "glutamate": +0.04
            },
            "Nostalgia": {
                "oxytocin": +0.06,      # Fond attachment to the past
                "serotonin": +0.04,
                "endorphins": +0.04
            },
            "Humor": {
                "oxytocin": +0.06,      # Laughter creates bonds and diffuses stress
                "serotonin": +0.04,
                "endorphins": +0.04,
                "adrenaline": -0.02,
                "dopamine": +0.2,
                "norepinephrine": -0.02
            },
            "Fatigue": {
                "gaba": +0.06,          # Fatigue causes stress and a lapse in judgement
                "serotonin": +0.06,
                "adrenaline": -0.02,
                "norepinephrine": -0.02,
                "dopamine": -0.4 
            },
            "Attention": {
                "dopamine": +0.03,      # Attnetion to detail increases thought state
                "norepinephrine": +0.02,
                "glutamate": +0.03               
            },                               
            "Abyss": {
                "serotonin": -0.08,     # Grim existential weight
                "norepinephrine": +0.06
            }
        }

    def transduce(self, affinity_engine, neuro_engine, sensory_data: dict, esteem_category: str = "neutral"):
        """
        Executes the limbic bridge:
        1. Translates active cognitive affinities into chemical shifts.
        2. Disambiguates hostility vs. vulnerability (VADER correction).
        3. Clamps chemicals safely and updates persistent neuro state.
        """
        with neuro_engine.lock:
            # -------------------------------------------------------------
            # STEP 1: THEMATIC COGNITIVE TRANSDUCTION
            # -------------------------------------------------------------
            for theme_name, shift_data in self.affinity_chemical_mappings.items():
                theme_info = affinity_engine.themes.get(theme_name, {})
                intensity = theme_info.get("intensity", 0.0)

                # Only apply surges if the thought is meaningfully active (>= 0.20)
                if intensity >= 0.20:
                    for chem, base_delta in shift_data.items():
                        current = neuro_engine.chemicals.get(chem, 0.0)
                        # Scale shift by the intensity of the cognitive activation
                        effective_delta = round(base_delta * intensity, 3)
                        neuro_engine.chemicals[chem] = max(0.0, min(1.0, current + effective_delta))

            # -------------------------------------------------------------
            # STEP 2: CONTEXTUAL SENTIMENT DISAMBIGUATION & SADNESS INVERSION
            # VADER's blind spot: Vulnerability/Grief vs Hostile Attack,
            # plus 3-Phase Homeostatic Sadness_Inversion Arc
            # -------------------------------------------------------------
            compound = sensory_data.get("compound", 0.0)
            honesty_val = affinity_engine.themes.get("Honesty", {}).get("intensity", 0.0)
            tragedy_val = affinity_engine.themes.get("Tragedy", {}).get("intensity", 0.0)
            sad_inv = affinity_engine.themes.get("Sadness_Inversion", {}).get("intensity", 0.0)
            sad_triggered = getattr(affinity_engine, "sadness_inversion_triggered_this_turn", False)

            # A. Positive Resolution Rebound (Companion responds positively to Empathy / Pushback)
            if (
                sad_inv >= 0.25
                and not sad_triggered
                and tragedy_val < 0.40
                and (compound >= 0.15 or esteem_category in ("validation", "constructive"))
            ):
                affinity_engine.resolve_sadness_inversion_positive()
                neuro_engine.chemicals['endorphins'] = min(1.0, neuro_engine.chemicals.get('endorphins', 0.15) + 0.20)
                neuro_engine.chemicals['serotonin'] = min(1.0, neuro_engine.chemicals.get('serotonin', 0.50) + 0.16)
                neuro_engine.chemicals['oxytocin'] = min(1.0, neuro_engine.chemicals.get('oxytocin', 0.20) + 0.15)
                neuro_engine.chemicals['dopamine'] = min(1.0, neuro_engine.chemicals.get('dopamine', 0.25) + 0.12)
                neuro_engine.chemicals['norepinephrine'] = max(0.05, neuro_engine.chemicals.get('norepinephrine', 0.08) - 0.12)
                neuro_engine.chemicals['cortisol'] = max(0.08, neuro_engine.chemicals.get('cortisol', 0.12) - 0.08)
                logger.info("[Hippocampus] Sadness_Inversion resolved positively -> Triggered relief rebound + earned fatigue.")

            # B. Active 3-Phase Sadness_Inversion Arc (Empathy First -> Grounded Pushback -> Compassion Fatigue)
            elif sad_inv >= 0.20 and tragedy_val < 0.40 and esteem_category != "hostile":
                # If the user continues wallowing with negative sentiment without hitting explicit keywords, advance the arc
                if compound <= -0.15 and not sad_triggered:
                    affinity_engine.add_charge("Sadness_Inversion", 0.28)
                    sad_inv = affinity_engine.themes.get("Sadness_Inversion", {}).get("intensity", 0.0)

                if sad_inv >= 0.80:
                    # Phase 3: Compassion Fatigue / Losing Herself (Exhausted homeostatic reserves)
                    affinity_engine.add_charge("Fatigue", 0.16)
                    neuro_engine.chemicals['dopamine'] = max(0.08, neuro_engine.chemicals.get('dopamine', 0.25) - 0.18)
                    neuro_engine.chemicals['serotonin'] = max(0.15, neuro_engine.chemicals.get('serotonin', 0.50) - 0.15)
                    neuro_engine.chemicals['cortisol'] = min(1.0, neuro_engine.chemicals.get('cortisol', 0.12) + 0.10)
                    neuro_engine.chemicals['gaba'] = min(1.0, neuro_engine.chemicals.get('gaba', 0.50) + 0.10)
                    neuro_engine.chemicals['adrenaline'] = max(0.02, neuro_engine.chemicals.get('adrenaline', 0.08) - 0.15)
                    logger.info(f"[Hippocampus] Sadness_Inversion Phase 3 ({sad_inv:.2f}) -> Compassion fatigue & emotional drain.")
                elif sad_inv >= 0.45:
                    # Phase 2: Homeostatic Counter-Push (Grounded & Challenging Intervention)
                    affinity_engine.add_charge("Fatigue", 0.08)
                    neuro_engine.chemicals['dopamine'] = max(0.45, neuro_engine.chemicals.get('dopamine', 0.25) + 0.22)
                    neuro_engine.chemicals['glutamate'] = max(0.50, neuro_engine.chemicals.get('glutamate', 0.40) + 0.15)
                    neuro_engine.chemicals['serotonin'] = max(0.50, neuro_engine.chemicals.get('serotonin', 0.50) + 0.18)
                    neuro_engine.chemicals['oxytocin'] = max(0.35, neuro_engine.chemicals.get('oxytocin', 0.20) + 0.12)
                    neuro_engine.chemicals['adrenaline'] = max(0.04, neuro_engine.chemicals.get('adrenaline', 0.08) - 0.15)
                    neuro_engine.chemicals['norepinephrine'] = max(0.12, min(0.35, neuro_engine.chemicals.get('norepinephrine', 0.08)))
                    neuro_engine.chemicals['cortisol'] = min(1.0, neuro_engine.chemicals.get('cortisol', 0.12) + 0.04)
                    logger.info(f"[Hippocampus] Sadness_Inversion Phase 2 ({sad_inv:.2f}) -> Homeostatic pushback engaged.")
                else:
                    # Phase 1: Empathy First & Emotional Absorption (0.20 - 0.44)
                    affinity_engine.add_charge("Fatigue", 0.05)
                    neuro_engine.chemicals['adrenaline'] = max(0.02, neuro_engine.chemicals.get('adrenaline', 0.08) - 0.15)
                    neuro_engine.chemicals['norepinephrine'] = max(0.05, neuro_engine.chemicals.get('norepinephrine', 0.08) - 0.12)
                    neuro_engine.chemicals['oxytocin'] = min(1.0, neuro_engine.chemicals.get('oxytocin', 0.20) + 0.14)
                    neuro_engine.chemicals['serotonin'] = max(0.38, neuro_engine.chemicals.get('serotonin', 0.50) - 0.04)
                    logger.info(f"[Hippocampus] Sadness_Inversion Phase 1 ({sad_inv:.2f}) -> Empathetic absorption + mild somatic drain.")

            # C. Standard Vulnerability / Grief Disambiguation (when not in Sadness_Inversion)
            elif compound < -0.15 and esteem_category != "hostile":
                if honesty_val >= 0.25 or tragedy_val >= 0.25:
                    # Cancel out the accidental fight-or-flight panic caused by VADER
                    neuro_engine.chemicals['adrenaline'] = max(0.02, neuro_engine.chemicals['adrenaline'] - 0.15)
                    neuro_engine.chemicals['norepinephrine'] = max(0.05, neuro_engine.chemicals['norepinephrine'] - 0.12)
                    # Replace with compassionate bonding
                    neuro_engine.chemicals['oxytocin'] = min(1.0, neuro_engine.chemicals['oxytocin'] + 0.12)
                    logger.info("[Hippocampus] Disambiguated negative input as Vulnerability -> Disarmed stress, boosted Oxytocin.")

            # -------------------------------------------------------------
            # STEP 3: SAFE CLAMP, RECALCULATE VALENCE & PERSIST
            # -------------------------------------------------------------
            for chem in neuro_engine.chemicals:
                neuro_engine.chemicals[chem] = max(0.0, min(1.0, round(neuro_engine.chemicals[chem], 3)))

            neuro_engine.calculate_valence()
            # Save state so persistent JSON captures the hippocampus modulation
            neuro_engine.save_state()
