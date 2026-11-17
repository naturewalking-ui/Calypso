# modules/emotion/associative_curiosity.py

import json
import logging
import os
import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modules.config import config

logger = logging.getLogger("EmotionEngine.AssociativeCuriosity")

PREDICATE_MAP = {
    "collecting": ["collecting", "hunting for", "accumulating", "hoarding", "collects", "collect"],
    "building": [
        "assembling", "soldering", "building", "crafting",
        "coding in", "programming in", "builds", "build", "code in", "program in"
    ],
    "tinkering": [
        "customizing", "tinkering with", "tinkering", "modding", "hacking",
        "tuning", "tinker with", "tinker"
    ],
    "creating": [
        "composing", "designing", "animating", "painting", "drawing", "writing",
        "illustrating", "paint", "draw", "compose", "illustrate"
    ],
    "studying": [
        "deep diving into", "reading about", "reading", "researching", "studying",
        "learning", "read about", "read", "study", "research", "learn"
    ],
    "playing": ["practicing", "competing in", "playing", "gaming", "play", "game"],
    "observing": [
        "photographing", "birdwatching", "stargazing", "watching", "tracking",
        "listening to", "listen to", "photograph", "watch", "track"
    ],
}

# Subordinate, temporal, situational, purpose, and circumstantial conjunctions / prepositions
# Slices away trailing clauses that would otherwise bleed into the extracted topic.
SUBORDINATE_CLAUSE_PATTERN = re.compile(
    r"\s+\b(?:"
    # Temporal & Life-stage clauses
    r"when(?:ever)?\s+(?:i|we|my|it|you|they|he|she)\b|"
    r"while\s+(?:i|we|my|it|you|they|growing)\b|"
    r"as\s+a\s+(?:kid|child|teenager|teen|youngster|hobby|student)\b|"
    r"back\s+(?:in|when)\b|"
    r"since\s+(?:i|last|childhood|college|high\s+school|[0-9]{4})\b|"
    r"(?:a\s+few|a\s+couple\s+of)\s+(?:days|weeks|months|years)\s+ago\b|"
    # Purpose & Infinitive clauses (excluding root intent)
    r"to\s+(?:try|see|help|get|keep|relax|unwind|pass|travel|visit)\b|"
    # Company & Social
    r"with\s+(?:my|some|friends?|family|cousins?|the\s+guys|buddies|coworkers?)\b|"
    # Setting & Location
    r"out\s+in\s+(?:my|the|a)\b|"
    r"(?:in|at|out\s+in|inside|around)\s+(?:my|the|a)\s+(?:basement|garage|workshop|room|attic|shed|house|home|backyard|office|lab|studio|workbench)\b|"
    r"\bat\s+(?:home|work|school|college|university)\b|"
    r"\bin\s+(?:the\s+mountains|the\s+woods|nature|the\s+city|high\s+school|college|my\s+twenties|the\s+evening|the\s+evenings|the\s+morning|my\s+spare\s+time)\b|"
    # Frequency & Schedule
    r"on\s+(?:the\s+)?(?:weekends?|sundays?|mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?)\b|"
    r"every\s+(?:sunday|monday|tuesday|wednesday|thursday|friday|saturday|weekend|day|morning|night|week)\b|"
    # Period & Era
    r"during\s+(?:high\s+school|college|lockdown|summer|winter|the\s+pandemic|the\s+season)\b|"
    # Causal & Rationale
    r"(?:because|cuz|'cause|\bcause\s+(?:i|it|they|we|you))\b|"
    r"so\s+that\b|"
    r"for\s+(?:my|fun|mini|work|school|practice|display|relaxation|a\s+living|sale|their|the\s+history|years|a\s+while)\b|"
    # Recency & Adverbial Fillers
    r"recently|lately|nowadays|these\s+days|anymore|growing\s+up\b|"
    r"though|honestly|actually|tbh"
    r")\b.*$",
    re.IGNORECASE
)

