# modules/emotion/knowledgegraph.py
#The Knowledge Graph Engine extracts enduring factual relationships, identity traits, and user preferences from dialogue into structured subject-predicate-object triples stored #in a local SQLite database. It performs multi-hop recursive queries across extracted entities and n-grams to uncover non-obvious relational connections that complement semantic #vector memory. Operative turns are indexed asynchronously via an LLM background worker, providing structured contextual recall into prompts without stalling the conversational #pipeline.
import json
import logging
import queue
import re
import sqlite3
import threading
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import contextlib

from modules.config import config
from modules.gpu_lock import gpu_vram_lock

logger = logging.getLogger("EmotionEngine.KnowledgeGraph")

STOPWORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's",
    "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other",
    "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't",
    "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves", "yeah", "okay", "hello", "hey", "just", "like"
}

# Core participant hub nodes
CORE_ENTITIES = {"user", "calypso"}


class KnowledgeGraphEngine:
    def __init__(self, db_path: Optional[Path] = None):
        target_path = Path(db_path) if db_path is not None else (config.MEMORY_DIR / "knowledge_graph.db")
        self.set_db_path(target_path)

        # Dedicated single-worker task queue to prevent LLM contention
        self._indexing_queue: queue.Queue = queue.Queue()
        self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self._worker_thread.start()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @db_path.setter
    def db_path(self, new_path: Path):
        self.set_db_path(new_path)

    def set_db_path(self, new_path: Path):
        self._db_path = Path(new_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self._db_path), timeout=25.0)
        conn.execute("PRAGMA synchronous=NORMAL;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS triples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(subject, predicate, object) ON CONFLICT REPLACE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sub ON triples(subject)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_obj ON triples(object)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pred ON triples(predicate)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sub_obj ON triples(subject, object)")

    def add_triple(self, sub: Any, pred: Any, obj: Any) -> bool:
        """Inserts or replaces a single normalized triple."""
        s = str(sub).strip().lower()
        p = str(pred).strip().lower()
        o = str(obj).strip().lower()

        if not s or not p or not o or s == o or len(s) < 2 or len(o) < 2:
            return False

        try:
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO triples (subject, predicate, object, timestamp) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (s, p, o)
                )
            logger.debug(f"[KnowledgeGraph] Added: ({s}) -[{p}]-> ({o})")
            return True
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
                logger.warning(f"[KnowledgeGraph] Table 'triples' missing in add_triple, reinitializing database: {e}")
                self._init_db()
                try:
                    with self._get_connection() as conn:
                        conn.execute(
                            "INSERT INTO triples (subject, predicate, object, timestamp) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                            (s, p, o)
                        )
                    logger.debug(f"[KnowledgeGraph] Added: ({s}) -[{p}]-> ({o})")
                    return True
                except Exception as retry_err:
                    logger.error(f"[KnowledgeGraph] Failed to add triple after re-init: {retry_err}")
                    return False
            logger.error(f"[KnowledgeGraph] Failed to add triple: {e}")
            return False
        except Exception as e:
            logger.error(f"[KnowledgeGraph] Failed to add triple: {e}")
            return False

    def add_triples(self, triples: List[Dict[str, Any]]) -> int:
        """Inserts multiple triples within a single database transaction."""
        valid_rows = []
        for t in triples:
            if not isinstance(t, dict):
                continue
            s = str(t.get("sub", "")).strip().lower()
            p = str(t.get("pred", "")).strip().lower()
            o = str(t.get("obj", "")).strip().lower()

            if s and p and o and s != o and len(s) >= 2 and len(o) >= 2:
                valid_rows.append((s, p, o))

        if not valid_rows:
            return 0

        try:
            with self._get_connection() as conn:
                conn.executemany(
                    "INSERT INTO triples (subject, predicate, object, timestamp) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    valid_rows
                )
            logger.debug(f"[KnowledgeGraph] Batched inserted {len(valid_rows)} triples.")
            return len(valid_rows)
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
                logger.warning(f"[KnowledgeGraph] Table 'triples' missing in add_triples, reinitializing database: {e}")
                self._init_db()
                try:
                    with self._get_connection() as conn:
                        conn.executemany(
                            "INSERT INTO triples (subject, predicate, object, timestamp) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                            valid_rows
                        )
                    logger.debug(f"[KnowledgeGraph] Batched inserted {len(valid_rows)} triples.")
                    return len(valid_rows)
                except Exception as retry_err:
                    logger.error(f"[KnowledgeGraph] Failed to batch add triples after re-init: {retry_err}")
                    return 0
            logger.error(f"[KnowledgeGraph] Failed to batch add triples: {e}")
            return 0
        except Exception as e:
            logger.error(f"[KnowledgeGraph] Failed to batch add triples: {e}")
            return 0

    def extract_candidate_entities(self, text: str) -> List[str]:
        """Extracts 1-word tokens as well as 2-word and 3-word n-grams to catch multi-word entities."""
        clean_text = re.sub(r'[^\w\s-]', ' ', text.lower())
        tokens = [tok.strip() for tok in clean_text.split() if tok.strip()]

        candidates: List[str] = []

        # 1. Single tokens
        for tok in tokens:
            if len(tok) >= 3 and tok not in STOPWORDS:
                candidates.append(tok)

        # 2. Bi-grams & Tri-grams for multi-word concepts
        for i in range(len(tokens) - 1):
            if tokens[i] not in STOPWORDS or tokens[i + 1] not in STOPWORDS:
                candidates.append(f"{tokens[i]} {tokens[i + 1]}")

        for i in range(len(tokens) - 2):
            candidates.append(f"{tokens[i]} {tokens[i + 1]} {tokens[i + 2]}")

        # Retain reference to core participants last (to avoid prioritizing them)
        if any(w in tokens for w in ["you", "calypso"]):
            candidates.append("calypso")
        if any(w in tokens for w in ["i", "me", "my"]):
            candidates.append("user")

        return list(dict.fromkeys(candidates))

    def multi_hop_search(self, start_entity: str, max_hops: int = 2, limit: int = 4) -> List[str]:
        """Traverses the graph outward up to N hops, prioritizing recent relations."""
        entity = start_entity.strip().lower()
        if not entity:
            return []

        query = """
        WITH RECURSIVE graph_hops(curr_node, s, p, o, depth, path, latest_ts) AS (
            SELECT
                CASE WHEN subject = ? THEN object ELSE subject END AS curr_node,
                subject, predicate, object, 1,
                subject || ' -[' || predicate || ']-> ' || object AS path,
                timestamp
            FROM triples
            WHERE subject = ? OR object = ?

            UNION ALL

            SELECT
                CASE WHEN t.subject = gh.curr_node THEN t.object ELSE t.subject END,
                t.subject, t.predicate, t.object,
                gh.depth + 1,
                gh.path || ' ──► ' || t.subject || ' -[' || t.predicate || ']-> ' || t.object,
                t.timestamp
            FROM triples t
            JOIN graph_hops gh ON (t.subject = gh.curr_node OR t.object = gh.curr_node)
            WHERE gh.depth < ?
              AND INSTR(gh.path, t.subject || ' -[' || t.predicate || ']-> ' || t.object) = 0
        )
        SELECT DISTINCT path FROM graph_hops 
        ORDER BY latest_ts DESC
        LIMIT ?;
        """
        try:
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute(query, (entity, entity, entity, max_hops, limit))
                return [row[0] for row in cur.fetchall()]
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
                logger.warning(f"[KnowledgeGraph] Table 'triples' missing in multi_hop_search, reinitializing database: {e}")
                self._init_db()
                try:
                    with self._get_connection() as conn:
                        cur = conn.cursor()
                        cur.execute(query, (entity, entity, entity, max_hops, limit))
                        return [row[0] for row in cur.fetchall()]
                except Exception as retry_err:
                    logger.error(f"[KnowledgeGraph] Multi-hop query error on '{entity}' after re-init: {retry_err}")
                    return []
            logger.error(f"[KnowledgeGraph] Multi-hop query error on '{entity}': {e}")
            return []
        except Exception as e:
            logger.error(f"[KnowledgeGraph] Multi-hop query error on '{entity}': {e}")
            return []

    def query_relevant_knowledge(self, query_text: str, max_hops: int = 2, max_results: int = 4) -> List[str]:
        """Discovers relational paths, prioritizing specific domain entities over universal hub nodes."""
        entities = self.extract_candidate_entities(query_text)
        if not entities:
            return []

        # Partition entities into specific terms vs universal hub nodes
        specific_entities = [e for e in entities if e not in CORE_ENTITIES]
        hub_entities = [e for e in entities if e in CORE_ENTITIES]

        all_paths = []

        # 1. Search specific concepts first
        for ent in specific_entities:
            paths = self.multi_hop_search(ent, max_hops=max_hops, limit=2)
            all_paths.extend(paths)
            if len(all_paths) >= max_results:
                break

        # 2. Only search hub nodes ('user', 'calypso') if specific terms yielded insufficient context
        if len(all_paths) < max_results:
            remaining = max_results - len(all_paths)
            for ent in hub_entities:
                paths = self.multi_hop_search(ent, max_hops=1, limit=remaining)
                all_paths.extend(paths)

        unique_paths = list(dict.fromkeys(all_paths))
        return unique_paths[:max_results]

    def _query_ollama(self, prompt: str, temperature: float = 0.1, num_predict: int = 220) -> str:
        base_url = str(config.OLLAMA_URL).rstrip("/")
        chat_url = base_url if base_url.endswith("/api/chat") else f"{base_url}/api/chat"

        payload = {
            "model": config.MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": temperature,
                "num_predict": num_predict
            }
        }

        req = urllib.request.Request(
            chat_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        try:
            with gpu_vram_lock:
                with urllib.request.urlopen(req, timeout=35) as response:
                    result = json.loads(response.read().decode("utf-8"))
                    return result.get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.error(f"[KnowledgeGraph] Ollama extraction request failed: {e}")
            return ""

    def extract_triples_from_dialogue(self, user_text: str, assistant_text: str = "") -> List[Dict[str, str]]:
        """Extracts factual triples from conversation turns with robust format stripping."""
        prompt = (
            "[TASK: KNOWLEDGE GRAPH TRIPLE EXTRACTION]\n"
            "Extract enduring factual truths, user preferences, identity traits, relationships, or commitments "
            "from the conversation below as subject-predicate-object triples.\n\n"
            "Rules:\n"
            "- Normalize the human participant to 'user' and the AI to 'calypso'.\n"
            "- Subject and Object should be concise concepts or entities (1 to 4 words).\n"
            "- Predicate must be an active relation (e.g., 'likes', 'works_on', 'fears', 'lives_in', 'created').\n"
            "- Output JSON ONLY: A root array of objects with keys: 'sub', 'pred', 'obj'. Example: [{\"sub\":\"user\",\"pred\":\"likes\",\"obj\":\"tea\"}].\n"
            "- If no lasting facts are present, output [].\n\n"
            f"User: \"{user_text}\"\n"
            + (f"Calypso: \"{assistant_text}\"\n\n" if assistant_text else "\n") +
            "JSON Response:"
        )

        raw_output = self._query_ollama(prompt)
        if not raw_output:
            return []

        # Strip any <think> blocks emitted by reasoning models
        cleaned = re.sub(r'<think>.*?</think>', '', raw_output, flags=re.DOTALL).strip()

        # Handle models returning either a raw JSON list or a JSON object wrapper
        match = re.search(r'\[.*\]', cleaned, re.DOTALL)
        if match:
            try:
                triples = json.loads(match.group(0))
                if isinstance(triples, list):
                    return triples
            except json.JSONDecodeError:
                pass

        # Fallback check for wrapper objects like {"triples": [...]}
        try:
            wrapped = json.loads(cleaned)
            if isinstance(wrapped, dict):
                for val in wrapped.values():
                    if isinstance(val, list):
                        return val
        except json.JSONDecodeError:
            pass

        logger.debug(f"[KnowledgeGraph] Could not extract valid JSON array: {raw_output[:120]}")
        return []

    def _process_queue(self):
        """Sequential daemon worker preventing inference thrashing against Ollama."""
        while True:
            item = self._indexing_queue.get()
            if item is None:
                break
            user_text, assistant_text = item
            try:
                triples = self.extract_triples_from_dialogue(user_text, assistant_text)
                if triples:
                    added = self.add_triples(triples)
                    if added > 0:
                        logger.info(f"[KnowledgeGraph] Indexed {added} new relation(s).")
            except Exception as e:
                logger.error(f"[KnowledgeGraph] Worker error processing dialogue: {e}", exc_info=True)
            finally:
                self._indexing_queue.task_done()

    def extract_and_index_async(self, user_text: str, assistant_text: str = ""):
        """Queues dialogue turns for extraction if they meet the salience threshold."""
        if not user_text or user_text.startswith("[System"):
            return

        words = user_text.strip().split()
        if len(words) < 6:
            return

        low_signal_starters = ("hello", "hey", "good morning", "goodnight", "ok", "cool", "yeah", "thanks")
        if user_text.lower().strip().startswith(low_signal_starters) and len(words) < 10:
            return

        self._indexing_queue.put((user_text, assistant_text))
