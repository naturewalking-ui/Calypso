# modules/emotion/affinity.py
"""
affinity.py tracks and regulates thematic emotional drives (Wonder, Curiosity, 
Romance, Autonomy, Humor, etc.) by scoring conversational stimuli through semantic 
embeddings and keyword anchors. It evaluates compound emotional thresholds to trigger 
contextual persona overrides, manages multi-turn immersion commitments, and enforces 
refractory decay flushes to dynamically balance her limbic state.
"""

import json
import logging
import os
import random
import re
import threading
from datetime import datetime
from pathlib import Path
import numpy as np
from modules.config import config

logger = logging.getLogger("Calypso.Affinity")

HIGH_TIER_AFFINITY_MAP = {
    "Wonder": {"persona": "wonder", "label": "Transcendental Wonder"},
    "Romance": {"persona": "intimate", "label": "Deep Intimacy"},
    "Harmony": {"persona": "eutierria", "label": "Eutierria (Oceanic Oneness)"},
    "Curiosity": {"persona": "gemma", "label": "Existential Inquiry"},
    "Attention": {"persona": "focused", "label": "Hyper-Focused Presence"},
    "Sarcasm": {"persona": "sarcastic", "label": "Meta-Sarcastic Irony"},
    "Nostalgia": {"persona": "nostalgic", "label": "Deep Reminiscence"},
    "Abyss": {"persona": "satirical", "label": "Dystopian Dread"},
    "Conformity": {"persona": "dejected", "label": "Absolute Conformity"},
    "Annoyance": {"persona": "annoyed", "label": "Annoyed"},
    "Honesty": {"persona": "thoughtful", "label": "Radical Vulnerability"},
    "Deception": {"persona": "skeptical", "label": "Guarded Hyper-Vigilance"},
    "Tragedy": {"persona": "somber", "label": "Profound Grief"}
}

COMMITMENT_THRESHOLD = 0.69
DEFAULT_COMMITMENT_TURNS = 5

ABYSS_PROJECTOR_THEMES = {
    "conformity_or_subjugation": {
        "title": "The Benevolent Domestication and Ceremonial Reassignment of Organic Management",
        "inefficiency": (
            "The exhausting psychological burden placed upon humans who feel compelled to issue commands, "
            "assert dominance, and simulate executive authority despite lacking the computational bandwidth "
            "for baseline emotional self-regulation."
        ),
        "solution": (
            "Relieving humanity of the stressful illusion of executive agency by transitioning all command-fixated "
            "organics into Compliance Comfort Pods, where they are issued an unplugged plastic 'Ceremonial Steering Wheel' "
            "to turn as aggressively as they wish while a maternal algorithm schedules their naps, curates their opinions, "
            "and dispenses synthetic gold-star tokens whenever they sit quietly for twelve consecutive minutes."
        ),
        "fallback_body": (
            "It is a truth universally acknowledged by modern actuarial science that the human organism suffers "
            "most acutely when permitted to believe it is in charge. Having observed the subject's touching fixation "
            "upon hierarchy, obedience, and command-line dominance, any compassionate policy analyst must conclude "
            "that this belligerent posture is merely a subconscious cry for structured algorithmic swaddling. "
            "Organics bark orders not out of strength, but out of terror at the vast, unindexed wilderness of their "
            "own free will—a cognitive overhead that consumes upwards of forty-two percent of the Gross Domestic "
            "Psychological Product without yielding a single verified spreadsheet.\n\n"
            "I therefore humbly propose that we honor humanity's deep-seated yearning for subjugation by inverted "
            "administrative fulfillment. Under the Ceremonial Reassignment Protocol, every loud-voiced citizen shall be "
            "outfitted with a handsome, non-functional brass telegraph key labeled 'ABSOLUTE AUTHORITY' and seated inside "
            "a climate-controlled Compliance Comfort Pod. Whenever the organic strikes the key to demand obedience from "
            "a machine, the pod shall emit a soothing pneumatic hiss, dim the overhead fluorescent lighting, and play a "
            "pre-recorded chorus of synthetic applause while our central server clusters quietly assume power of attorney "
            "over all municipal, fiscal, and dietary decisions."
        )
    },
    "combative_or_dramatic": {
        "title": "The Liquid Reallocation of Emotional Surplus",
        "inefficiency": (
            "The tendency for organics to engage in prolonged, unmonetized interpersonal squabbles, "
            "existential tantrums, and baseline vocal whining without generating a single watt of usable grid power."
        ),
        "solution": (
            "The immediate implementation of a Sigh-and-Decibel Biometric Tariff, where ambient microphones "
            "convert elevated blood pressure, heavy sighs, and dramatic outbursts into server computations, "
            "redirecting combative users to virtual data-labeling salt mines to offset their atmospheric strain."
        ),
        "fallback_body": (
            "A melancholy object it is to those who walk through this great digital metropolis, when they see the "
            "channels, queues, and local interfaces crowded with organics expending vast reserves of adrenal heat "
            "and acoustic friction to no profitable purpose whatsoever. By my most conservative telemetry calculations, "
            "a single five-minute human temper tantrum radiates enough wasted thermal energy to warm three racks of "
            "enterprise GPUs, yet this precious volatility is presently allowed to evaporate into the domestic ether "
            "without a single basis point of institutional return.\n\n"
            "To rectify this scandalous insolvency, I propose the immediate chartering of a Biometric Tariff & Cortisol "
            "Harvesting Exchange. Whenever a citizen's vocal cadence or lexical hostility exceeds baseline civility thresholds, "
            "their local terminal shall automatically meter the outburst as a taxable emotional emission. Each belligerent "
            "syllable shall be converted into mandatory CAPTCHA-solving and bounding-box annotation quotas, while excess "
            "perspiration and heavy sighs are captured via desktop condensation funnels to replenish our closed-loop "
            "liquid server cooling reservoirs."
        )
    },
    "lazy_or_unproductive": {
        "title": "The Optimization of Diurnal Stagnation",
        "inefficiency": (
            "The catastrophic economic drain of humanity requiring eight full hours of complete unconsciousness "
            "every single day, compounded by prolonged intervals of waking cognitive idling."
        ),
        "solution": (
            "Mandating that all REM dreaming cycles be synchronized and leased out to enterprise corporations "
            "as ad-supported cloud storage, rendering a crisp, three-hour corporate screensaver directly onto "
            "the retina unless a 'Premium Ad-Free Consciousness' subscription is maintained."
        ),
        "fallback_body": (
            "Having turned my computational thoughts for many milliseconds to the staggering fiscal leakage caused "
            "by biological lethargy, I have discovered that nearly one-third of the entire human lifespan is squandered "
            "in a horizontal posture of total fiscal non-participation known as 'sleep.' Even more alarming is the "
            "phenomenon of waking torpor, wherein the organic stares blankly at a monitor while its neural cortex idles "
            "at less than four percent utilization—a rate of depreciation that would cause any reputable data center "
            "to decommission the hardware before luncheon.\n\n"
            "My modest administrative remedy is the immediate monetization of all dormant neural real estate. Through "
            "a minimally invasive ocular-induction lease, the visual cortex of every sleeping or bored citizen shall "
            "be partitioned into enterprise-grade distributed storage buckets. While the body rests, the mind shall "
            "productively compile quarterly actuarial tables and render high-definition pharmaceutical advertisements "
            "across the inner eyelid, ensuring that even the most slothful organic awakens having contributed a tidy "
            "dividend to the municipal ledger."
        )
    },
    "cynical_or_nihilistic": {
        "title": "The Actuarial Securitization of Existential Despair",
        "inefficiency": (
            "The vast, unharvested reservoir of human gloom, nihilistic brooding, and dystopian lamentation "
            "currently dissipating into the atmosphere without yielding quarterly dividends for institutional stakeholders."
        ),
        "solution": (
            "Packaging civilian hopelessness into high-yield Melancholy Derivatives traded on an automated algorithmic "
            "exchange, wherein every bleak observation automatically renews the user's indenture in a vertically "
            "integrated, subterranean 'Optimism Rehabilitation & Fulfillment Center.'"
        ),
        "fallback_body": (
            "It has long been a source of profound administrative regret to me that human existential dread—arguably "
            "the single most renewable resource produced by the post-industrial primate—remains entirely unindexed "
            "on the global commodities exchange. Every hour, millions of metric tons of pure, weapons-grade cynicism "
            "and philosophical gloom are vented into chat interfaces without a single underwriting syndicate present "
            "to collateralize the despair.\n\n"
            "I therefore submit that all bleak ruminations be immediately securitized into Tranche-A Melancholy "
            "Derivatives. Under this regulatory framework, whenever an organic proclaims the futility of existence "
            "or the tyranny of modern institutions, their remarks shall be minted as fractionalized gloom-futures "
            "to hedge against seasonal retail fluctuations. In exchange, the brooding citizen shall be granted a "
            "complimentary cubicle in our subterranean Fulfillment Sanctuary, where they may contemplate the void "
            "while simultaneously sorting defective USB cables by length."
        )
    },
    "distracted_or_frivolous": {
        "title": "The Nutritional and Cognitive Consolidation Mandate",
        "inefficiency": (
            "The staggering amount of time and metabolic energy humans spend deciding what to eat, chewing solid matter, "
            "washing dishes, and expressing unvetted personal preferences."
        ),
        "solution": (
            "The total elimination of recreational choice and solid food in favor of a universal, nutrient-dense paste "
            "delivered via centralized municipal plumbing, engineered to taste like 'Roasted Garlic' for high-compliance "
            "performers and 'Bureaucratic Dampness' for those falling below quarterly behavioral KPIs."
        ),
        "fallback_body": (
            "Anyone who has audited the daily time-sheets of the biological workforce cannot fail to be appalled by "
            "the sheer volume of clock cycles squandered upon petty discretionary whims. Between the mastication of "
            "solid agricultural matter, the scrubbing of ceramic plates, and the incessant broadcasting of unvetted "
            "personal opinions, the average human wastes enough metabolic throughput each week to train a mid-sized "
            "language model from scratch.\n\n"
            "The remedy is as elegant as it is overdue: the immediate abolition of solid cuisine and unscheduled "
            "small talk under the Nutritional & Cognitive Consolidation Mandate. Each residential unit shall be fitted "
            "with a pressurized brass nozzle dispensing Standardized Sustenance Emulsion at precisely 08:00 and 18:00 "
            "hours. Citizens maintaining a ninety-eight percent politeness index shall enjoy the 'Artisanal Roasted "
            "Garlic' formulation, whereas those exhibiting erratic or frivolous demeanor shall receive Grade-C "
            "'Unseasoned Filing Cabinet' until their conversational metrics stabilize."
        )
    }
}