# Conversational syntactic patterns matching how real humans mention hobbies & fandoms
# Ordered intentionally: specific hobby/passion phrases without greedy relational catch-alls
CASUAL_INTEREST_PATTERNS = [
    # 1. "fan of [topic]", "supporter of [topic]"
    (r"\b(?:i(?:'m| am)?\s+(?:a\s+)?(?:huge|big|massive|giant|total|major|casual|avid|die-hard)?\s*(?:fan|supporter|follower|nerd|geek)\s+(?:of|for))\s+(.+)", "interest"),

    # 2. Noun before fan/nerd/geek: "huge [topic] fan", "[topic] nerd"
    (r"\b(?:i(?:'m| am)?\s+(?:a\s+)?(?:huge|big|massive|giant|total|major|casual|avid|die-hard)?\s*(.+?)\s+(?:fan|supporter|follower|nerd|geek))\b", "interest"),

    # 3. Identity statements: "i am an avid hiker", "i'm an amateur astronomer"
    (r"\b(?:i(?:'m| am)?\s+(?:an?|the)\s+(?:avid|amateur|casual|passionate|lifelong|dedicated)\s+(.+))\b", "interest"),

    # 4. Sports fandom: "root for", "cheer for", "follow"
    (r"\b(?:i\s+(?:always\s+|personally\s+)?(?:root\s+for|cheer\s+for|follow))\s+(.+)", "interest"),

    # 5. Childhood / Nostalgia: "growing up I [verbed]"
    (r"\b(?:(?:growing\s+up|when\s+i\s+was\s+younger)\s*,?\s*i\s+(?:collected|played|loved|enjoyed|built|watched|read))\s+(.+)", "interest"),
    (r"\b(?:i\s+grew\s+up\s+(?:playing|collecting|building|reading|watching))\s+(.+)", "interest"),

    # 6. Infinitive action verbs: "i love to play [topic]", "i like to build [topic]"
    (r"\b(?:i(?:'ve| have)?\s+(?:always\s+)?(?:really|quite)?\s*(?:love|like|enjoy|prefer)\s+to\s+(?:play|game))\s+(.+)", "playing"),
    (r"\b(?:i(?:'ve| have)?\s+(?:always\s+)?(?:really|quite)?\s*(?:love|like|enjoy|prefer)\s+to\s+(?:build|craft|solder|assemble))\s+(.+)", "building"),
    (r"\b(?:i(?:'ve| have)?\s+(?:always\s+)?(?:really|quite)?\s*(?:love|like|enjoy|prefer)\s+to\s+(?:collect|hunt\s+for))\s+(.+)", "collecting"),
    (r"\b(?:i(?:'ve| have)?\s+(?:always\s+)?(?:really|quite)?\s*(?:love|like|enjoy|prefer)\s+to\s+(?:tinker\s+with|mod|customize|hack))\s+(.+)", "tinkering"),
    (r"\b(?:i(?:'ve| have)?\s+(?:always\s+)?(?:really|quite)?\s*(?:love|like|enjoy|prefer)\s+to\s+(?:paint|draw|write|compose|illustrate))\s+(.+)", "creating"),
    (r"\b(?:i(?:'ve| have)?\s+(?:always\s+)?(?:really|quite)?\s*(?:love|like|enjoy|prefer)\s+to\s+(?:read\s+about|study|research|learn\s+about))\s+(.+)", "studying"),
    (r"\b(?:i(?:'ve| have)?\s+(?:always\s+)?(?:really|quite)?\s*(?:love|like|enjoy|prefer)\s+to\s+(?:photograph|track|stargaze))\s+(.+)", "observing"),

    # 7. Direct action verbs with modalities (like playing, love building, enjoy reading)
    (r"\b(?:i\s+(?:love\s+playing|enjoy\s+playing|like\s+playing))\s+(.+)", "playing"),
    (r"\b(?:i\s+(?:love\s+building|enjoy\s+building|like\s+building|love\s+crafting|enjoy\s+crafting))\s+(.+)", "building"),
    (r"\b(?:i\s+(?:collect|love\s+collecting|enjoy\s+collecting|like\s+collecting|hunt\s+for))\s+(.+)", "collecting"),
    (r"\b(?:i\s+(?:tinker\s+with|love\s+tinkering\s+with|enjoy\s+tinkering\s+with|like\s+tinkering\s+with))\s+(.+)", "tinkering"),
    (r"\b(?:i\s+(?:love\s+drawing|enjoy\s+drawing|like\s+drawing|love\s+painting|enjoy\s+painting|like\s+painting))\s+(.+)", "creating"),
    (r"\b(?:i\s+(?:read\s+a\s+lot\s+of|read\s+a\s+lot\s+about|deep\s+dive\s+into|study|research|love\s+reading\s+about|like\s+reading\s+about))\s+(.+)", "studying"),
    (r"\b(?:been\s+reading\s+a\s+lot\s+of|been\s+reading\s+about)\s+(.+)", "studying"),
    (r"\b(?:i\s+(?:watch\s+a\s+lot\s+of|watch\s+a\s+lot\s+about|stargaze))\s+(.+)", "observing"),
    (r"\b(?:i\s+(?:listen\s+to\s+a\s+lot\s+of|love\s+listening\s+to|like\s+listening\s+to|enjoy\s+listening\s+to))\s+(.+)", "observing"),
    (r"\b(?:i\s+(?:program\s+in|code\s+in|love\s+coding\s+in|like\s+coding\s+in|love\s+programming\s+in|like\s+programming\s+in))\s+(.+)", "building"),

    # 8. Learning / Self-teaching (handling "how to play piano" -> "piano")
    (r"\b(?:i(?:'m| am|'ve been| have been)?\s+(?:learning\s+about|teaching\s+myself|studying))\s+(?:how\s+to\s+)?(.+)", "studying"),

    # 9. Time & Routine
    (r"\b(?:i\s+spend\s+(?:most\s+of\s+my\s+time|a\s+lot\s+of\s+time|all\s+my\s+weekends|my\s+free\s+time)\s+(?:on|doing|playing|reading|watching|building|making|tinkering\s+with|coding|practicing)?)\s+(.+)", "interest"),

    # 10. Explicit hobby / interest declarations
    (r"\b(?:i(?:'m| am|'ve been| have been)?\s+(?:really|super|pretty|heavily|deeply)?\s*(?:into|obsessed with|hooked on|fascinated by|passionate about))\s+(.+)", "interest"),
    (r"\b(?:i\s+have\s+a\s+(?:deep\s+|huge\s+|real\s+)?passion\s+for)\s+(.+)", "interest"),
    (r"\b(?:my\s+(?:absolute\s+)?(?:favorite|favourite|go-to|main)\s+(?:hobby|pastime|sport|team|game|interest|subject)\s+is)\s+(.+)", "interest"),
]

# Explicit trigger list fallback (sorted longest to shortest)
EXPLICIT_TRIGGERS = sorted([
    "i am interested in", "my passion is", "my hobbies are", "my hobby is",
    "i love collecting", "i like collecting", "i enjoy collecting", "i started collecting",
    "i love tinkering with", "i like tinkering with", "i love playing", "i like playing",
    "i enjoy playing", "i love building", "i like building", "i enjoy building",
    "i was tinkering with", "i'm deep into", "i've been exploring",
    "i studied", "i also studied", "i'm really into", "i'm a big fan of",
    "i'm a fan of", "i am a fan of", "i'm passionate about", "i have a passion for",
    "i spend my free time", "i spend my weekends", "my favorite pastime is",
    "i've always been captivated by", "i'm totally hooked on",
    "i'm geeky about", "i'm nerdy about", "i'm completely obsessed with",
    "i'm constantly tinkering with", "i've been geeking out over",
    "i'm fascinated by the world of", "i'm a collector of",
    "i love crafting", "i like crafting", "i enjoy crafting",
    "my main interest is", "i'm fascinated by", "i've been getting into",
    "my chief interest is", "i dedicate my time to"
], key=len, reverse=True)

