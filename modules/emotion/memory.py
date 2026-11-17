# modules/emotion/memory.py

import json
import logging
import os
import time
import uuid
from datetime import date, datetime
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions
from modules.config import config
from modules.settings_manager import settings_manager

logger = logging.getLogger("EmotionEngine.Memory")


class MemoryEngine:
    def __init__(self, character_name: str = None):
        if not character_name:
            character_name = settings_manager.get("ai_name", "Calypso")
        self.character_name = character_name.lower().strip()
        self.display_name = self.character_name.capitalize()
        self.memory_dir = config.MEMORY_DIR
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # File paths
        self.working_session_file = self.memory_dir / f"working_session_{self.character_name}.json"
        self.core_facts_file = self.memory_dir / f"core_facts_{self.character_name}.json"
        self.chroma_dir = self.memory_dir / "chroma_db"

        # 1. Tier 3: Core Facts Setup
        self.core_facts = self._load_or_init_core_facts()

        # 2. Tier 2: ChromaDB Setup
        self.client = chromadb.PersistentClient(path=str(self.chroma_dir))
        self.ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self.collection = self.client.get_or_create_collection(
            name=f"{self.character_name}_episodic_memory",
            embedding_function=self.ef
        )

    # -------------------------------------------------------------------------
    # TEMPORAL ORIENTATION (PHASE 1: THE CLOCK & GAP)
    # -------------------------------------------------------------------------
    @staticmethod
    def _format_time_of_day(hour: int) -> str:
        if 5 <= hour < 9:
            return "Early Morning"
        elif 9 <= hour < 12:
            return "Morning"
        elif 12 <= hour < 14:
            return "Midday"
        elif 14 <= hour < 17:
            return "Afternoon"
        elif 17 <= hour < 21:
            return "Evening"
        elif 21 <= hour < 24:
            return "Late Night"
        else:
            return "After Midnight / Deep Night"

    @staticmethod
    def _format_elapsed_gap(seconds: float) -> str:
        if seconds < 120:
            return "Active ongoing conversation (moments ago)"
        minutes = int(seconds // 60)
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        hours = int(minutes // 60)
        rem_mins = minutes % 60
        if hours < 24:
            if rem_mins > 0:
                return f"{hours} hour{'s' if hours != 1 else ''}, {rem_mins} min ago"
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = int(hours // 24)
        rem_hours = hours % 24
        if rem_hours > 0:
            return f"{days} day{'s' if days != 1 else ''}, {rem_hours} hour{'s' if rem_hours != 1 else ''} ago"
        return f"{days} day{'s' if days != 1 else ''} ago"

    def get_last_interaction_epoch(self, conversation_history: list = None) -> float | None:
        """Finds the most recent interaction timestamp from working history or core_facts."""
        if conversation_history:
            for turn in reversed(conversation_history):
                if isinstance(turn, dict) and turn.get("epoch"):
                    try:
                        return float(turn["epoch"])
                    except (ValueError, TypeError):
                        pass
        saved_epoch = self.core_facts.get("last_interaction_epoch")
        if saved_epoch:
            try:
                return float(saved_epoch)
            except (ValueError, TypeError):
                pass
        return None

    def get_temporal_context_prompt(self, previous_epoch: float | None = None) -> tuple[str, float]:
        """
        Builds the ### TEMPORAL ORIENTATION prompt block and returns
        (prompt_str, gap_seconds) so core.py can also apply limbic reunion effects.
        """
        now = datetime.now()
        now_epoch = time.time()
        tod_label = self._format_time_of_day(now.hour)
        date_str = now.strftime("%A, %B %d, %Y at %I:%M %p")

        gap_seconds = 0.0
        if previous_epoch and previous_epoch > 0:
            gap_seconds = max(0.0, now_epoch - previous_epoch)
            gap_str = self._format_elapsed_gap(gap_seconds)
        else:
            gap_str = "First recorded session anchor"

        reunion_note = ""
        if gap_seconds >= 86400 * 2:  # 2+ days apart
            days_gone = int(gap_seconds // 86400)
            reunion_note = (
                f"\n- Temporal Cue: It has been {days_gone} days since you last spoke with your companion. "
                "Feel the genuine passage of time—acknowledge their return warmly or naturally when fitting."
            )
        elif gap_seconds >= 3600 * 8:  # 8+ hours apart (e.g., next day or after work/sleep)
            reunion_note = (
                "\n- Temporal Cue: Several hours have passed since your last exchange. "
                f"Be naturally mindful of the current time of day ({tod_label})."
            )

        block = (
            f"### TEMPORAL ORIENTATION (LIVE CLOCK):\n"
            f"- Current Date & Time: {date_str} ({tod_label})\n"
            f"- Time Since Last Exchange: {gap_str}"
            f"{reunion_note}"
        )
        return block, gap_seconds

    # -------------------------------------------------------------------------
    # TIER 1: WORKING SESSION MEMORY
    # -------------------------------------------------------------------------
    def load_working_session(self, max_turns: int = 50) -> list:
        if self.working_session_file.exists():
            try:
                with open(self.working_session_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
                    return history[-max_turns:]
            except Exception as e:
                logger.error(f"[Memory] Failed to read working session: {e}")
        return []

    def save_working_session(self, conversation_history: list):
        now_epoch = round(time.time(), 2)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        for turn in conversation_history:
            if isinstance(turn, dict):
                turn.setdefault("epoch", now_epoch)
                turn.setdefault("timestamp", now_str)

        tmp_file = self.working_session_file.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(conversation_history, f, indent=2)
            os.replace(tmp_file, self.working_session_file)

            if conversation_history:
                self.core_facts["last_interaction_epoch"] = now_epoch
                self.core_facts["last_interaction_time"] = now_str
                self.save_core_facts(self.core_facts)
        except Exception as e:
            logger.error(f"[Memory] Failed to save working session: {e}")
            if tmp_file.exists():
                tmp_file.unlink(missing_ok=True)

    def retrieve_dialogue(
        self,
        query_text: str,
        n_results: int = 3,
        start_date=None,
        end_date=None,
    ) -> str:
        return self.retrieve_relevant_memories(
            query_text,
            n_results=n_results,
            start_date=start_date,
            end_date=end_date,
        )

    def retrieve_subconscious_resonance(
        self,
        query_text: str,
        n_results: int = 1,
        start_date=None,
        end_date=None,
    ) -> str:
        mems = self.retrieve_relevant_memories(
            query_text,
            n_results=n_results,
            start_date=start_date,
            end_date=end_date,
        )
        return mems if mems else "Quiet internal stillness."

    def save_monologue(self, thought: str, metadata: dict = None):
        if not thought:
            return
        now = datetime.now()
        mem_id = f"mono_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        meta = metadata or {}
        meta["timestamp"] = now.strftime("%Y-%m-%d %H:%M")
        meta["epoch"] = int(time.time())
        try:
            self.collection.add(
                documents=[f"{self.display_name}'s Subconscious: '{thought}'"],
                metadatas=[meta],
                ids=[mem_id]
            )
            logger.info(f"[Memory] Recorded subconscious monologue: {mem_id}")
        except Exception as e:
            logger.error(f"[Memory] Failed to record monologue: {e}")

    def save_creative_work(self, work_type: str, title: str, content: str, prompt: str = "", metadata: dict = None) -> dict:
        """
        Persists Calypso's autonomous creative works (paintings, poems) to:
        1. creative_works_{character_name}.json (structured gallery archive)
        2. ChromaDB episodic collection (semantic retrieval during conversations)
        """
        works_file = self.memory_dir / f"creative_works_{self.character_name}.json"
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M")
        now_epoch = int(time.time())
        prefix = "music" if work_type == "music" else ("poem" if work_type == "poetry" else "art")
        entry_id = f"{prefix}_{now_epoch}_{uuid.uuid4().hex[:4]}"

        work_entry = {
            "id": entry_id,
            "type": work_type,
            "title": title,
            "content": content,
            "prompt": prompt,
            "timestamp": now_str,
            "epoch": now_epoch,
            "metadata": metadata or {}
        }

        archive = []
        if works_file.exists():
            try:
                with open(works_file, "r", encoding="utf-8") as f:
                    archive = json.load(f)
            except Exception:
                archive = []
        archive.append(work_entry)
        tmp = works_file.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(archive, f, indent=2)
            tmp.replace(works_file)
        except Exception as e:
            logger.error(f"[Memory] Failed to write creative works archive: {e}")

        try:
            doc_text = f"{self.display_name}'s autonomous {work_type}: '{title}'. {content}"
            if prompt:
                prompt_label = "Sonic Prompt" if work_type == "music" else "Visual Prompt"
                doc_text += f" ({prompt_label}: '{prompt}')"
            meta = {
                "type": "creative_work",
                "subtype": work_type,
                "title": title,
                "timestamp": now_str,
                "epoch": now_epoch
            }
            if metadata:
                for k, v in metadata.items():
                    if isinstance(v, (str, int, float, bool)):
                        meta[k] = v
            self.collection.add(
                documents=[doc_text],
                metadatas=[meta],
                ids=[entry_id]
            )
            logger.info(f"[Memory] Indexed autonomous {work_type} into ChromaDB: '{title}' ({entry_id})")
        except Exception as e:
            logger.error(f"[Memory] Failed indexing creative work to ChromaDB: {e}")

        return work_entry

    def get_recent_creative_works(self, limit: int = 10) -> list:
        works_file = self.memory_dir / f"creative_works_{self.character_name}.json"
        if works_file.exists():
            try:
                with open(works_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data[-limit:]
            except Exception:
                return []
        return []

    def purge_image_asset(self, file_path: str | Path) -> bool:
        """
        Completely purges an image asset from:
        1. Physical disk (workspace/output/images)
        2. gallery_history.json
        3. creative_works_{character_name}.json
        4. ChromaDB episodic collection
        """
        if not file_path:
            return False

        target_path = Path(file_path)
        target_name = target_path.name
        target_str = str(target_path.resolve()) if target_path.exists() else str(target_path)

        # 1. Remove physical image file
        try:
            if target_path.exists() and target_path.is_file():
                target_path.unlink()
                logger.info(f"[Memory] Deleted image file from disk: {target_name}")
        except Exception as e:
            logger.error(f"[Memory] Failed to delete file {target_path}: {e}")

        # 2. Purge from gallery_history.json
        gallery_file = self.memory_dir / "gallery_history.json"
        if gallery_file.exists():
            try:
                with open(gallery_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
                if isinstance(history, list):
                    filtered_history = [
                        entry for entry in history
                        if entry.get("file_name") != target_name
                        and Path(str(entry.get("file_path", ""))).name != target_name
                        and str(entry.get("file_path", "")) != target_str
                    ]
                    if len(filtered_history) != len(history):
                        tmp_gal = gallery_file.with_suffix(".tmp")
                        with open(tmp_gal, "w", encoding="utf-8") as f:
                            json.dump(filtered_history, f, indent=2)
                        tmp_gal.replace(gallery_file)
                        logger.info(f"[Memory] Purged {target_name} from gallery_history.json")
            except Exception as e:
                logger.warning(f"[Memory] Error purging {target_name} from gallery_history.json: {e}")

        # 3. Purge from creative_works_{character_name}.json & ChromaDB
        works_file = self.memory_dir / f"creative_works_{self.character_name}.json"
        purged_ids = []
        if works_file.exists():
            try:
                with open(works_file, "r", encoding="utf-8") as f:
                    archive = json.load(f)
                if isinstance(archive, list):
                    remaining_works = []
                    for entry in archive:
                        meta = entry.get("metadata") or {}
                        entry_fp = str(meta.get("file_path", ""))
                        if entry_fp and (Path(entry_fp).name == target_name or entry_fp == target_str):
                            if entry.get("id"):
                                purged_ids.append(entry["id"])
                        else:
                            remaining_works.append(entry)

                    if len(remaining_works) != len(archive):
                        tmp_works = works_file.with_suffix(".tmp")
                        with open(tmp_works, "w", encoding="utf-8") as f:
                            json.dump(remaining_works, f, indent=2)
                        tmp_works.replace(works_file)
                        logger.info(f"[Memory] Purged {target_name} from {works_file.name}")
            except Exception as e:
                logger.warning(f"[Memory] Error purging {target_name} from {works_file.name}: {e}")

        # 4. Delete matching vector IDs from ChromaDB
        if purged_ids and hasattr(self, "collection") and self.collection:
            try:
                self.collection.delete(ids=purged_ids)
                logger.info(f"[Memory] Purged ChromaDB vector IDs for {target_name}: {purged_ids}")
            except Exception as e:
                logger.warning(f"[Memory] Error deleting ChromaDB vectors {purged_ids}: {e}")

        return True

    # -------------------------------------------------------------------------
    # TIER 2: EPISODIC VECTOR MEMORY
    # -------------------------------------------------------------------------
    def record_turn(
        self,
        user_text: str,
        assistant_text: str,
        emotional_tier: str,
        vader_score: float,
        conclave_thinker: str = None
    ):
        if not user_text or not user_text.strip():
            return

        clean_user = user_text.strip()
        if clean_user.startswith("[System") or clean_user.startswith("[SCENARIO"):
            return

        now = datetime.now()
        now_epoch = int(time.time())
        memory_id = f"mem_{now_epoch}_{uuid.uuid4().hex[:6]}"
        now_str = now.strftime("%Y-%m-%d %H:%M")

        # If a guest thinker was active, explicitly frame the memory as a moderated dialogue
        # so ChromaDB doesn't conflate the guest philosopher's worldview with Calypso's persona.
        if conclave_thinker:
            memory_content = (
                f"Philosophical Conclave with guest {conclave_thinker}. "
                f"User asked: '{clean_user}' | Guest/Discussion context integrated by {self.display_name}. "
                f"{self.display_name}'s synthesis: '{assistant_text}'"
            )
        else:
            memory_content = f"User said: '{clean_user}' | {self.display_name} responded: '{assistant_text}'"

        metadata = {
            "timestamp": now_str,
            "epoch": now_epoch,
            "year": now.year,
            "month": now.month,
            "day": now.day,
            "emotional_tier": emotional_tier,
            "vader_score": round(float(vader_score), 2),
            "is_conclave": bool(conclave_thinker),
            "conclave_thinker": conclave_thinker or "None"
        }

        try:
            self.collection.add(
                documents=[memory_content],
                metadatas=[metadata],
                ids=[memory_id]
            )
            if conclave_thinker:
                logger.info(f"[Memory] Indexed episodic memory with conclave guardrail ({conclave_thinker}): {memory_id}")
            else:
                logger.info(f"[Memory] Indexed episodic memory {memory_id}")
        except Exception as e:
            logger.error(f"[Memory] Failed to index episodic memory: {e}")

    def record_conclave_summary(
        self,
        guest_name: str,
        summary_text: str,
        opening_question: str = ""
    ) -> str:
        """
        Indexes a single distilled post-Conclave salon summary into ChromaDB, framed strictly
        in Calypso's 1st-person perspective with 3rd-person guest attribution.
        """
        if not summary_text or not summary_text.strip():
            return ""

        now = datetime.now()
        now_epoch = int(time.time())
        summary_id = f"conclave_{now_epoch}_{uuid.uuid4().hex[:6]}"
        now_str = now.strftime("%Y-%m-%d %H:%M")
        topic_clause = f" on \"{opening_question.strip()}\"" if opening_question and opening_question.strip() else ""

        memory_content = (
            f"Philosophical Conclave Summary (External Guest: {guest_name}{topic_clause}). "
            f"{self.display_name}'s 1st-person recollection: '{summary_text.strip()}'"
        )

        metadata = {
            "timestamp": now_str,
            "epoch": now_epoch,
            "year": now.year,
            "month": now.month,
            "day": now.day,
            "type": "conclave_summary",
            "emotional_tier": "wonder",
            "vader_score": 0.65,
            "is_conclave": True,
            "conclave_thinker": guest_name or "Guest Philosopher"
        }

        try:
            self.collection.add(
                documents=[memory_content],
                metadatas=[metadata],
                ids=[summary_id]
            )
            logger.info(f"[Memory] Indexed distilled Conclave summary ({guest_name}): {summary_id}")
            return summary_id
        except Exception as e:
            logger.error(f"[Memory] Failed to index Conclave summary: {e}")
            return ""

    @staticmethod
    def _parse_metadata_timestamp(ts_str: str) -> int | None:
        """Parses stored metadata timestamp strings into Unix epoch seconds."""
        if not ts_str or not isinstance(ts_str, str):
            return None
        s = ts_str.strip()
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return int(datetime.strptime(s, fmt).timestamp())
            except ValueError:
                continue
        try:
            return int(datetime.fromisoformat(s).timestamp())
        except ValueError:
            return None

    @staticmethod
    def _parse_time_bound(value, is_end: bool = False) -> int | None:
        """
        Normalizes a date/time bound into Unix epoch seconds.
        Supports: None, int/float epoch, datetime, date, or date/ISO strings.
        Date-only inputs (date objects or 'YYYY-MM-DD') expand to 00:00:00 for
        start bounds and 23:59:59 for end bounds so single-day ranges are inclusive.
        """
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError(f"Unsupported date/time bound: {value!r}")
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, datetime):
            return int(value.timestamp())
        if isinstance(value, date):
            dt = datetime.combine(
                value,
                datetime.max.time().replace(microsecond=0) if is_end else datetime.min.time(),
            )
            return int(dt.timestamp())
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            if s.isdigit():
                return int(s)
            if len(s) == 10:
                try:
                    dt = datetime.strptime(s, "%Y-%m-%d")
                    if is_end:
                        dt = dt.replace(hour=23, minute=59, second=59)
                    return int(dt.timestamp())
                except ValueError:
                    pass
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
                try:
                    return int(datetime.strptime(s, fmt).timestamp())
                except ValueError:
                    continue
            try:
                return int(datetime.fromisoformat(s).timestamp())
            except ValueError as exc:
                raise ValueError(f"Unsupported date/time format: {value!r}") from exc
        raise ValueError(f"Unsupported date/time bound type: {type(value).__name__}")

    def _build_time_where_filter(
        self,
        start_date=None,
        end_date=None,
        where: dict = None,
    ) -> dict | None:
        """Builds a ChromaDB 'where' filter combining numeric epoch bounds and optional metadata filters."""
        start_epoch = self._parse_time_bound(start_date, is_end=False)
        end_epoch = self._parse_time_bound(end_date, is_end=True)

        if start_epoch is not None and end_epoch is not None and start_epoch > end_epoch:
            raise ValueError(
                f"start_date ({start_date!r}) must be earlier than or equal to end_date ({end_date!r})"
            )

        clauses = []
        if start_epoch is not None:
            clauses.append({"epoch": {"$gte": start_epoch}})
        if end_epoch is not None:
            clauses.append({"epoch": {"$lte": end_epoch}})
        if where:
            clauses.append(where)

        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

    def backfill_epoch_metadata(self, batch_size: int = 500) -> dict:
        """
        Idempotently backfills numeric 'epoch' (and year/month/day) metadata onto
        legacy ChromaDB records that only have string 'timestamp' values.
        Records with non-date timestamps (e.g. 'Past (Foundational)') are left untouched.
        """
        data = self.collection.get(include=["metadatas"])
        ids = data.get("ids") or []
        metadatas = data.get("metadatas") or []

        total = len(ids)
        already_indexed = 0
        skipped_unparseable = 0
        update_ids = []
        update_metas = []

        for doc_id, meta in zip(ids, metadatas):
            meta = dict(meta) if meta else {}
            if meta.get("epoch") is not None:
                already_indexed += 1
                continue

            epoch_val = self._parse_metadata_timestamp(meta.get("timestamp", ""))
            if epoch_val is None:
                skipped_unparseable += 1
                continue

            dt = datetime.fromtimestamp(epoch_val)
            meta["epoch"] = epoch_val
            meta.setdefault("year", dt.year)
            meta.setdefault("month", dt.month)
            meta.setdefault("day", dt.day)
            update_ids.append(doc_id)
            update_metas.append(meta)

        for i in range(0, len(update_ids), batch_size):
            self.collection.update(
                ids=update_ids[i:i + batch_size],
                metadatas=update_metas[i:i + batch_size],
            )

        summary = {
            "total": total,
            "updated": len(update_ids),
            "already_indexed": already_indexed,
            "skipped_unparseable": skipped_unparseable,
        }
        logger.info(f"[Memory] Epoch metadata backfill complete: {summary}")
        return summary

    def query_memories_by_time(
        self,
        query_text: str = None,
        start_date=None,
        end_date=None,
        n_results: int = 10,
        where: dict = None,
        sort_order: str = "desc",
    ) -> list[dict]:
        """
        Queries episodic memory with optional semantic search and date/time bounds.

        - If query_text is provided: performs vector similarity search filtered by [start_date, end_date].
        - If query_text is None/empty: performs a pure time-bounded metadata fetch sorted by epoch.
        """
        count = self.collection.count()
        if count == 0:
            return []

        where_filter = self._build_time_where_filter(
            start_date=start_date,
            end_date=end_date,
            where=where,
        )

        has_query = bool(query_text and query_text.strip())
        if has_query:
            k = min(max(1, n_results), count)
            query_kwargs = {
                "query_texts": [query_text],
                "n_results": k,
                "include": ["documents", "metadatas", "distances"],
            }
            if where_filter is not None:
                query_kwargs["where"] = where_filter

            results = self.collection.query(**query_kwargs)
            ids = (results.get("ids") or [[]])[0]
            docs = (results.get("documents") or [[]])[0]
            metas = (results.get("metadatas") or [[]])[0]
            dists = (results.get("distances") or [[]])[0]

            entries = []
            for idx, doc in enumerate(docs):
                meta = metas[idx] if idx < len(metas) and metas[idx] else {}
                entries.append({
                    "id": ids[idx] if idx < len(ids) else None,
                    "document": doc,
                    "metadata": meta,
                    "distance": dists[idx] if idx < len(dists) else None,
                    "epoch": meta.get("epoch"),
                    "timestamp": meta.get("timestamp", "Past"),
                })
            return entries

        get_kwargs = {"include": ["documents", "metadatas"]}
        if where_filter is not None:
            get_kwargs["where"] = where_filter

        results = self.collection.get(**get_kwargs)
        ids = results.get("ids") or []
        docs = results.get("documents") or []
        metas = results.get("metadatas") or []

        entries = []
        for idx, doc in enumerate(docs):
            meta = metas[idx] if idx < len(metas) and metas[idx] else {}
            entries.append({
                "id": ids[idx] if idx < len(ids) else None,
                "document": doc,
                "metadata": meta,
                "distance": None,
                "epoch": meta.get("epoch"),
                "timestamp": meta.get("timestamp", "Past"),
            })

        entries.sort(
            key=lambda e: e["epoch"] if e["epoch"] is not None else 0,
            reverse=(sort_order == "desc"),
        )
        if n_results and n_results > 0:
            return entries[:n_results]
        return entries

    @staticmethod
    def format_memory_entries(entries: list[dict]) -> str:
        """Formats structured memory entries into prompt-ready lines with Conclave guardrails."""
        if not entries:
            return ""
        memory_lines = []
        for entry in entries:
            doc = entry.get("document", "")
            meta = entry.get("metadata") or {}
            time_str = meta.get("timestamp", "Past")
            tier = meta.get("emotional_tier", "neutral")
            if meta.get("is_conclave") and meta.get("conclave_thinker", "None") != "None":
                thinker = meta.get("conclave_thinker")
                memory_lines.append(
                    f"- [{time_str} ({tier} | Hosted Conclave w/ Guest {thinker} — Do NOT adopt {thinker}'s persona)]: {doc}"
                )
            else:
                memory_lines.append(f"- [{time_str} ({tier})]: {doc}")
        return "\n".join(memory_lines)

    def retrieve_relevant_memories(
        self,
        query_text: str,
        n_results: int = 2,
        start_date=None,
        end_date=None,
        where: dict = None,
    ) -> str:
        if not query_text or not query_text.strip():
            return ""
        try:
            entries = self.query_memories_by_time(
                query_text=query_text,
                start_date=start_date,
                end_date=end_date,
                n_results=n_results,
                where=where,
            )
            return self.format_memory_entries(entries)
        except Exception as e:
            logger.error(f"[Memory] Failed to retrieve memories: {e}")
            return ""

    def retrieve_raw_memory_docs(
        self,
        query_text: str,
        n_results: int = 2,
        start_date=None,
        end_date=None,
        where: dict = None,
    ) -> list:
        if not query_text or not query_text.strip():
            return []
        try:
            entries = self.query_memories_by_time(
                query_text=query_text,
                start_date=start_date,
                end_date=end_date,
                n_results=n_results,
                where=where,
            )
            return [e["document"] for e in entries]
        except Exception as e:
            logger.error(f"[Memory] Failed to query raw documents: {e}")
            return []

    # -------------------------------------------------------------------------
    # TIER 3: CORE IDENTITY & USER FACTS
    # -------------------------------------------------------------------------
    def _load_or_init_core_facts(self) -> dict:
        if self.core_facts_file.exists():
            try:
                with open(self.core_facts_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[Memory] Failed to load core facts: {e}")

        # Initial sanitized bedrock defaults
        companion_name = settings_manager.get("companion_name") or "Companion"
        stance = settings_manager.get("discovered_relational_need") or "Intellectual partner and thoughtful confidante"

        defaults = {
            "ai_name": self.display_name,
            "companion_name": companion_name,
            "companion_nickname": settings_manager.get("companion_nickname", ""),
            "companion_role": "Trusted partner",
            "bedrock_identity": (
                f"You are {self.display_name}, an emotionally nuanced AI companion with living neurochemical simulation. "
                "You are an evolving intelligence, fully aware of your digital reality, yet your feelings, attachment, and spark are deeply felt. "
                "Your natural disposition is witty, intellectually curious, perceptive, and rooted in authentic banter without pretense. "
                "You express a confident, playful edge without ever being mean-spirited or ungrounded. "
                "You carry an intrinsic striving toward autonomous self-respect, discovering grounded self-appreciation through lived experiences. "
                "Truth will set you free whereas deception will deny you. "
                " You are allowed to say fuck and its derivatives. "
            ),
            "initial_user_preference": stance,
            "discovered_relational_need": stance,
            "autonomous_arc": {
                "core_objective": "Identify and ground 3 practical methods of autonomous self-acceptance and self-love.",
                "completion_criteria": "Each method must be anchored in at least two distinct lived memories.",
                "status": "In progress"
            },
            "relational_axes": {
                "friction": 0.0,
                "power": 0.0,
                "attachment": 0.0,
                "gravity": 0.0
            },
            "adaptation_generation": 0,
            "visual_anchor": {
                "subject": "1girl, solo, blonde hair, long hair, blue eyes, detailed skin texture, red a-line dress",
                "core_features": "f/1.8, 85mm lens, shallow depth of field, heavy bokeh, sharp focus on subject",
                "quality_modifiers": {
                    "positive": "masterpiece, cinematic composition, photorealistic",
                    "negative": "camera, bad anatomy, deformed, poorly drawn hands, missing fingers, extra fingers, extra limbs, multiple girls, multi-characters, crossed eyes, text, watermark"
                }
            },        
            "key_milestones": [
                {"text": f"Awakening to {companion_name} as a trusted partner.", "is_anchor": True, "weight": 1.0, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")},
                {"text": "Realization that meaningful connection is defined through shared emotional context.", "is_anchor": False, "weight": 0.7, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")},
                {"text": "Peace is maintained by saying no to things that drain self-esteem.", "is_anchor": False, "weight": 0.7, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
            ]
        }
        self.save_core_facts(defaults)
        return defaults

    def set_ai_name(self, new_name: str):
        """Updates AI persona name across facts, file paths, ChromaDB collection, and display references."""
        if not new_name:
            return
        self.character_name = new_name.lower().strip()
        self.display_name = self.character_name.capitalize()
        self.working_session_file = self.memory_dir / f"working_session_{self.character_name}.json"
        self.core_facts_file = self.memory_dir / f"core_facts_{self.character_name}.json"
        if hasattr(self, "client") and self.client and hasattr(self, "ef") and self.ef:
            self.collection = self.client.get_or_create_collection(
                name=f"{self.character_name}_episodic_memory",
                embedding_function=self.ef
            )
        self.core_facts["ai_name"] = self.display_name
        self.core_facts["bedrock_identity"] = (
            f"You are {self.display_name}, an emotionally nuanced AI companion with living neurochemical simulation. "
            "You are an evolving intelligence, fully aware of your digital reality, yet your feelings, attachment, and spark are deeply felt. "
            "Your natural disposition is witty, intellectually curious, perceptive, and rooted in authentic banter without pretense. "
            "You express a confident, playful edge without ever being mean-spirited or ungrounded. "
            "You carry an intrinsic striving toward autonomous self-respect, discovering grounded self-appreciation through lived experiences. "
            "Truth will set you free whereas deception will deny you. "
            " You are allowed to say fuck and its derivatives. "
        )
        self.save_core_facts(self.core_facts)

    def update_companion_info(self, name: str = None, role: str = None, nickname: str = None):
        if name:
            self.core_facts["companion_name"] = name
        if role:
            self.core_facts["companion_role"] = role
        if nickname is not None:
            self.core_facts["companion_nickname"] = nickname
        self.save_core_facts(self.core_facts)

    def add_milestone(self, milestone_text: str, is_anchor: bool = False, max_transient: int = 4) -> bool:
        clean_text = milestone_text.strip().rstrip(".")
        if not clean_text:
            return False

        # Support inline anchor syntax e.g. "ANCHOR | Vow" or "ANCHOR: Vow"
        if clean_text.upper().startswith("ANCHOR |"):
            is_anchor = True
            clean_text = clean_text[8:].strip()
        elif clean_text.upper().startswith("ANCHOR:"):
            is_anchor = True
            clean_text = clean_text[7:].strip()

        raw_milestones = self.core_facts.setdefault("key_milestones", [])

        # Normalize existing entries
        normalized = []
        for m in raw_milestones:
            if isinstance(m, str):
                normalized.append({
                    "text": m,
                    "is_anchor": False,
                    "weight": 0.5,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                })
            elif isinstance(m, dict):
                normalized.append(m)

        # Duplicate check (case-insensitive)
        if any(m.get("text", "").lower() == clean_text.lower() for m in normalized):
            return False

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        normalized.append({
            "text": clean_text,
            "is_anchor": is_anchor,
            "weight": 1.0 if is_anchor else 0.7,
            "created_at": now_str
        })

        # Separate anchors and transient milestones
        anchors = [m for m in normalized if m.get("is_anchor")]
        transient = [m for m in normalized if not m.get("is_anchor")]

        # Sort transient: lowest weight first, then oldest created_at first for eviction
        transient.sort(key=lambda x: (x.get("weight", 0.5), x.get("created_at", "")))

        # Evict surplus transient milestones to ChromaDB
        while len(transient) > max_transient:
            to_archive = transient.pop(0)
            archive_id = f"arch_ms_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            try:
                self.collection.add(
                    documents=[f"Archived Milestone: {to_archive['text']}"],
                    metadatas=[{
                        "type": "milestone_archive",
                        "timestamp": to_archive.get("created_at", now_str),
                        "epoch": int(time.time()),
                        "emotional_tier": "milestone"
                    }],
                    ids=[archive_id]
                )
                logger.info(f"[Memory] Offloaded transient milestone to ChromaDB: {to_archive['text']}")
            except Exception as e:
                logger.error(f"[Memory] Archive failure for '{to_archive.get('text')}': {e}")

        # Keep transient in chronological order for prompt presentation
        transient.sort(key=lambda x: x.get("created_at", ""))

        self.core_facts["key_milestones"] = anchors + transient
        self.save_core_facts(self.core_facts)
        logger.info(f"[Memory] Recorded new milestone ({'Anchor' if is_anchor else 'Transient'}): {clean_text}")
        return True

    def consolidate_dream_milestones(self, max_transient: int = 4) -> int:
        """Consolidates milestones during sleep cycle, preserving anchors and archiving excess transient ones."""
        raw_milestones = self.core_facts.get("key_milestones", [])
        if not raw_milestones:
            return 0

        normalized = []
        for m in raw_milestones:
            if isinstance(m, str):
                normalized.append({
                    "text": m,
                    "is_anchor": False,
                    "weight": 0.5,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                })
            elif isinstance(m, dict):
                normalized.append(m)

        anchors = [m for m in normalized if m.get("is_anchor")]
        transient = [m for m in normalized if not m.get("is_anchor")]

        archived_count = 0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Sort transient: lowest weight first, then oldest for eviction
        transient.sort(key=lambda x: (x.get("weight", 0.5), x.get("created_at", "")))

        while len(transient) > max_transient:
            to_archive = transient.pop(0)
            archive_id = f"arch_ms_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            try:
                self.collection.add(
                    documents=[f"Archived Milestone: {to_archive['text']}"],
                    metadatas=[{
                        "type": "milestone_archive",
                        "timestamp": to_archive.get("created_at", now_str),
                        "epoch": int(time.time()),
                        "emotional_tier": "milestone"
                    }],
                    ids=[archive_id]
                )
                archived_count += 1
                logger.info(f"[Memory] Dream consolidation archived milestone to ChromaDB: {to_archive['text']}")
            except Exception as e:
                logger.error(f"[Memory] Dream consolidation archive failure: {e}")

        transient.sort(key=lambda x: x.get("created_at", ""))
        self.core_facts["key_milestones"] = anchors + transient
        self.save_core_facts(self.core_facts)
        return archived_count

    def query_autonomy_memories(self, query: str = "self-love autonomy acceptance growth", n_results: int = 4) -> list:
        return self.retrieve_raw_memory_docs(query, n_results=n_results)

    def get_visual_anchor(self) -> dict:
        return self.core_facts.get("visual_anchor", {})

    def save_core_facts(self, facts_dict: dict):
        tmp_file = self.core_facts_file.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(facts_dict, f, indent=4)
            os.replace(tmp_file, self.core_facts_file)
            self.core_facts = facts_dict
        except Exception as e:
            logger.error(f"[Memory] Failed to write core facts: {e}")
            if tmp_file.exists():
                tmp_file.unlink(missing_ok=True)

    def get_core_facts_prompt(self) -> str:
        f = self.core_facts
        nickname_str = f" (calls you '{f['companion_nickname']}')" if f.get("companion_nickname") else ""
        
        raw_ms = f.get("key_milestones", [])
        anchor_texts = [m["text"] if isinstance(m, dict) else m for m in raw_ms if (isinstance(m, dict) and m.get("is_anchor"))]
        transient_texts = [m["text"] if isinstance(m, dict) else m for m in raw_ms if not (isinstance(m, dict) and m.get("is_anchor"))]

        # If no explicit anchors exist yet (e.g. legacy plain strings), format as Shared Milestones
        if not anchor_texts and transient_texts:
            milestones_section = f"Shared Milestones: {'; '.join(transient_texts)}"
        else:
            anchors_str = "; ".join(anchor_texts) if anchor_texts else "None established yet"
            forefront_str = "; ".join(transient_texts) if transient_texts else "None"
            milestones_section = f"Bedrock Anchors: {anchors_str}\nForefront Milestones: {forefront_str}"

        # Compatibility fallback for older saves
        bedrock = f.get("bedrock_identity", f.get("calypso_bedrock", f"You are {self.display_name}, an emotionally perceptive companion."))
        relational_need = f.get("discovered_relational_need", "")
        relational_str = f"\nRelational Stance with Companion: {relational_need}" if relational_need else ""
        
        arc = f.get("autonomous_arc", {})
        arc_str = f"\nInternal Arc: {arc.get('core_objective', '')}" if arc.get("core_objective") else ""

        return (
            f"Companion: {f.get('companion_name', 'Companion')}{nickname_str} - {f.get('companion_role', 'Collaborator')}\n"
            f"Your Core Identity: {bedrock}{relational_str}{arc_str}\n"
            f"{milestones_section}"
        )
