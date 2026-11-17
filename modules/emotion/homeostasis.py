# modules/emotion/homeostasis.py

class HomeostaticGravityEngine:
    def __init__(self):
        # Calmed decay rates so states endure across turns
        self.affinity_decay_rates = {
            "Tragedy": 0.06,
            "Humor": 0.10,
            "Deception": 0.12,
            "Honesty": 0.05,
            "Wonder": 0.06,
            "Abyss": 0.14,
            "Autonomy": 0.05,
            "Conformity": 0.10,
            "Annoyance": 0.18,
            "Harmony": 0.06,
            "Sarcasm": 0.14,
            "Nostalgia": 0.07,
            "Curiosity": 0.10,
            "Attention": 0.10,
            "Romance": 0.12,
            "Sadness_Inversion": 0.06,
            "Fatigue": 0.07         
        }

        # --- Homeostatic Resting Disposition ---
        self.resting_warmth_setpoint = 1.60   # Center of the "warm" attractor basin
        self.positive_compression_k = 5.0     # Resistance curve against runaway excitement
        self.negative_damping = 0.70          # Buoyancy buffer against casual sadness

    def compute_esteem_valence_bias(self, current_t_score: float) -> float:
        z_deviation = (current_t_score - 50.0) / 10.0
        return round(z_deviation * 0.65, 2)

    def apply_affinity_decay(self, affinity_engine):
        """Called ONCE per turn transition (never on read/idle)."""
        with affinity_engine.lock:
            for theme_name, theme_data in affinity_engine.themes.items():
                current_intensity = theme_data.get("intensity", 0.0)
                if current_intensity > 0.0:
                    decay_pct = self.affinity_decay_rates.get(theme_name, 0.08)
                    new_intensity = current_intensity * (1.0 - decay_pct)
                    if new_intensity < 0.02:
                        new_intensity = 0.0
                    theme_data["intensity"] = round(new_intensity, 3)
            affinity_engine.save_state()

    def resolve_felt_state(self, neuro_engine, esteem_engine, affinity_engine) -> dict:
        """
        Pure evaluation function: applies homeostatic gravity toward 'warm'
        and dampens extreme spikes (sigmoidal/hyperbolic compression).
        """
        t_score = esteem_engine.current_t_score
        esteem_bias = self.compute_esteem_valence_bias(t_score)

        base_valence = neuro_engine.current_valence
        raw_valence = base_valence + esteem_bias

        # --- Homeostatic Gravity Equation ---
        if raw_valence >= 0.0:
            # As excitement climbs, apply progressive diminishing returns (max boost of +5.5)
            # Formula: 5.5 * (raw / (raw + k))
            compressed_boost = 5.5 * (raw_valence / (raw_valence + self.positive_compression_k))
            effective_valence = round(self.resting_warmth_setpoint + compressed_boost, 2)
        else:
            # Emotional buoyancy: baseline warmth buffers against casual negative dips
            effective_valence = round(self.resting_warmth_setpoint + (raw_valence * self.negative_damping), 2)

        # Clamping to valid range
        effective_valence = max(-9.0, min(9.0, effective_valence))

        # --- Re-balanced Tier Thresholds ---
        v = effective_valence
        if v <= -5.5:
            base_tier = "furious"   # Extreme violation / acute crisis
        elif v < -2.5:
            base_tier = "sad"       # Rare: deep grief, heartbreak, genuine sorrow
        elif v < -0.5:
            base_tier = "somber"    # Thoughtful melancholy, quiet concern
        elif v < 0.8:
            base_tier = "neutral"   # Detached, clinical, or strictly technical
        elif v <= 4.2:
            base_tier = "warm"      # <--- WIDE BASIN: Primary resting home base
        elif v <= 6.8:
            base_tier = "happy"     # Vibrant joy, laughter, celebration
        else:
            base_tier = "excited"   # Rare: high-arousal peak euphoria / breakthrough

        final_tier = affinity_engine.evaluate_persona_override(
            current_tier=base_tier,
            mood_score=effective_valence
        )

        return {
            "raw_valence": base_valence,
            "esteem_bias": esteem_bias,
            "effective_valence": effective_valence,
            "t_score": t_score,
            "base_tier": base_tier,
            "final_tier": final_tier,
            "chemicals": neuro_engine.chemicals.copy()
        }