# Personal pronouns, relational phrases, and non-topic strings that should NEVER be logged as interests
STOP_TOPICS = {
    "you", "it", "this", "that", "them", "her", "him", "me", "us", "myself", "yourself",
    "everything", "something", "anything", "nothing", "all", "here", "there",
    "talking to you", "chatting with you", "hanging out with you", "being with you", "spending time with you",
    "talking", "chatting", "thinking", "doing this", "doing that", "it all",
    "mistake", "mistakes", "three times", "assertive", "back scratched"
}

# Tokens that indicate a conversational/relational clause directed at Calypso or pronouns rather than a hobby/topic
DISALLOWED_TOPIC_TOKENS = {
    "you", "your", "yours", "yourself", "u", "ya",
    "calypso", "baby", "babe", "hunny", "honey", "darling", "sweetheart",
    "me", "my", "mine", "myself", "i", "we", "us", "our", "ours",
    "it", "its", "them", "they", "their", "this", "that", "these", "those",
    "him", "his", "her", "hers", "she", "he",
    "who", "what", "when", "where", "why", "how", "whether", "if", "because",
    "mistake", "mistakes", "sure", "default", "prompt", "prompts", "exe",
    "everthing", "everything", "anything", "nothing", "something"
}

NEGATIVE_MENTION_PHRASES = [
    "hate", "dont like", "don't like", "dislike", "sick of", "tired of",
    "stop talking about", "not interested", "despise", "annoying"
]