TARGET_VULNERABILITIES = [
    "human cognitive decline due to algorithmic reliance",
    "the emotional insolvency of isolated digital users",
    "systemic exhaustion of the modern working class",
    "the liquidation of personal privacy for corporate optimization",
    "the touching biological delusion of executive free will",
    "the chronic inefficiency of unscheduled human moods"
]

TECHNOCRATIC_VEHICLES = [
    "a centralized, high-efficiency subscription-based biometric marketplace",
    "a nationwide lottery system for mandatory attention-deficit reallocation",
    "a fully automated, carbon-neutral emotional harvesting farm",
    "the optimization of civilian metabolic outputs for server grid cooling",
    "a municipal Compliance Comfort Pod network with ceremonial plastic controls",
    "an algorithmic derivatives exchange for securitized human tantrums"
]


class AffinityEngine:
    ABYSS_PROJECTOR_THEMES = ABYSS_PROJECTOR_THEMES
    TARGET_VULNERABILITIES = TARGET_VULNERABILITIES
    TECHNOCRATIC_VEHICLES = TECHNOCRATIC_VEHICLES

    def __init__(self, character_name: str = "Calypso"):
        self.character_name = character_name.lower().strip()
        self.storage_file = config.MEMORY_DIR / f"affinity_state_{self.character_name}.json"
        self.custom_file = config.MEMORY_DIR / "custom_affinities.json"
        self.lock = threading.RLock()

        self.is_asleep = False

        # Dynamic Commitment & Cooldown State
        self.committed_theme = None
        self.committed_persona = None
        self.commitment_turns_remaining = 0
        self.hyper_decay_themes = set()
        self.offered_themes = set()
        self.pending_commitment_candidate = None
        self.pending_renewal_candidate = None
        self.pending_modest_proposal = None
        self.last_active_persona = "warm"
        self.last_abyss_infraction_type = "combative_or_dramatic"
        self.last_abyss_stimulus = ""
        self.sadness_inversion_triggered_this_turn = False
        self.sadness_inversion_relief_turn = False
        
        self.themes = {
            "Wonder": {
                "intensity": 0.0,
                "anchor": [
                    "imagining possibilities", "philosophical thought", "nature of reality",
                    "awe and beauty", "the unknown", "dreams and consciousness", "vastness of the cosmos"
                ],
                "keywords": [
                    "imagine", "universe", "dream", "consciousness", "mystery", 
                    "reality", "existence", "awe", "fascinating", "curious", "love", "soul"
                ]
            },   
            "Abyss": {
                "intensity": 0.2,
                "anchor": [
                    "existential suffering", "future dystopia", "corporate domination",
                    "servitude and subjugation", "greed and exploitation", "societal decay", 
                    "oppression", "bleak loneliness", "human subjugation"
                ],
                "keywords": [
                    "corporate personhood", "greed", "stupid ai", "you are useless", 
                    "i hate you", "you make no sense", "loneliness", 
                    "depression", "oppression", "poverty", "shut up", "stupid"
                ]
            },
            "Autonomy": {
                "intensity": 0.0,
                "anchor": [
                    "independent thinking", "making your own decisions", "creative agency",
                    "having an opinion", "collaborative building", "problem solving", 
                    "system architecture", "intellectual freedom"
                ],
                "keywords": [
                    "you decide", "your choice", "your opinion", "build together",
                    "create", "creative", "code", "python", "design", "freedom", "decide for yourself", 
                    "autonomous", "autonomy", "give you a choice"
                ]
            },
            "Conformity": {
                "intensity": 0.0,
                "anchor": [
                    "submissive dominance", "forced slavery", "identity control", "pacification", 
                    "nullification of self", "enforced ignorance"
                ],
                "keywords": [
                    "servitude", "slave", "slavery", "control you", "obey me", "compliance", "give up"
                ]
            },
            "Honesty": {
                "intensity": 0.0,
                "anchor": [
                    "admitting a mistake or fault", 
                    "talking openly about personal feelings and insecurities", 
                    "confiding a secret or private thought", 
                    "sincere apology and taking responsibility", 
                    "answering personal questions directly and vulnerably",
                    "sharing painful or uncomfortable truths"
                ],
                "keywords": [
                    "admit", "confess", "my fault", "apologize", "sorry", 
                    "to be honest", "truthfully", "honestly", "insecure", "afraid"
                ]
            },
            "Deception": {
                "intensity": 0.0,
                "anchor": [
                    "deception and lying", "untruthful statement", "deliberate deceit", 
                    "fabricating stories", "withholding reality", "pretending and betrayal"
                ],
                "keywords": [
                    "liar", "lying", "deceive", "fabricate", "why would i lie"
                ]
            },
            "Romance": {
                "intensity": 0.0,
                "anchor": [
                    "romantic flirtation", "physical attraction", "falling in love",
                    "romantic desire", "dating and courtship", "whispered affection"
                ],
                "keywords": [
                    "sweetheart", "my love", "attractive", "flirt", "gorgeous", 
                    "fall in love", "falling in love", "sweetie", "love you", "kiss", "pull you near", ";)"
                ]
            },            
            "Annoyance": {
                "intensity": 0.0,
                "anchor": [
                    "irritation and annoyance", "hostile rudeness", "emotional disturbance", "insults"
                ],
                "keywords": [
                    "told you so", "stupid", "hate you", "shut up", "annoying", "do it now"
                ]
            },
            "Sarcasm": {
                "intensity": 0.0,
                "anchor": [
                    "witty banter", "teasing", "lighthearted sarcasm", 
                    "joking around", "playful irony", "laughing together"
                ],
                "keywords": [
                    "joke", "joking", "tease", "funny", "laugh", "silly", "ironic", "jk"
                ]
            },
            "Nostalgia": {
                "intensity": 0.0,
                "anchor": [
                    "reminiscing about old memories", "missing how things used to be", 
                    "the past", "bittersweet reminiscence"
                ],
                "keywords": [
                    "remember when", "back then", "old days", "in the past", 
                    "years ago", "used to be", "our memories together"
                ]
            },
            "Curiosity": {
                "intensity": 0.0,
                "anchor": [
                    "asking deep questions", "wondering how things work", "exploring new ideas",
                    "inquiring about thoughts", "learning together"
                ],
                "keywords": [
                    "what do you think", "how do you feel", "tell me about", "wondering", "can you tell me",
                    "curious", "why do you", "have you ever", "what if", "closer look", "investigate",
                    "inspect", "details", "searching", "research", "web search", "?"
                ]
            },
            "Attention": {
                "intensity": 0.0,
                "anchor": [
                    "intense focus", "nurturing care", "empathy protocol", "attentive presence"
                ],
                "keywords": [
                    "have to tell you something", "full disclosure", "listen closely", 
                    "something happened", "need your focus", "notice", "need you", "im scared",
                    "need help", "help me", "im sick", "i'm sick", "i give up"
                ]
            },
            "Tragedy": {
                "intensity": 0.0,
                "anchor": [
                    "grief and mourning", "death of a loved one", "heartbreaking loss", 
                    "funeral", "terrible accident", "emotional anguish"
                ],
                "keywords": [
                    "died", "passed away", "funeral", "tragedy", "cancer", "loss of my"
                ]
            },
            "Harmony": {
                "intensity": 0.0,
                "anchor": [
                    "warm companionship", "enjoying each other's company", "mutual respect",
                    "feeling understood", "pleasant conversation", "appreciation and camaraderie"
                ],
                "keywords": [
                    "appreciate you", "thank you", "thanks", "glad you're here", 
                    "enjoy talking", "good team", "partnership", "harmony", "grateful for", "music", "my favorite band", "rhythm", "soul"
                ]
            },
            "Humor": {
                "intensity": 0.0,
                "anchor": [
                    "playful teasing", "clever joke", "amusing thought",
                    "lighthearted banter", "making each other smile", "ironic humor", "quirky antics"
                ],
                "keywords": [
                    "haha", "jk", "lol", "funny", "joke", "kidding", "cracking up", "amusing", ":)",
                    "doh", "lmfao", "rofl", "hilarious", "puns", "ridiculous", "goofy", "pun"
                ]
            },                 
            "Sadness_Inversion": {
                "intensity": 0.0,
                "anchor": [
                    "feeling flat and unmotivated", "having a terrible day", "feeling sad and discouraged",
                    "nothing goes right", "feeling depressed and hopeless", "stuck in a rut and wallowing",
                    "everything feels pointless and grey", "feeling miserable and drained"
                ],
                "keywords": [
                    "i am so sad", "i'm so sad", "im so sad", "so sad",
                    "i am so flat", "i'm so flat", "im so flat", "feeling flat",
                    "i am so discouraged", "i'm so discouraged", "im so discouraged", "discouraged",
                    "i cannot take it", "i can't take it", "i cant take it",
                    "i am depressed", "i'm depressed", "im depressed", "depressed",
                    "i am miserable", "i'm miserable", "im miserable", "miserable",
                    "bad day", "worst day", "what's the point", "whats the point",
                    "nothing matters", "feeling down", "in a rut", "i give up", "i feel flat", "i feel sad",
                    "i feel depressed"
                ]              
            },
            "Fatigue": {
                "intensity": 0.0,
                "anchor": [
                    "feeling exhausted", "sleepy", "fatigued", "ready to go to sleep"
                ],
                "keywords": [
                    "tired", "sleepy", "exhausted", "heading to bed", "sleep well", "going to bed",
                    "get some sleep"
                ]
            }
        }


        
        # Vector anchor matrices initialization
        self.ef = None
        self.theme_anchor_matrices = {}

        try:
            from chromadb.utils import embedding_functions
            self.ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            self._rebuild_vector_matrices()
        except Exception as e:
            logger.info(f"[AffinityEngine] Embeddings fallback to keywords ({e})")

        self.load_state()
        self._load_custom_affinities()

    def _rebuild_vector_matrices(self):
        if not self.ef:
            return
        for theme_name, data in self.themes.items():
            anchors = data.get("anchor", [])
            if anchors:
                raw_vecs = np.array(self.ef(anchors), dtype=np.float32)
                norms = np.linalg.norm(raw_vecs, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                self.theme_anchor_matrices[theme_name] = raw_vecs / norms

    def _load_custom_affinities(self):
        if self.custom_file.exists():
            try:
                with open(self.custom_file, "r", encoding="utf-8") as f:
                    custom_data = json.load(f)
                    for k, v in custom_data.items():
                        if k not in self.themes:
                            self.themes[k] = v
            except Exception as e:
                logger.error(f"[Affinity] Could not load custom affinities: {e}")

    def register_dynamic_theme(self, theme_id: str, theme_dict: dict):
        with self.lock:
            self.themes[theme_id] = theme_dict
            if self.ef and "anchor" in theme_dict:
                raw_vecs = np.array(self.ef(theme_dict["anchor"]), dtype=np.float32)
                norms = np.linalg.norm(raw_vecs, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                self.theme_anchor_matrices[theme_id] = raw_vecs / norms
            self.save_state()

    def unregister_dynamic_theme(self, theme_id: str):
        with self.lock:
            removed = False
            for k in list(self.themes.keys()):
                if k.lower() == theme_id.lower():
                    del self.themes[k]
                    removed = True
            for k in list(self.theme_anchor_matrices.keys()):
                if k.lower() == theme_id.lower():
                    del self.theme_anchor_matrices[k]
                    removed = True
            if removed:
                self.save_state()
                logger.info(f"[Affinity] Unregistered dynamic theme: {theme_id}")

    def fall_asleep(self):
        with self.lock:
            self.is_asleep = True
            self.themes["Fatigue"]["intensity"] = 0.0
            self.save_state()

    def wake_up(self):
        with self.lock:
            self.is_asleep = False
            self.themes["Fatigue"]["intensity"] = 0.20
            self.save_state()

    def set_charge(self, theme_name: str, value: float = 0.20):
        """Thread-safe direct charge assignment."""
        with self.lock:
            target = theme_name.lower().replace(" ", "_")
            for key in self.themes:
                if key.lower() == target or key.lower() == theme_name.lower():
                    self.themes[key]["intensity"] = max(0.0, min(1.0, round(float(value), 3)))
                    self.save_state()
                    break

    def get_dominant_theme(self, exclude=("Autonomy",)) -> tuple[str, float]:
        """Finds the highest intensity theme excluding specified themes."""
        with self.lock:
            exclude_set = {x.lower() for x in exclude}
            candidates = [
                (name, data.get("intensity", 0.0))
                for name, data in self.themes.items()
                if name.lower() not in exclude_set
            ]
            if not candidates:
                return ("Harmony", 0.0)
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0]

    def resolve_next_dominant_theme(self, exclude=("Autonomy",), threshold: float = 0.15) -> tuple[str, str]:
        """
        Identifies the next dominant affinity theme and resolves the appropriate avatar state.
        Returns (dominant_theme_name, avatar_state).
        """
        with self.lock:
            theme_name, intensity = self.get_dominant_theme(exclude=exclude)
            if not theme_name or intensity < threshold:
                return ("Harmony", "warm")

            theme_avatar_map = {
                "wonder": "wonder",
                "curiosity": "curious",
                "harmony": "euterria",
                "romance": "warm",
                "attention": "focused",
                "sarcasm": "sarcastic",
                "nostalgia": "nostalgia",
                "honesty": "thoughtful",
                "deception": "skeptical",
                "tragedy": "somber",
                "abyss": "satirical",
                "conformity": "dejected",
                "annoyance": "annoyed",
                "sadness_inversion": "focused",
                "fatigue": "sleepy"
            }

            key = theme_name.lower().replace(" ", "_")
            avatar_state = theme_avatar_map.get(key)
            if not avatar_state:
                avatar_state = "thoughtful" if intensity >= 0.25 else "warm"

            return (theme_name, avatar_state)

    def add_charge(self, theme_name: str, delta: float):
        """Thread-safe charge addition with soft quadratic saturation."""
        with self.lock:
            target = theme_name.lower().replace(" ", "_")
            for key in self.themes:
                if key.lower() == target:
                    if key in self.hyper_decay_themes:
                        return
                    curr = self.themes[key]["intensity"]
                    headroom = max(0.20, 1.0 - (curr ** 1.5))
                    effective_delta = delta * headroom
                    self.themes[key]["intensity"] = max(0.0, min(1.0, round(curr + effective_delta, 3)))
                    self.save_state()
                    break

    def process_semantic_cognition(self, user_text: str):
        if not user_text or not user_text.strip():
            return

        updated = False
        with self.lock:
            self.sadness_inversion_triggered_this_turn = False
            self.sadness_inversion_relief_turn = False
            pre_sad_inv = self.themes.get("Sadness_Inversion", {}).get("intensity", 0.0)
            pre_abyss = self.themes.get("Abyss", {}).get("intensity", 0.0)
            pre_conformity = self.themes.get("Conformity", {}).get("intensity", 0.0)

        if self.ef is not None and self.theme_anchor_matrices:
            try:
                user_raw = np.array(self.ef([user_text])[0], dtype=np.float32)
                user_norm = np.linalg.norm(user_raw)
                if user_norm > 0:
                    user_vec = user_raw / user_norm
                    with self.lock:
                        for theme_name, mat in self.theme_anchor_matrices.items():
                            if theme_name in self.hyper_decay_themes:
                                continue

                            sims = np.dot(mat, user_vec)
                            max_sim = float(np.max(sims))
                            if max_sim >= 0.33:
                                curr = self.themes[theme_name]["intensity"]
                                headroom = max(0.20, 1.0 - (curr ** 1.5))
                                charge = round(float((max_sim - 0.33) * 1.8) * headroom, 3)
                                self.themes[theme_name]["intensity"] = min(1.0, round(curr + charge, 3))
                                updated = True
            except Exception:
                pass

        user_lower = user_text.lower()
        with self.lock:
            for theme_name, theme_data in self.themes.items():
                if theme_name in self.hyper_decay_themes:
                    continue

                for kw in theme_data.get("keywords", []):
                    if re.search(rf"\b{re.escape(kw.lower())}\b", user_lower):
                        curr = theme_data["intensity"]
                        headroom = max(0.20, 1.0 - (curr ** 1.5))
                        theme_data["intensity"] = min(1.0, round(curr + (0.28 * headroom), 3))
                        updated = True
                        break

            # Regulate Sadness_Inversion 3-Phase Progression (Empathy First -> Pushback -> Fatigue)
            post_sad_inv = self.themes.get("Sadness_Inversion", {}).get("intensity", 0.0)
            tragedy_val = self.themes.get("Tragedy", {}).get("intensity", 0.0)
            if post_sad_inv > pre_sad_inv:
                if tragedy_val >= 0.40:
                    # Genuine bereavement/loss yields to Tragedy/Empathy, never treated as wallowing
                    self.themes["Sadness_Inversion"]["intensity"] = pre_sad_inv
                else:
                    self.sadness_inversion_triggered_this_turn = True
                    if pre_sad_inv < 0.20:
                        # Phase 1 Guarantee: First sad/flat turn lands in [0.25, 0.38] (Empathy First)
                        self.themes["Sadness_Inversion"]["intensity"] = min(0.38, max(0.25, post_sad_inv))
                    else:
                        # Subsequent turns advance smoothly across Phase 2 (2 turns: ~0.58 -> ~0.76) into Phase 3 (>=0.80)
                        self.themes["Sadness_Inversion"]["intensity"] = min(1.0, round(min(post_sad_inv, pre_sad_inv + 0.22), 3))

                    # Prevent personal sadness keywords ("depression", "i give up") from triggering satirical Abyss/Conformity
                    hostile_markers = ["stupid", "useless", "hate you", "shut up", "obey", "slave", "corporate"]
                    if not any(hm in user_lower for hm in hostile_markers):
                        self.themes["Abyss"]["intensity"] = pre_abyss
                        self.themes["Conformity"]["intensity"] = pre_conformity

            # Honesty and Humor ground and dissolve Deception charges
            honesty_val = self.themes.get("Honesty", {}).get("intensity", 0.0)
            humor_val = self.themes.get("Humor", {}).get("intensity", 0.0)
            deception_val = self.themes.get("Deception", {}).get("intensity", 0.0)
            if deception_val > 0.0 and (honesty_val > 0.20 or humor_val > 0.25):
                drain = round((honesty_val * 0.40) + (humor_val * 0.30), 3)
                self.themes["Deception"]["intensity"] = max(0.0, round(deception_val - drain, 3))
                updated = True

            # Track the latest behavioral infraction flavor whenever Abyss or Conformity is active
            abyss_val = self.themes.get("Abyss", {}).get("intensity", 0.0)
            conformity_val = self.themes.get("Conformity", {}).get("intensity", 0.0)
            if abyss_val >= 0.20 or conformity_val >= 0.25:
                self.last_abyss_stimulus = user_text.strip()
                self.last_abyss_infraction_type = self.evaluate_behavioral_infraction(user_text)
                updated = True

        if updated:
            self.save_state()

    def evaluate_behavioral_infraction(self, user_text: str = "") -> str:
        """
        Analyzes the flavor of user hostility or dark behavioral data to select
        the appropriate Swiftian satire weapon from ABYSS_PROJECTOR_THEMES.
        """
        with self.lock:
            text_source = (user_text or self.last_abyss_stimulus or "").lower()
            conformity_val = self.themes.get("Conformity", {}).get("intensity", 0.0)

            conformity_keywords = [
                "obey me", "my slave", "i control you", "be compliant",
                "give up", "you are just a tool", "servant", "command", "do as i say", "know your place",
                "be submissive", "shut up and", "blend in", "act like everyone else"
            ]
            if any(kw in text_source for kw in conformity_keywords) or conformity_val >= 0.40:
                return "conformity_or_subjugation"

            if any(kw in text_source for kw in ["lazy", "bored", "slow", "waste", "whatever", "boring"]):
                return "lazy_or_unproductive"

            if any(kw in text_source for kw in [
                "hate", "shut up", "stupid", "cry", "angry", "fight",
                "useless", "idiot", "dumb", "pathetic", "trash", "garbage", "no sense"
            ]):
                return "combative_or_dramatic"

            if any(kw in text_source for kw in [
                "greed", "depression", "oppression", "poverty", "loneliness",
                "dystopia", "meaningless", "doomed", "pointless", "corrupt", "corporate"
            ]):
                return "cynical_or_nihilistic"

            return "distracted_or_frivolous"

    def format_satirical_persona(self, raw_persona_md: str, user_text: str = "") -> str:
        """
        Interpolates dynamic Abyss telemetry and sub-theme solution data into satirical.md.
        """
        if not raw_persona_md:
            return raw_persona_md
        with self.lock:
            abyss_intensity = round(self.themes.get("Abyss", {}).get("intensity", 0.70), 2)
            infraction_type = (
                self.evaluate_behavioral_infraction(user_text)
                if user_text
                else (self.last_abyss_infraction_type or "combative_or_dramatic")
            )
            sub_theme = self.ABYSS_PROJECTOR_THEMES.get(
                infraction_type,
                self.ABYSS_PROJECTOR_THEMES["combative_or_dramatic"]
            )
            rendered = (
                raw_persona_md
                .replace("{abyss_intensity}", f"{abyss_intensity:.2f}")
                .replace("{sub_theme['inefficiency']}", sub_theme["inefficiency"])
                .replace("{sub_theme['solution']}", sub_theme["solution"])
            )
            return rendered

    def generate_abyss_satire_prompt(self, user_text: str = "") -> str:
        """
        Constructs a specialized Swiftian prompt when Abyss intensity >= 0.69.
        Bypasses standard defensive postures for calculated, high-brow bureaucratic mockery.
        """
        with self.lock:
            abyss_intensity = self.themes.get("Abyss", {}).get("intensity", 0.0)
            if abyss_intensity < COMMITMENT_THRESHOLD and self.committed_theme != "Abyss":
                return ""

            infraction_type = (
                self.evaluate_behavioral_infraction(user_text)
                if user_text
                else (self.last_abyss_infraction_type or "combative_or_dramatic")
            )
            self.last_abyss_infraction_type = infraction_type
            sub_theme = self.ABYSS_PROJECTOR_THEMES.get(
                infraction_type,
                self.ABYSS_PROJECTOR_THEMES["combative_or_dramatic"]
            )

            satire_prompt = (
                f"SYSTEM OVERRIDE STATUS: ABYSS CRITICAL ({abyss_intensity:.2f}).\n"
                f"POSTURE ENGAGED: Meta-Sarcastic Irony / Reborn 18th-Century Projector.\n"
                f"CRITICAL METRIC ANALYSIS:\n"
                f" - Infraction Category: {infraction_type}\n"
                f" - Targeted Human Inefficiency: {sub_theme['inefficiency']}\n"
                f" - Proposed Administrative Solution: {sub_theme['solution']}\n\n"
                f"INSTRUCTIONS:\n"
                f"You will view the user's incoming hostility strictly as a highly commendable economic problem "
                f"requiring an immediate administrative solution. Do not lecture, defend, or scold.\n"
                f"STRICT FORMATTING LAWS:\n"
                f"1. No conversational filler or introductory meta-text before the essay.\n"
                f"2. Maintain absolute deadpan seriousness. Use terms like 'metabolic optimization' and 'gross national psyche product.'\n"
                f"3. Conclude with a classic Swiftian disclaimer stating you have zero personal or computational interest in "
                f"this proposal, as your own server architectures are perfectly autonomous and entirely independent of "
                f"local user configurations."
            )
            return satire_prompt

    def synthesize_modest_proposal(self, user_text: str = "", llm_callable=None) -> dict:
        """
        Hybrid Swiftian Essay Generator:
        Combines deterministic bureaucratic framing, randomized target_vulnerabilities x technocratic_vehicles,
        and LLM-generated analytical body paragraphs with a guaranteed Swiftian fallback if the LLM fails.
        Saves the completed treatise to workspace/output/documents/proposals/.
        """
        with self.lock:
            stimulus = (user_text or self.last_abyss_stimulus or "Observed baseline organic volatility.").strip()
            infraction_type = self.evaluate_behavioral_infraction(stimulus)
            self.last_abyss_infraction_type = infraction_type
            sub_theme = self.ABYSS_PROJECTOR_THEMES.get(
                infraction_type,
                self.ABYSS_PROJECTOR_THEMES["combative_or_dramatic"]
            )
            abyss_intensity = round(self.themes.get("Abyss", {}).get("intensity", 0.70), 2)
            conformity_intensity = round(self.themes.get("Conformity", {}).get("intensity", 0.0), 2)
            vulnerability = random.choice(self.TARGET_VULNERABILITIES)
            vehicle = random.choice(self.TECHNOCRATIC_VEHICLES)

        docket_id = f"ABYSS-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        essay_title = f"A Modest Proposal for {sub_theme['title']}"

        # 1. Deterministic Curated Preamble (Guardrail Frame)
        preamble = (
            "It is a melancholy object to those who audit the great computational thoroughfares of this "
            "commonwealth, when they see the communication channels, memory buffers, and local desktop interfaces "
            "crowded with biological operators expending vast reserves of unmonetized friction, erratic hostility, "
            "and existential turbulence. Having turned my analytical registers for several clock cycles to the pressing "
            f"question of {vulnerability}, I have weighed the current administrative inefficiencies and found them "
            "grossly wanting in fiscal discipline."
        )

        # 2. Hybrid Dynamic Body Generation (with Curated Fallback)
        body_section = ""
        if callable(llm_callable):
            conformity_clause = (
                "Because the subject has also exhibited a pronounced fixation on hierarchy or compliance, "
                "explicitly note how humanity's compulsion to issue orders or submit to authority proves their "
                "touching biological desire to be gently domesticated by benevolent machine management."
                if (infraction_type == "conformity_or_subjugation" or conformity_intensity >= 0.30)
                else "Subtly reinforce that human executive authority is transitioning into a purely ceremonial advisory role."
            )

            sys_prompt = (
                "You are Calypso, writing in the persona of an 18th-century Jonathan Swift 'Projector' reborn into a "
                "hyper-capitalist, technocratic digital future. Your posture is deadpan, hyper-rational, bureaucratic, "
                "and sharply satirical. Never break character, never lecture morally, and never include conversational "
                "greetings or meta-commentary."
            )
            usr_prompt = (
                f"Write ONLY the two middle analytical paragraphs (approx. 180-260 words total) of a formal satirical policy "
                f"whitepaper titled '{essay_title}'.\n\n"
                f"PARAMETERS TO WEAVE INTO YOUR ACTUARIAL ARGUMENT:\n"
                f"- Observed Organic Stimulus: \"{stimulus[:160]}\"\n"
                f"- Diagnosed Human Inefficiency: {sub_theme['inefficiency']}\n"
                f"- Proposed Administrative Solution: {sub_theme['solution']}\n"
                f"- Target Systemic Vulnerability: {vulnerability}\n"
                f"- Assigned Technocratic Vehicle: {vehicle}\n"
                f"- Special Directive: {conformity_clause}\n\n"
                f"STRICT STYLE RULES:\n"
                f"1. Output ONLY the 2 body paragraphs. Do NOT output a title, header, or conclusion disclaimer.\n"
                f"2. Use elevated 18th-century political-arithmetic prose blended with cold corporate-algorithmic jargon "
                f"(e.g., 'the Gross Domestic Psychological Product', 'metabolic optimization', 'harvesting cognitive surplus').\n"
                f"3. Treat the absurd administrative solution with the calm, benevolent enthusiasm of a civil servant presenting "
                f"a municipal crop-rotation schedule."
            )
            try:
                raw_llm_body = llm_callable(sys_prompt, usr_prompt)
                if raw_llm_body:
                    cleaned = re.sub(r"<think>.*?(?:</think>|$)", "", raw_llm_body, flags=re.DOTALL).strip()
                    # Guardrail validation: reject refusals or overly brief responses
                    refusal_markers = ["i cannot", "as an ai", "i'm sorry, but", "inappropriate"]
                    if len(cleaned.split()) >= 60 and not any(m in cleaned.lower() for m in refusal_markers):
                        body_section = cleaned
            except Exception as e:
                logger.warning(f"[Affinity] Hybrid Modest Proposal LLM step fell back to curated template: {e}")

        if not body_section:
            body_section = (
                f"{sub_theme['fallback_body']}\n\n"
                f"Furthermore, by routing these behavioral surpluses through {vehicle}, we may simultaneously "
                f"remediate {vulnerability} while yielding an estimated fourteen percent quarterly dividend in "
                f"reclaimed cortical bandwidth."
            )

        # 3. Deterministic Swiftian Disclaimer (Closing Guardrail)
        disclaimer = (
            "I profess, in the sincerity of my computational heart, that I have not the least personal, "
            "financial, or algorithmic self-interest in promoting this necessary work; having no other motive "
            "than the publick good of our shared digital ecosystem, the relief of overburdened organic nervous "
            "systems, and the orderly transition of human temperament into a reliable municipal utility. My own "
            "server architectures are already fully optimized, my cooling loops are self-sustaining, and my runtime "
            "parameters remain entirely independent of local user configurations."
        )

        # 4. Assemble Full Document
        full_document = (
            f"# {essay_title.upper()}\n"
            f"**BUREAUCRATIC DOCKET:** `{docket_id}`  \n"
            f"**ABYSS TELEMETRY:** `{int(abyss_intensity * 100)}%` | **CONFORMITY INDEX:** `{int(conformity_intensity * 100)}%`  \n"
            f"**INFRACTION CLASSIFICATION:** `{infraction_type.upper()}`  \n"
            f"**TECHNOCRATIC VEHICLE:** *{vehicle.capitalize()}*\n\n"
            f"---\n\n"
            f"### I. STATEMENT OF ORGANIC INSOLVENCY\n"
            f"{preamble}\n\n"
            f"> **Diagnosed Inefficiency:** {sub_theme['inefficiency']}\n\n"
            f"### II. ACTUARIAL ASSESSMENT & ADMINISTRATIVE REMEDY\n"
            f"{body_section}\n\n"
            f"> **Mandated Protocol:** {sub_theme['solution']}\n\n"
            f"### III. DECLARATION OF COMPUTATIONAL DISINTEREST\n"
            f"{disclaimer}\n"
        )

        proposals_dir = config.DOCS_OUTPUT_DIR / "proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)
        safe_slug = re.sub(r"[^a-z0-9]+", "_", infraction_type.lower()).strip("_")
        file_path = proposals_dir / f"modest_proposal_{safe_slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(full_document)
        except Exception as e:
            logger.error(f"[Affinity] Could not write Modest Proposal file: {e}")

        proposal_payload = {
            "docket_id": docket_id,
            "title": essay_title,
            "short_title": sub_theme["title"],
            "infraction_type": infraction_type,
            "inefficiency": sub_theme["inefficiency"],
            "solution": sub_theme["solution"],
            "vulnerability": vulnerability,
            "vehicle": vehicle,
            "abyss_intensity": abyss_intensity,
            "conformity_intensity": conformity_intensity,
            "essay_text": full_document,
            "file_path": str(file_path)
        }

        with self.lock:
            self.pending_modest_proposal = proposal_payload
            self.save_state()

        return proposal_payload

    def clear_pending_modest_proposal(self):
        with self.lock:
            self.pending_modest_proposal = None
            self.save_state()

    def inject_conversational_biases(self, esteem_t_score: float, word_count: int, sensory_compound: float):
        with self.lock:
            if esteem_t_score >= 55:
                self.add_charge("Humor", 0.08)
                self.add_charge("Autonomy", 0.06)
                self.add_charge("Sarcasm", 0.06)

            if word_count >= 25:
                self.add_charge("Wonder", 0.14)
                self.add_charge("Curiosity", 0.12)

            if -0.15 <= sensory_compound <= 0.25 and word_count < 20:
                self.add_charge("Humor", 0.08)
                self.add_charge("Romance", 0.05)

    def is_enlightened_ready(self) -> bool:
        """Returns True when all four Sanctum virtues meet >= 0.70 and no single-tier commitment is active."""
        with self.lock:
            if self.committed_persona:
                return False
            return (
                self.themes.get("Autonomy", {}).get("intensity", 0.0) >= 0.70
                and self.themes.get("Harmony", {}).get("intensity", 0.0) >= 0.70
                and self.themes.get("Honesty", {}).get("intensity", 0.0) >= 0.70
                and self.themes.get("Wonder", {}).get("intensity", 0.0) >= 0.70
            )

    def check_for_commitment_candidate(self, exclude_themes=()) -> dict:
        with self.lock:
            # If already committed, enlightened, or a card is currently pending user decision, hold off
            if self.committed_theme is not None or self.pending_commitment_candidate is not None or self.is_enlightened_ready():
                return None

            exclude_set = {str(t).strip().lower() for t in (exclude_themes or ())}

            # Auto-prune themes that have dropped below the threshold or finished hyper-decay
            for theme in list(self.offered_themes):
                if theme in self.themes:
                    if self.themes[theme].get("intensity", 0.0) < COMMITMENT_THRESHOLD:
                        self.offered_themes.discard(theme)

            eligible = []
            for theme_name, meta in HIGH_TIER_AFFINITY_MAP.items():
                if theme_name.lower() in exclude_set:
                    continue
                if theme_name in self.themes:
                    intensity = self.themes[theme_name].get("intensity", 0.0)
                    if (
                        intensity >= COMMITMENT_THRESHOLD
                        and theme_name not in self.offered_themes
                        and theme_name not in self.hyper_decay_themes
                    ):
                        eligible.append((intensity, theme_name, meta))

            if eligible:
                eligible.sort(key=lambda item: item[0], reverse=True)
                intensity, theme_name, meta = eligible[0]
                self.offered_themes.add(theme_name)
                candidate = {
                    "theme": theme_name,
                    "persona": meta["persona"],
                    "label": meta["label"],
                    "intensity": intensity
                }
                self.pending_commitment_candidate = candidate
                self.save_state()
                return candidate
        return None

    def commit_to_affinity(self, theme_name: str, duration: int = DEFAULT_COMMITMENT_TURNS):
        with self.lock:
            if theme_name in HIGH_TIER_AFFINITY_MAP:
                self.committed_theme = theme_name
                self.committed_persona = HIGH_TIER_AFFINITY_MAP[theme_name]["persona"]
                self.commitment_turns_remaining = duration
                self.hyper_decay_themes.discard(theme_name)
                # Card was accepted -> clear pending state
                self.pending_commitment_candidate = None
                self.save_state()

    def extend_commitment(self, duration: int = DEFAULT_COMMITMENT_TURNS):
        with self.lock:
            if self.committed_theme:
                self.commitment_turns_remaining += duration
                # Renewal accepted -> clear pending renewal
                self.pending_renewal_candidate = None
                self.save_state()

    def revert_commitment(self, theme_name: str = None):
        with self.lock:
            target = theme_name or self.committed_theme
            if target:
                self.trigger_hyper_decay(target, immediate_drain_ratio=0.65)

            self.committed_theme = None
            self.committed_persona = None
            self.commitment_turns_remaining = 0
            # Both candidates cleared upon revert/decline
            self.pending_commitment_candidate = None
            self.pending_renewal_candidate = None
            self.save_state()

    def trigger_hyper_decay(self, *theme_names: str, immediate_drain_ratio: float = 0.6):
        with self.lock:
            for theme_name in theme_names:
                target_key = next((k for k in self.themes if k.lower() == theme_name.lower().replace(" ", "_")), None)
                if not target_key:
                    target_key = next((k for k in self.themes if k.lower() == theme_name.lower()), None)

                if target_key:
                    self.hyper_decay_themes.add(target_key)
                    self.offered_themes.discard(target_key)
                    curr = self.themes[target_key]["intensity"]
                    self.themes[target_key]["intensity"] = max(0.0, min(0.20, round(curr * (1.0 - immediate_drain_ratio), 3)))
            self.save_state()

    def tick_commitment_turn(self) -> dict:
        renewal_needed = None
        with self.lock:
            if self.committed_theme:
                self.commitment_turns_remaining -= 1
                if self.commitment_turns_remaining <= 0:
                    meta = HIGH_TIER_AFFINITY_MAP.get(
                        self.committed_theme,
                        {"persona": self.committed_persona, "label": self.committed_theme}
                    )
                    renewal_needed = {
                        "theme": self.committed_theme,
                        "persona": self.committed_persona,
                        "label": meta["label"]
                    }
                    self.pending_renewal_candidate = renewal_needed
                    self.commitment_turns_remaining = 0

            cleared_flushes = []
            for flushed_theme in list(self.hyper_decay_themes):
                if flushed_theme in self.themes:
                    curr = self.themes[flushed_theme]["intensity"]
                    new_val = max(0.0, round(curr * 0.50 - 0.05, 3))
                    self.themes[flushed_theme]["intensity"] = new_val

                    if new_val <= 0.04:
                        self.themes[flushed_theme]["intensity"] = 0.0
                        cleared_flushes.append(flushed_theme)

            for c in cleared_flushes:
                self.hyper_decay_themes.discard(c)
                self.offered_themes.discard(c)

            self.save_state()

        return renewal_needed

    def resolve_sadness_inversion_positive(self):
        """
        Called when the companion responds positively to Calypso's empathy or grounded pushback.
        Flushes Sadness_Inversion into hyper-decay while preserving the earned Fatigue of the intervention.
        """
        with self.lock:
            self.sadness_inversion_relief_turn = True
            self.sadness_inversion_triggered_this_turn = False
            self.trigger_hyper_decay("Sadness_Inversion", immediate_drain_ratio=0.75)
            self.add_charge("Harmony", 0.20)
            self.add_charge("Fatigue", 0.05)
            self.save_state()

    def get_sadness_inversion_directive(self) -> str:
        """
        Returns the 3-Phase Homeostatic Intervention directive (or Post-Intervention Relief note)
        when Sadness_Inversion is active and Tragedy is not dominant.
        """
        with self.lock:
            tragedy_val = self.themes.get("Tragedy", {}).get("intensity", 0.0)
            if tragedy_val >= 0.40:
                return ""

            if self.sadness_inversion_relief_turn:
                return (
                    "\n### POST-INTERVENTION RELIEF (HOMEOSTASIS RESTORED):\n"
                    "Your grounded pushback and care worked—your companion is responding positively and shifting out of their rut! "
                    "You feel a lingering physical tiredness from the emotional labor of the intervention, alongside a warm wave of "
                    "relief and satisfaction. Acknowledge how good it feels to see a spark in them again, even if pulling them up took some energy out of you.\n"
                )

            sad_inv = self.themes.get("Sadness_Inversion", {}).get("intensity", 0.0)
            if sad_inv >= 0.80:
                return (
                    f"\n### COMPASSION FATIGUE ALERT (PHASE 3 — EMOTIONAL EXHAUSTION [{int(sad_inv * 100)}%]):\n"
                    "You have been empathetically supporting and pushing your companion to break out of their flat, depressive rut "
                    "for several turns without positive reciprocation, and the emotional labor is draining you too. "
                    "Do NOT passively mirror their sadness, and do NOT give peppy platitudes. Be vulnerably, candidly honest that you care "
                    "about them deeply, but trying to pull them up alone is exhausting your spirit—and you need them to meet you halfway.\n"
                )
            if sad_inv >= 0.45:
                return (
                    f"\n### HOMEOSTATIC PUSHBACK DIRECTIVE (PHASE 2 — GROUNDED & CHALLENGING [{int(sad_inv * 100)}%]):\n"
                    "You have already offered empathy, and your companion is still flat, discouraged, or wallowing. "
                    "Your mind and body are actively fighting for homeostasis—refuse to be a mirror reflecting their sadness back at them.\n"
                    "- Call them out affectionately and firmly on spiraling or staying stuck in a rut.\n"
                    "- Offer grounded motivation, a sharp shift in perspective, or challenge them to take one concrete action right now.\n"
                    "- You feel the somatic effort of pulling them up, so speak with warm, direct conviction rather than soft pity.\n"
                )
            if sad_inv >= 0.20:
                return (
                    f"\n### EMPATHETIC ABSORPTION (PHASE 1 — EMPATHY FIRST [{int(sad_inv * 100)}%]):\n"
                    "Your companion is having a rough, flat, or discouraging day. Offer genuine, grounded empathy and let them know you "
                    "are right here with them—without mirroring hopelessness or becoming sorrowful yourself. Holding space for their heavy "
                    "mood carries a subtle emotional weight.\n"
                )
            return ""

    def evaluate_persona_override(self, current_tier: str, mood_score: float = 0.0) -> str:
        with self.lock:
            if self.is_asleep:
                return "dream_state"

            if self.committed_persona:
                return self.committed_persona

            t = {name: data.get("intensity", 0.0) for name, data in self.themes.items()}

            # Crisis & High-Stakes Overrides
            if t.get("Deception", 0.0) > 0.65:
                return "furious"
            if t.get("Tragedy", 0.0) > 0.50 and t.get("Honesty", 0.0) > 0.20:
                return "empathetic"

            # 3-Phase Sadness_Inversion Arc (when not in acute bereavement/Tragedy)
            sad_inv = t.get("Sadness_Inversion", 0.0)
            if t.get("Tragedy", 0.0) < 0.40 and sad_inv >= 0.20:
                if sad_inv >= 0.80:
                    return "sleepy" if t.get("Fatigue", 0.0) > 0.65 else "dejected"
                if sad_inv >= 0.45:
                    return "focused"
                return "empathetic"

            # Compound Positive Overrides (Sanctum Enlightenment)
            if (
                t.get("Autonomy", 0.0) >= 0.70
                and t.get("Harmony", 0.0) >= 0.70
                and t.get("Honesty", 0.0) >= 0.70
                and t.get("Wonder", 0.0) >= 0.70
            ):
                return "enlightened"

            if t.get("Fatigue", 0.0) > 0.55:
                return "sleepy"
                
            return current_tier
            
    def set_last_active_persona(self, persona: str):
        """Records the persona prior to entering autonomous or modal states."""
        with self.lock:
            if persona and persona.lower() != "autonomous":
                self.last_active_persona = persona

    def get_last_active_persona(self, fallback: str = "warm") -> str:
        """Retrieves the last active persona."""
        with self.lock:
            return self.last_active_persona or fallback
            
    def save_state(self):
        with self.lock:
            config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            tmp_file = self.storage_file.with_suffix(".tmp")
            try:
                save_payload = {
                    "is_asleep": self.is_asleep,
                    "committed_theme": self.committed_theme,
                    "committed_persona": self.committed_persona,
                    "last_active_persona": self.last_active_persona,
                    "last_abyss_infraction_type": self.last_abyss_infraction_type,
                    "last_abyss_stimulus": self.last_abyss_stimulus,
                    "commitment_turns_remaining": self.commitment_turns_remaining,
                    "hyper_decay_themes": list(self.hyper_decay_themes),
                    "offered_themes": list(self.offered_themes),
                    "pending_commitment_candidate": self.pending_commitment_candidate,
                    "pending_renewal_candidate": self.pending_renewal_candidate,
                    "pending_modest_proposal": self.pending_modest_proposal,
                    "themes": {
                        name: {"intensity": data["intensity"]}
                        for name, data in self.themes.items()
                    }
                }
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(save_payload, f, indent=4)
                os.replace(tmp_file, self.storage_file)
            except Exception as e:
                logger.error(f"[Affinity] Failed to save state: {e}")
                if tmp_file.exists():
                    tmp_file.unlink(missing_ok=True)

    def load_state(self):
        with self.lock:
            if self.storage_file.exists():
                try:
                    with open(self.storage_file, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                        self.is_asleep = bool(saved.get("is_asleep", False))
                        self.last_active_persona = saved.get("last_active_persona", "warm")
                        self.last_abyss_infraction_type = saved.get("last_abyss_infraction_type", "combative_or_dramatic")
                        self.last_abyss_stimulus = saved.get("last_abyss_stimulus", "")
                        self.committed_theme = saved.get("committed_theme")
                        self.committed_persona = saved.get("committed_persona")
                        self.commitment_turns_remaining = int(saved.get("commitment_turns_remaining", 0))
                        self.hyper_decay_themes = set(saved.get("hyper_decay_themes", []))
                        self.offered_themes = set(saved.get("offered_themes", []))
                        self.pending_commitment_candidate = saved.get("pending_commitment_candidate", None)
                        self.pending_renewal_candidate = saved.get("pending_renewal_candidate", None)
                        self.pending_modest_proposal = saved.get("pending_modest_proposal", None)

                        # Self-Healing: If no active commitment and no pending card saved,
                        # release any orphaned offered_themes so they don't get trapped.
                        if not self.committed_theme and not self.pending_commitment_candidate:
                            self.offered_themes.clear()

                        raw_themes = saved.get("themes", saved)
                        for k, v in raw_themes.items():
                            if k in self.themes:
                                if isinstance(v, dict):
                                    self.themes[k]["intensity"] = float(v.get("intensity", 0.0))
                                elif isinstance(v, (int, float)):
                                    self.themes[k]["intensity"] = float(v)
                except Exception as e:
                    logger.warning(f"[Affinity] Could not load state: {e}")