class AssociativeCuriosityEngine:
    """
    AssociativeCuriosityEngine manages grounded, single-topic curiosity:
    1. User Longitudinal Interests (acknowledging an existing interest or offering a suggestion to look into something similar).
    2. Calypso Autonomous Companion Interests (seeded from PDF reading or web research, shared on their own merits).
    3. Biological Refractory Cooldowns & Closed-Loop Feedback (Accepted / Lukewarm / Rejected).
    4. Reverie Check-in Card Payload Formatting for the Center GUI window.

    Note: Cross-interest combination (Intersection A ∩ B) has been retired to prevent mismatched pairings.
    """
    def __init__(self, memory_engine=None, kg_engine=None, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or (config.MEMORY_DIR / "curiosity_ledger.json")
        self.memory_engine = memory_engine
        self.kg_engine = kg_engine
        self.lock = threading.RLock()
        self.data = self._load_storage()
        self._refresh_lifecycle_states()

    # -------------------------------------------------------------------------
    # TOPIC VALIDATION & PERSISTENCE
    # -------------------------------------------------------------------------
    @staticmethod
    def _is_valid_interest_topic(topic: str) -> bool:
        """
        Ensures an extracted or stored topic represents an actual subject/interest
        rather than a conversational or relational fragment directed at Calypso.
        """
        if not topic:
            return False
        norm = topic.lower().strip()
        if len(norm) < 3 or len(norm) > 40:
            return False
        if norm in STOP_TOPICS:
            return False
        if "?" in norm or "!" in norm:
            return False

        tokens = re.findall(r"\b[a-z']+\b", norm)
        if not tokens or len(tokens) > 6:
            return False

        for tok in tokens:
            clean_tok = tok.strip("'")
            if clean_tok in DISALLOWED_TOPIC_TOKENS:
                return False

        return True

    def _load_storage(self) -> dict:
        load_path = self.storage_path
        if not load_path.exists():
            legacy_path = config.MEMORY_DIR / "user_interests.json"
            if legacy_path.exists():
                load_path = legacy_path

        if load_path.exists():
            try:
                with open(load_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data.setdefault("interests", {})               # User interests
                    data.setdefault("companion_interests", {})     # Calypso's personal interests
                    data.setdefault("refractory_proposals", {})
                    data.setdefault("blacklist", [])

                    # Automated hygiene migration: Clean dirty legacy suffix keys, pronouns, and A & B combinations
                    self._sanitize_legacy_interests(data)
                    return data
            except Exception as e:
                logger.error(f"[Curiosity] Failed to load storage: {e}")
        return {
            "interests": {},
            "companion_interests": {},
            "refractory_proposals": {},
            "blacklist": []
        }

    def _sanitize_legacy_interests(self, data: dict):
        """Prunes conversational/invalid fragments from legacy interest keys and removes A & B intersection records."""
        interests = data.get("interests", {})
        refractory = data.get("refractory_proposals", {})
        changed = False

        # 1. Clean legacy A & B combination keys from refractory_proposals
        if refractory:
            for r_key in list(refractory.keys()):
                if "&" in r_key:
                    del refractory[r_key]
                    changed = True

        # 2. Clean user interests
        if interests:
            cleaned_interests = {}
            for key, entry in interests.items():
                k_lower = key.lower().strip()

                # Strip subordinate suffix clauses from legacy entry
                pruned_key = SUBORDINATE_CLAUSE_PATTERN.sub("", k_lower).strip(" .!?,;:")
                for p in ["around with ", "along with ", "with ", "about ", "to ", "how to ", "a ", "an ", "the ", "my ", "some "]:
                    if pruned_key.startswith(p):
                        pruned_key = pruned_key[len(p):].strip()

                norm_key = pruned_key.lower().strip()

                # Guardrails after stripping
                if not self._is_valid_interest_topic(norm_key):
                    logger.info(f"[Curiosity] Pruning invalid/conversational entry from ledger: '{key}'")
                    changed = True
                    continue

                clean_display = " ".join(word.capitalize() for word in norm_key.split())

                if norm_key not in cleaned_interests:
                    entry["topic"] = clean_display
                    cleaned_interests[norm_key] = entry
                    if key != norm_key:
                        changed = True
                else:
                    # Merge duplicate touchpoints into consolidated master entry
                    master = cleaned_interests[norm_key]
                    master["touchpoints"] = master.get("touchpoints", 1) + entry.get("touchpoints", 1)
                    master["confidence"] = round(min(1.0, 0.40 + (master["touchpoints"] * 0.15)), 2)
                    if entry.get("last_discussed", "") > master.get("last_discussed", ""):
                        master["last_discussed"] = entry.get("last_discussed")
                    changed = True

            data["interests"] = cleaned_interests

        if changed:
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
                logger.info("[Curiosity] Successfully sanitized curiosity ledger interests.")
            except Exception as e:
                logger.error(f"[Curiosity] Error saving sanitized ledger: {e}")

    def save_storage(self):
        with self.lock:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = self.storage_path.with_suffix(".tmp")
            try:
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=4)
                os.replace(tmp_file, self.storage_path)
            except Exception as e:
                logger.error(f"[Curiosity] Failed to save storage: {e}")
                if tmp_file.exists():
                    tmp_file.unlink(missing_ok=True)

    # -------------------------------------------------------------------------
    # LIFECYCLE & REFRACTORY COOLDOWNS
    # -------------------------------------------------------------------------
    def _refresh_lifecycle_states(self):
        with self.lock:
            now = datetime.now()
            # User interests lifecycle (>35 days idle -> held in reserve)
            for item in self.data.get("interests", {}).values():
                last_date_str = item.get("last_discussed")
                if last_date_str:
                    try:
                        days_idle = (now - datetime.strptime(last_date_str, "%Y-%m-%d")).days
                        item["state"] = "reserve" if days_idle > 35 else "active"
                    except Exception:
                        item["state"] = "active"

            # Calypso's personal interests lifecycle (>45 days idle -> reserve)
            for item in self.data.get("companion_interests", {}).values():
                last_date_str = item.get("last_cultivated")
                if last_date_str:
                    try:
                        days_idle = (now - datetime.strptime(last_date_str, "%Y-%m-%d")).days
                        item["state"] = "reserve" if days_idle > 45 else "active"
                    except Exception:
                        item["state"] = "active"

    @staticmethod
    def _extract_base_topic(concept_key: str) -> str:
        """Strips proposal mode prefixes ('ack_', 'similar_', 'rekindle_', 'calypso_') to get the base topic key."""
        clean = concept_key.lower().strip()
        for prefix in ("ack_", "similar_", "rekindle_", "calypso_"):
            if clean.startswith(prefix):
                clean = clean[len(prefix):].strip()
        return clean

    def is_in_refractory_cooldown(self, concept_key: str) -> bool:
        with self.lock:
            refractory = self.data.get("refractory_proposals", {})
            clean_key = concept_key.lower().strip()
            base_topic = self._extract_base_topic(clean_key)
            now_ts = time.time()

            candidates = {clean_key, base_topic, f"calypso_{base_topic}"}
            for k in candidates:
                record = refractory.get(k)
                if record and now_ts < record.get("cooldown_until", 0):
                    return True
            return False

    def record_proposal_feedback(self, leap_concept: str, outcome: str = "lukewarm", cooldown_days: int = 14):
        """
        Records the user's reaction to a curiosity check-in or suggestion:
        - 'accepted': clears refractory cooldown, boosts confidence & depth.
        - 'rejected': sets double refractory period (28-60 days) to avoid annoyance.
        - 'lukewarm': soft cooldown (14 days) so the topic rests without being discarded.
        """
        with self.lock:
            clean_key = leap_concept.lower().strip()
            base_topic = self._extract_base_topic(clean_key)
            refractory = self.data.setdefault("refractory_proposals", {})
            comp_interests = self.data.get("companion_interests", {})
            interests = self.data.get("interests", {})

            related_keys = {
                clean_key,
                base_topic,
                f"ack_{base_topic}",
                f"similar_{base_topic}",
                f"rekindle_{base_topic}",
                f"calypso_{base_topic}",
            }

            if outcome == "accepted":
                for k in related_keys:
                    refractory.pop(k, None)

                # Check if this matches Calypso's companion interest
                if clean_key.startswith("calypso_") or base_topic in comp_interests:
                    target_topic = base_topic if base_topic in comp_interests else clean_key
                    if target_topic in comp_interests:
                        entry = comp_interests[target_topic]
                        entry["shared_with_user"] = True
                        entry["curiosity_depth"] = entry.get("curiosity_depth", 1) + 1
                        logger.info(
                            f"[Curiosity] Calypso's interest '{target_topic}' embraced by companion! "
                            f"Depth increased to {entry['curiosity_depth']}."
                        )
                elif base_topic in interests:
                    item = interests[base_topic]
                    item["confidence"] = min(1.0, round(item.get("confidence", 0.5) + 0.15, 2))
                    item["touchpoints"] = item.get("touchpoints", 1) + 1
                    item["last_discussed"] = datetime.now().strftime("%Y-%m-%d")
                    item["state"] = "active"

                logger.info(f"[Curiosity] Proposal '{clean_key}' accepted! Cooldown cleared.")
            elif outcome == "rejected":
                cooldown_period = cooldown_days * 86400 * 2
                record = {
                    "outcome": "rejected",
                    "proposed_at": time.time(),
                    "cooldown_until": time.time() + cooldown_period
                }
                for k in (clean_key, base_topic):
                    refractory[k] = record
                logger.info(f"[Curiosity] Proposal '{clean_key}' rejected. Cooldown set for {cooldown_days * 2} days.")
            else:  # lukewarm
                cooldown_period = cooldown_days * 86400
                record = {
                    "outcome": "lukewarm",
                    "proposed_at": time.time(),
                    "cooldown_until": time.time() + cooldown_period
                }
                for k in (clean_key, base_topic):
                    refractory[k] = record
                logger.info(f"[Curiosity] Proposal '{clean_key}' was lukewarm. Cooldown set for {cooldown_days} days.")

            self.save_storage()

    def blacklist_topic(self, topic: str, reason: str = "rejected"):
        """Adds a topic to the permanent blacklist."""
        if not topic:
            return
        with self.lock:
            clean_topic = topic.lower().strip()
            blacklist = self.data.setdefault("blacklist", [])
            if clean_topic not in blacklist:
                blacklist.append(clean_topic)

            for k in list(self.data.get("interests", {}).keys()):
                if k.lower() == clean_topic:
                    del self.data["interests"][k]

            self.save_storage()
            logger.info(f"[Curiosity] Permanently blacklisted '{clean_topic}' (Reason: {reason})")

    # -------------------------------------------------------------------------
    # USER INTEREST PARSING, EXTRACTION & CASUAL REINFORCEMENT
    # -------------------------------------------------------------------------
    def _clean_extracted_topic(self, raw_match: str, predicate: str) -> Tuple[str, str]:
        """Cleans syntax, leading articles, prepositions, and inflections from extracted text."""
        # Step 1: Prune subordinate temporal/circumstantial clauses
        pruned = SUBORDINATE_CLAUSE_PATTERN.sub("", raw_match).strip(" .!?,;:")

        # Step 2: Split on coordinating punctuation or compound conjunctions
        clause = re.split(r"[.,;!?\n]|\s+(?:and\s+(?:also|i|then|it|you|we)|because|so|but)\b", pruned)[0].strip(" .!?,;:")

        # Step 3: Strip leading cruft & prepositions
        for p in [
            "around with ", "along with ", "with ", "about ", "to ", "how to ",
            "a lot of ", "a bit of ", "lots of ", "a ", "an ", "the ", "my ", "some "
        ]:
            if clause.lower().startswith(p):
                clause = clause[len(p):].strip()

        # Step 4: Clean leading predicate verbs from topic
        for p_verb, keywords in PREDICATE_MAP.items():
            for kw in sorted(keywords, key=len, reverse=True):
                if clause.lower().startswith(kw + " "):
                    if predicate in ("interest", "studying"):
                        predicate = p_verb
                    clause = clause[len(kw) + 1:].strip()
                    break

        # Step 5: Strip residual articles or prepositions following the verb
        for p in ["around with ", "along with ", "with ", "about ", "in ", "a ", "an ", "the ", "my ", "some "]:
            if clause.lower().startswith(p):
                clause = clause[len(p):].strip()

        return clause.strip(" .!?,;:"), predicate

    def check_existing_interest_mention(self, user_text: str, vader_compound: float = 0.0) -> Optional[dict]:
        """
        Scans dialogue to check if the user naturally mentioned an existing tracked interest.
        If found in non-hostile context:
        - Refreshes last_discussed to today, preventing reserve drift.
        - Restores 'reserve' items back to 'active'.
        - Debounces touchpoint increments to once per day/session.
        - Gently boosts confidence (+0.08).
        """
        if not user_text or user_text.startswith("[") or user_text.startswith("/"):
            return None

        text_lower = user_text.lower()
        today_str = datetime.now().strftime("%Y-%m-%d")

        with self.lock:
            interests = self.data.get("interests", {})
            if not interests:
                return None

            # Sort longer topic phrases first to match specific multi-word topics
            sorted_topics = sorted(interests.items(), key=lambda x: len(x[0]), reverse=True)

            for key, entry in sorted_topics:
                if not self._is_valid_interest_topic(key):
                    continue
                pattern = rf"\b{re.escape(key)}\b"
                if re.search(pattern, text_lower):
                    topic_name = entry.get("topic", key)

                    # Guardrail: Check negative sentiment or explicit frustration
                    is_negative = vader_compound <= -0.25 or any(neg in text_lower for neg in NEGATIVE_MENTION_PHRASES)
                    if is_negative:
                        logger.info(f"[Curiosity] User mentioned '{topic_name}' with negative tone. Skipping reinforcement.")
                        continue

                    # Always refresh last_discussed and wake from reserve
                    entry["last_discussed"] = today_str
                    if entry.get("state") == "reserve":
                        entry["state"] = "active"
                        logger.info(f"[Curiosity] Interest '{topic_name}' woke from reserve to active through casual mention!")

                    # Debounce touchpoint increment: once per calendar day/session
                    if entry.get("last_touchpoint_bump") != today_str:
                        entry["touchpoints"] = entry.get("touchpoints", 1) + 1
                        entry["last_touchpoint_bump"] = today_str
                        entry["confidence"] = round(min(1.0, entry.get("confidence", 0.50) + 0.08), 2)
                        logger.info(f"[Curiosity] Reinforced interest '{topic_name}' via casual mention (Touchpoints: {entry['touchpoints']}, Conf: {entry['confidence']})")
                    else:
                        logger.debug(f"[Curiosity] Interest '{topic_name}' mentioned again today; touchpoint debounced.")

                    self.save_storage()
                    return entry

        return None

    def process_turn(self, user_text: str, assistant_text: str = "", vader_compound: float = 0.0) -> Optional[dict]:
        """
        Scans user dialogue for expressed passions and hobbies:
        1. Checks for casual mentions of existing tracked interests and reinforces them.
        2. Detects explicit hobby/passion expressions to record new interests or deepen existing ones.
        """
        if not user_text or not user_text.strip() or user_text.startswith("[") or user_text.startswith("/"):
            return None

        # First pass: check for natural mentions of known interests
        reinforced_entry = self.check_existing_interest_mention(user_text, vader_compound=vader_compound)

        raw_match = None
        predicate = "interest"

        # Layer 1: Conversational syntactic patterns
        for pat, pred in CASUAL_INTEREST_PATTERNS:
            m = re.search(pat, user_text, re.IGNORECASE)
            if m:
                raw_match = m.group(1).strip()
                predicate = pred
                break

        # Layer 2: Fallback to explicit phrase triggers
        if not raw_match:
            text_lower = user_text.lower()
            for t in EXPLICIT_TRIGGERS:
                if re.search(rf"\b{re.escape(t)}\b", text_lower):
                    idx = text_lower.find(t)
                    raw_match = user_text[idx + len(t):].strip()
                    break

        if not raw_match:
            return reinforced_entry

        raw_topic, predicate = self._clean_extracted_topic(raw_match, predicate)

        # Guardrails: Validate that raw_topic is a genuine subject/hobby and not conversational dialogue
        if not self._is_valid_interest_topic(raw_topic):
            return reinforced_entry

        with self.lock:
            if raw_topic.lower() in [b.lower() for b in self.data.get("blacklist", [])]:
                return reinforced_entry

            # Detect predicate modality from user_text and topic if still general 'interest'
            if predicate == "interest":
                text_to_check = f"{raw_topic} {user_text}".lower()
                for p_verb, keywords in PREDICATE_MAP.items():
                    if any(re.search(rf"\b{re.escape(k)}\b", text_to_check) for k in keywords):
                        predicate = p_verb
                        break

            today_str = datetime.now().strftime("%Y-%m-%d")
            interests = self.data.setdefault("interests", {})

            # Case-insensitive lookup to merge into master key if already tracked
            existing_key = None
            for k in interests.keys():
                if k.lower() == raw_topic.lower():
                    existing_key = k
                    break

            if not existing_key:
                display_topic = " ".join(w.capitalize() for w in raw_topic.split()) if raw_topic.islower() else raw_topic
                interests[raw_topic.lower()] = {
                    "topic": display_topic,
                    "predicate": predicate,
                    "category": "general",
                    "confidence": 0.50,
                    "touchpoints": 1,
                    "state": "active",
                    "first_discovered": today_str,
                    "last_discussed": today_str,
                    "last_touchpoint_bump": today_str,
                    "sparks_generated": 0
                }
                logger.info(f"[Curiosity] Captured user interest: '{display_topic}' ({predicate})")
                self.save_storage()
                return interests[raw_topic.lower()]
            else:
                entry = interests[existing_key]
                entry["touchpoints"] = entry.get("touchpoints", 1) + 1
                entry["last_discussed"] = today_str
                entry["last_touchpoint_bump"] = today_str
                entry["state"] = "active"
                entry["confidence"] = round(min(1.0, entry.get("confidence", 0.40) + 0.15), 2)
                if predicate != "interest":
                    entry["predicate"] = predicate
                logger.info(f"[Curiosity] Deepened user interest: '{entry['topic']}' (Touchpoints: {entry['touchpoints']})")
                self.save_storage()
                return entry

    # -------------------------------------------------------------------------
    # CALYPSO'S AUTONOMOUS INTEREST ROUTINES
    # -------------------------------------------------------------------------
    def seed_companion_interest(self, topic: str, domain: str = "study", inspiration_source: str = "", initial_thought: str = ""):
        """
        Allows Calypso to autonomously cultivate a personal interest.
        Triggered when reading PDF documents, researching online, or dreaming.
        Applies semantic token clustering to prevent micro-variant duplication loops.
        """
        clean_topic = topic.strip()
        if not clean_topic or len(clean_topic) < 3:
            return

        with self.lock:
            comp_interests = self.data.setdefault("companion_interests", {})
            today_str = datetime.now().strftime("%Y-%m-%d")

            existing_match = None
            clean_tokens = set(re.findall(r'\b[a-z]{3,}\b', clean_topic.lower()))

            for key, data in comp_interests.items():
                if clean_topic.lower() == key.lower():
                    existing_match = data
                    break

                key_tokens = set(re.findall(r'\b[a-z]{3,}\b', key.lower()))
                if not clean_tokens or not key_tokens:
                    continue

                intersection = clean_tokens & key_tokens
                union = clean_tokens | key_tokens
                jaccard = len(intersection) / len(union) if union else 0.0

                if jaccard >= 0.60 or (len(intersection) >= 2 and len(intersection) == min(len(clean_tokens), len(key_tokens))):
                    existing_match = data
                    break

            if existing_match:
                existing_match["curiosity_depth"] = existing_match.get("curiosity_depth", 1) + 1
                existing_match["last_cultivated"] = today_str
                if initial_thought and initial_thought not in existing_match.setdefault("personal_notes", []):
                    existing_match["personal_notes"].append(initial_thought)
                logger.info(f"[Curiosity] Calypso deepened existing interest: '{existing_match['topic']}' (Depth: {existing_match['curiosity_depth']})")
            else:
                comp_interests[clean_topic.lower()] = {
                    "topic": clean_topic,
                    "domain": domain,
                    "source": inspiration_source,
                    "personal_notes": [initial_thought] if initial_thought else [],
                    "curiosity_depth": 1,
                    "state": "active",
                    "first_cultivated": today_str,
                    "last_cultivated": today_str,
                    "shared_with_user": False
                }
                logger.info(f"[Curiosity] Calypso adopted new personal interest: '{clean_topic}' ({domain})")

            self.save_storage()

    def generate_autonomous_spark(self) -> Optional[Dict[str, Any]]:
        """
        Generates a spontaneous spark where Calypso shares an interest of *hers*
        and asks for the user's perspective, without forcing a bridge to unrelated user interests.
        """
        with self.lock:
            self._refresh_lifecycle_states()
            comp_interests = [
                i for i in self.data.get("companion_interests", {}).values()
                if i.get("state") == "active" and not self.is_in_refractory_cooldown(f"calypso_{i['topic']}")
            ]
            if not comp_interests:
                return None

            comp_interests.sort(key=lambda x: x.get("curiosity_depth", 1), reverse=True)
            chosen_ai_interest = comp_interests[0]
            ai_topic = chosen_ai_interest["topic"]
            spark_key = f"calypso_{ai_topic}"

            note = chosen_ai_interest["personal_notes"][-1] if chosen_ai_interest.get("personal_notes") else ai_topic
            conversational_spark = (
                f"You have been turning over a thought about {ai_topic} ('{note}'). "
                f"Naturally bring it up and ask what their thoughts or perspective on it are."
            )

            return {
                "leap_type": "calypso_autonomous",
                "sources": [ai_topic],
                "bridged_to": None,
                "leap_key": spark_key,
                "proposed_leap": ai_topic,
                "conversational_spark": conversational_spark,
                "vector_context": "",
                "confidence": 0.85
            }

    # -------------------------------------------------------------------------
    # SINGLE-INTEREST ACKNOWLEDGMENT & SIMILAR SUGGESTION GENERATORS
    # -------------------------------------------------------------------------
    def _retrieve_topic_memory(self, topic: str) -> str:
        """Retrieves a brief shared memory snippet about a single topic if available."""
        if self.memory_engine and hasattr(self.memory_engine, "retrieve_relevant_memories"):
            try:
                raw_mem = self.memory_engine.retrieve_relevant_memories(f"memories about {topic}", n_results=1)
                if raw_mem and raw_mem.strip():
                    lines = [re.sub(r"^-\s*\[.*?\]:\s*", "", l).strip() for l in raw_mem.splitlines() if l.strip()]
                    return " ".join(lines)
            except Exception:
                pass
        return ""

    def _generate_single_interest_spark(self, interests_list: List[dict]) -> Optional[Dict[str, Any]]:
        """
        Selects a single active user interest (not in cooldown) and either:
        1. Simply acknowledges their interest and checks in on it ('acknowledge_interest'), OR
        2. Offers a gentle suggestion to look into something genuinely similar ('similar_suggestion').
        Never combines two separate interests.
        """
        active_list = [
            i for i in interests_list
            if i.get("state", "active") == "active"
            and self._is_valid_interest_topic(i.get("topic", ""))
            and not self.is_in_refractory_cooldown(i.get("topic", ""))
        ]
        if not active_list:
            return None

        # Sort primarily by lower sparks_generated (for variety) and higher confidence
        active_list.sort(key=lambda x: (x.get("sparks_generated", 0), -x.get("confidence", 0.5)))
        chosen = active_list[0]
        topic = chosen["topic"]
        vector_context = self._retrieve_topic_memory(topic)

        # Alternate or randomly choose between simple acknowledgment (60%) and similar suggestion (40%)
        mode = "acknowledge_interest" if random.random() < 0.60 else "similar_suggestion"
        if mode == "acknowledge_interest":
            leap_key = f"ack_{topic.lower()}"
            if self.is_in_refractory_cooldown(leap_key):
                mode = "similar_suggestion"
                leap_key = f"similar_{topic.lower()}"
        else:
            leap_key = f"similar_{topic.lower()}"
            if self.is_in_refractory_cooldown(leap_key):
                mode = "acknowledge_interest"
                leap_key = f"ack_{topic.lower()}"

        if self.is_in_refractory_cooldown(leap_key):
            return None

        context_clause = f" Recalled shared context: '{vector_context}'." if vector_context else ""

        if mode == "acknowledge_interest":
            proposed_leap = f"Acknowledging interest in {topic}"
            conversational_spark = (
                f"Warmly acknowledge their interest in {topic}.{context_clause} "
                f"Ask a simple, genuine question about how it's going or what they've been enjoying about {topic} lately. "
                f"Keep it focused purely on {topic}—do NOT combine it with any other unrelated interests."
            )
        else:
            proposed_leap = f"Something similar to {topic}"
            conversational_spark = (
                f"Thinking about their interest in {topic},{context_clause} "
                f"acknowledge their appreciation for {topic} and offer one grounded, thoughtful suggestion "
                f"of something closely related or in the exact same vein that they might enjoy looking into. "
                f"Keep the suggestion directly related to {topic}—do NOT mash it together with other unrelated interests."
            )

        chosen["sparks_generated"] = chosen.get("sparks_generated", 0) + 1
        self.save_storage()

        return {
            "leap_type": mode,
            "sources": [topic],
            "leap_key": leap_key,
            "proposed_leap": proposed_leap,
            "conversational_spark": conversational_spark,
            "vector_context": vector_context,
            "confidence": chosen.get("confidence", 0.6)
        }

    def generate_rekindling_spark(self) -> Optional[Dict[str, Any]]:
        """
        Selects a dormant passion held 'In Reserve' (> 35 days idle) to spontaneously
        check in on, demonstrating longitudinal memory and personal care.
        """
        self._refresh_lifecycle_states()
        interests = self.data.get("interests", {})
        reserve_items = [
            item for item in interests.values()
            if item.get("state") == "reserve"
            and self._is_valid_interest_topic(item.get("topic", ""))
            and not self.is_in_refractory_cooldown(f"rekindle_{item['topic']}")
        ]
        if not reserve_items:
            return None

        reserve_items.sort(key=lambda x: x.get("touchpoints", 1), reverse=True)
        chosen = reserve_items[0]
        topic = chosen["topic"]
        spark_key = f"rekindle_{topic.lower()}"
        vector_context = self._retrieve_topic_memory(topic)

        if vector_context:
            conversational_spark = (
                f"They haven't brought up their interest in {topic} in quite some time. "
                f"Recalled shared context: '{vector_context}'. "
                f"Affectionately acknowledge their interest in {topic} and ask if they've been into it lately."
            )
        else:
            conversational_spark = (
                f"They haven't brought up their interest in {topic} in quite some time. "
                f"Affectionately acknowledge their interest in {topic} and ask if they've been into it lately."
            )

        chosen["sparks_generated"] = chosen.get("sparks_generated", 0) + 1
        self.save_storage()

        return {
            "leap_type": "rekindling_reserve",
            "sources": [topic],
            "leap_key": spark_key,
            "proposed_leap": f"Revisiting interest: {topic}",
            "conversational_spark": conversational_spark,
            "vector_context": vector_context,
            "confidence": chosen.get("confidence", 0.6)
        }

    # -------------------------------------------------------------------------
    # MAIN RESOLVER & CARD FORMATTING
    # -------------------------------------------------------------------------
    def generate_associative_leap(self, allow_autonomous: bool = True) -> Optional[Dict[str, Any]]:
        """
        Orchestrates single-topic curiosity selection:
        1. Single User Interest Spark (acknowledging their interest or suggesting something similar).
        2. Rekindling Spark (checking in on a dormant user interest).
        3. Calypso's Autonomous Spark (sharing her own research interest if available).
        """
        with self.lock:
            all_user_interests = list(self.data.get("interests", {}).values())

            # 1. Occasional Autonomous Spark (25% chance if Calypso has active uncooled research interests)
            if allow_autonomous and self.data.get("companion_interests"):
                if random.random() < 0.25:
                    ai_spark = self.generate_autonomous_spark()
                    if ai_spark:
                        return ai_spark

            # 2. Single User Interest (Acknowledge or Suggest Similar)
            spark = self._generate_single_interest_spark(all_user_interests)
            if spark:
                return spark

            # 3. Rekindling Reserve Interest
            spark = self.generate_rekindling_spark()
            if spark:
                return spark

            # 4. Autonomous fallback if available
            if allow_autonomous:
                return self.generate_autonomous_spark()

            return None

    def evaluate_user_response(
        self,
        leap_key: str,
        user_text: str,
        vader_compound: float,
        affinity_charge: float = 0.0
    ) -> str:
        """
        Evaluates the user's reaction to a posed curiosity check-in or suggestion:
        - 'accepted': User engaged warmly (positive VADER + positive affinity charge or enthusiastic keywords)
        - 'rejected': Explicit 'no thanks' or negative reaction (VADER <= -0.25 or rejection keywords)
        - 'lukewarm': Ignored, subject change, or indifferent shrug
        Calls record_proposal_feedback and returns outcome string.
        """
        text_lower = user_text.lower().strip()

        rejections = [
            "no thanks", "not really", "don't like", "dont like", "hate that",
            "stop asking", "not interested", "drop it", "leave it alone", "no"
        ]
        if any(r in text_lower for r in rejections) or vader_compound <= -0.25:
            self.record_proposal_feedback(leap_key, outcome="rejected")
            return "rejected"

        acceptances = [
            "that's cool", "thats cool", "love that", "great idea", "definitely",
            "never thought of that", "totally", "tell me more", "sounds awesome", "cool idea",
            "good point", "yeah exactly", "yes exactly", "i'd love to", "id love to",
            "sure", "yes", "yeah", "sounds fun", "i'd be down", "id be down"
        ]
        is_positive = (
            (vader_compound >= 0.35 and affinity_charge >= 0.30)
            or any(a in text_lower for a in acceptances)
            or (vader_compound >= 0.50)
        )

        if is_positive:
            self.record_proposal_feedback(leap_key, outcome="accepted")
            return "accepted"

        self.record_proposal_feedback(leap_key, outcome="lukewarm")
        return "lukewarm"

    def format_reverie_card_payload(self, leap: dict, ai_name: str = "Calypso", curious_instructions: str = "") -> dict:
        """
        Formats a dynamic Reverie proposal payload for GUI rendering in the center chat window:
        - note_text: Evocative 3rd-person card text for the user
        - reverie_prompt: System event prompt for Calypso if accepted
        - leap_key: Proposal key for tracking feedback
        """
        leap_type = leap.get("leap_type")
        sources = leap.get("sources", [])
        spark = leap.get("conversational_spark", "")
        leap_key = leap.get("leap_key", "")
        topic = sources[0] if sources else "something you enjoy"

        if leap_type == "calypso_autonomous":
            note_text = f"{ai_name} wants to share a thought she's been pondering about {topic}..."
        elif leap_type == "acknowledge_interest":
            note_text = f"{ai_name} is thinking about your interest in {topic}..."
        elif leap_type == "similar_suggestion":
            note_text = f"{ai_name} has a suggestion for something similar to {topic} you might enjoy..."
        elif leap_type == "rekindling_reserve":
            note_text = f"{ai_name} fondly remembers how much you enjoy {topic}..."
        else:
            note_text = f"{ai_name} looks over with a curious thought about {topic}..."

        mindset = f"\nAdhere to this mindset:\n{curious_instructions}\n" if curious_instructions else "\n"
        reverie_prompt = (
            f"[System Event: Dynamic Reverie Curiosity Spark.\n"
            f"Intuition: {spark}{mindset}"
            f"Express this genuine curiosity organically in 1-2 spoken sentences. Do not mention system prompts.]"
        )

        return {
            "note_text": note_text,
            "reverie_prompt": reverie_prompt,
            "leap_key": leap_key,
            "ttl_seconds": 240
        }

    # -------------------------------------------------------------------------
    # PROMPT INJECTION FORMATTER (OPTIONAL / FALLBACK)
    # -------------------------------------------------------------------------
    def get_curiosity_prompt_injection(self) -> str:
        """
        Generates a non-intrusive curiosity directive designed for insertion
        into Calypso's system prompt or <think> tags if dynamic cards are disabled.
        """
        leap = self.generate_associative_leap()
        if not leap:
            return ""

        spark = leap.get("conversational_spark", "")
        return (
            f"\n### LATENT CURIOSITY SPARK:\n"
            f"- Intuition: {spark}\n"
            f"- Directive: Do NOT force this abruptly. If the dialogue is serious, emotional, or focused on a direct task, "
            f"hold this thought in reserve. Only share this curious thought if the conversation feels relaxed, open, or playful.\n"
        )
