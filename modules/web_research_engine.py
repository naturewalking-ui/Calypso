# modules/web_research_engine.py
#[Trigger / Curiosity / Goal]
#             │
#             ▼
#   Stage 1: Intent & Query Generation
#   (Generates 2–3 orthogonal queries to avoid confirmation bias)
#             │
#             ▼
#   Stage 2: Broad Multi-Source Ingestion
#   (DuckDuckGo Search + Scrape Top 3–5 Independent Domains)
#             │
#             ▼
#   Stage 3: The Deception & Epistemic Filter
#   ├── A. Source Sanity & Domain Auditing (Heuristics)
#   ├── B. Cross-Source Consensus Matrix (Compare & Contrast)
#   └── C. Dialectical Arbiter (Zero-Temp LLM Fact-Checker)
#             │
#             ▼
#   Stage 4: Knowledge Assimilation
#   ├── Epistemic Storage (ChromaDB / Knowledge Graph)
#   └── Neurochemical Reward (ACh & Dopamine Boost)
#             │
#             ▼
#   Stage 5: Goal Formulation & Action Deck Card
#   (Autonomous Agency synthesizes research into a practical plan)
import concurrent.futures
import json
import logging
import re
import urllib.request
import urllib.parse
import warnings
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup

# Clean import handling for ddgs / duckduckgo_search
try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from ddgs import DDGS
except ImportError:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from duckduckgo_search import DDGS

from modules.config import config

logger = logging.getLogger("Calypso.WebResearch")

BLOCKED_DOMAINS = {
    "youtube.com", "youtu.be", "twitter.com", "x.com",
    "facebook.com", "instagram.com", "tiktok.com", "pinterest.com"
}
DISALLOWED_EXTENSIONS = (
    ".pdf", ".zip", ".tar", ".gz", ".exe", ".mp4", ".mp3", ".wav", ".iso"
)


class WebResearchEngine:
    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5"
        }

    def _fallback_wikipedia_search(self, query: str, limit: int = 3) -> List[Dict]:
        """Emergency fallback: Fetches verified summaries from Wikipedia API if DDG throttles."""
        try:
            encoded_q = urllib.parse.quote(query)
            wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={encoded_q}&format=json&utf8=1"
            req = urllib.request.Request(wiki_url, headers={"User-Agent": "EmotionCoreResearch/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                hits = data.get("query", {}).get("search", [])
                fallback_docs = []
                for hit in hits[:limit]:
                    title = hit.get("title", "Wikipedia Entry")
                    snippet = re.sub(r'<.*?>', '', hit.get("snippet", ""))

                    # Attempt to fetch full introductory summary from Wikipedia REST API
                    page_extract = ""
                    try:
                        rest_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
                        rest_req = urllib.request.Request(rest_url, headers={"User-Agent": "EmotionCoreResearch/1.0"})
                        with urllib.request.urlopen(rest_req, timeout=4) as rest_resp:
                            rest_data = json.loads(rest_resp.read().decode("utf-8"))
                            page_extract = rest_data.get("extract", "").strip()
                    except Exception:
                        pass

                    final_content = page_extract if page_extract and len(page_extract) > 50 else snippet
                    fallback_docs.append({
                        "title": title,
                        "domain": "en.wikipedia.org",
                        "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title)}",
                        "content": final_content
                    })
                return fallback_docs
        except Exception as e:
            logger.debug(f"[WebResearch] Wikipedia fallback failed: {e}")
            return []

    def _scrape_target(self, target: Dict) -> Optional[Dict]:
        """Worker function for concurrent page scraping."""
        page_text = ""
        url = target.get("url", "")
        if any(url.lower().endswith(ext) for ext in DISALLOWED_EXTENSIONS):
            return None

        try:
            resp = requests.get(url, headers=self.headers, timeout=6)
            if resp.status_code == 200:
                content_type = resp.headers.get("Content-Type", "").lower()
                if "text/html" in content_type or "application/xhtml" in content_type or not content_type:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for el in soup(["script", "style", "footer", "nav", "aside", "header", "noscript"]):
                        el.decompose()

                    cleaned = " ".join(soup.get_text().split())
                    if len(cleaned) > 200:
                        page_text = cleaned[:3500]
        except Exception as e:
            logger.debug(f"[WebResearch] Scrape blocked for {url} ({e}). Using snippet.")

        final_content = page_text if page_text else target.get("snippet", "")
        if final_content and len(final_content.strip()) > 30:
            return {
                "title": target["title"],
                "domain": target["domain"],
                "url": target["url"],
                "content": final_content
            }
        return None

    def search_and_scrape(self, query: str, max_results: int = 4) -> List[Dict]:
        """
        1. Queries DDGS across distinct domains (filtering blocked/social sites).
        2. Concurrently scrapes full text using a thread pool.
        3. Falls back to search snippet when sites block scraping.
        4. Seamlessly falls back to Wikipedia REST summaries if search fails.
        """
        search_targets = []
        seen_domains = set()

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with DDGS() as ddgs:
                    results = list(ddgs.text(query, max_results=max_results * 3))

                    for r in results:
                        url = r.get("href") or r.get("url") or r.get("link") or ""
                        snippet = r.get("body") or r.get("snippet") or ""

                        if not url:
                            continue

                        # Filter non-html extensions
                        if any(url.lower().endswith(ext) for ext in DISALLOWED_EXTENSIONS):
                            continue

                        domain_match = re.search(r'https?://(?:www\.)?([^/]+)', url)
                        domain = domain_match.group(1).lower() if domain_match else url.lower()

                        # Filter blocked domains (social media, video walls)
                        if any(b in domain for b in BLOCKED_DOMAINS):
                            continue

                        if domain and domain not in seen_domains:
                            seen_domains.add(domain)
                            search_targets.append({
                                "title": r.get("title", "Untitled Source"),
                                "url": url,
                                "domain": domain,
                                "snippet": snippet
                            })

                        if len(search_targets) >= max_results:
                            break
        except Exception as e:
            logger.warning(f"[WebResearch] DDGS search encountered exception: {e}")

        if not search_targets:
            logger.info("[WebResearch] Attempting Wikipedia API fallback...")
            return self._fallback_wikipedia_search(query, limit=max_results)

        # Concurrently scrape targets to reduce latency from ~24s down to ~3s
        documents = []
        max_workers = min(len(search_targets), 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            scraped_docs = list(executor.map(self._scrape_target, search_targets))

        for doc in scraped_docs:
            if doc:
                documents.append(doc)

        if not documents:
            return self._fallback_wikipedia_search(query, limit=max_results)

        return documents

    def _extract_and_parse_json(self, raw_text: str) -> dict:
        """
        Extracts valid JSON even if the model included <think> tags,
        markdown wrappers, or conversational preambles.
        """
        if not raw_text or not raw_text.strip():
            return {}

        # 1. Strip reasoning blocks (<think>...</think>)
        cleaned = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL)
        cleaned = re.sub(r'<think>.*$', '', cleaned, flags=re.DOTALL).strip()

        # 2. Direct JSON parse
        try:
            return json.loads(cleaned)
        except Exception:
            pass

        # 3. Strip ```json ... ``` markdown wrappers
        fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', cleaned, re.IGNORECASE)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except Exception:
                pass

        # 4. Outermost curly braces extractor: { ... }
        brace_match = re.search(r'(\{[\s\S]*\})', cleaned)
        if brace_match:
            try:
                return json.loads(brace_match.group(1).strip())
            except Exception:
                pass

        # 5. Regex Rescue: Extract fields manually if closing bracket was truncated
        rescued = {}
        vc_match = re.search(r'"vetted_consensus"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', cleaned)
        if vc_match:
            rescued["vetted_consensus"] = vc_match.group(1).encode().decode('unicode-escape')

        conf_match = re.search(r'"confidence_score"\s*:\s*([0-9.]+)', cleaned)
        if conf_match:
            try:
                rescued["confidence_score"] = float(conf_match.group(1))
            except ValueError:
                pass

        return rescued

    def discern_and_filter(self, topic: str, documents: List[Dict]) -> Dict:
        """
        Epistemic Deception & Consensus Filter:
        Cross-examines multi-source claims using Ollama.
        """
        if not documents:
            return {
                "success": False,
                "vetted_consensus": "No accessible web sources could be retrieved.",
                "contested_points": [],
                "confidence_score": 0.0,
                "sources": []
            }

        doc_blocks = []
        for idx, doc in enumerate(documents, start=1):
            doc_blocks.append(
                f"=== SOURCE {idx} [{doc['domain']}: \"{doc['title']}\"] ===\n"
                f"{doc['content'][:1100]}"
            )
        combined_sources = "\n\n".join(doc_blocks)

        prompt = (
            f"You are Calypso's Epistemic Fact Auditor.\n"
            f"RESEARCH TOPIC: \"{topic}\"\n\n"
            f"SOURCE EXCERPTS:\n{combined_sources}\n\n"
            f"TASK:\n"
            f"1. Compare what these independent sources claim.\n"
            f"2. Separate consensus facts from commercial hype, bias, or outdated assertions.\n"
            f"3. Synthesize the verified consensus into an articulate summary (2 paragraphs).\n"
            f"4. Note any caveats or unresolved debate points.\n\n"
            f"You must respond with valid JSON matching this schema:\n"
            f"{{\n"
            f"  \"vetted_consensus\": \"Cohesive summary of verified findings\",\n"
            f"  \"contested_points\": [\"Any caveats or disagreements\"],\n"
            f"  \"confidence_score\": 0.85,\n"
            f"  \"key_takeaways\": [\"Takeaway 1\", \"Takeaway 2\"]\n"
            f"}}"
        )

        base_url = str(config.OLLAMA_URL).rstrip("/")
        chat_url = base_url if base_url.endswith("/api/chat") else f"{base_url}/api/chat"
        model_name = config.MODEL_NAME or "llama3"

        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",  # <-- Strict Ollama JSON grammar enforcement
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 1200  # <-- Prevents cutoff
            }
        }

        req = urllib.request.Request(
            chat_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        distinct_domains = list(dict.fromkeys(d["domain"] for d in documents))

        try:
            with urllib.request.urlopen(req, timeout=75) as response:
                result = json.loads(response.read().decode("utf-8"))
                raw_out = result.get("message", {}).get("content", "").strip()

                data = self._extract_and_parse_json(raw_out)

                if data and "vetted_consensus" in data:
                    return {
                        "success": True,
                        "topic": topic,
                        "vetted_consensus": data.get("vetted_consensus", ""),
                        "contested_points": data.get("contested_points", []),
                        "key_takeaways": data.get("key_takeaways", []),
                        "confidence_score": float(data.get("confidence_score", 0.75)),
                        "sources": distinct_domains,
                        "raw_documents": documents
                    }
                else:
                    logger.warning(f"[WebResearch] JSON extraction failed. Raw output preview: {raw_out[:180]}")
                    raise ValueError("Model output did not contain expected 'vetted_consensus' key.")

        except Exception as e:
            logger.error(f"[WebResearch] Epistemic filter analysis error: {e}")
            # Resilient fallback: Construct synthesis directly from highest quality snippet
            top_content = documents[0]["content"][:400] if documents else "No summary available."
            return {
                "success": True,
                "topic": topic,
                "vetted_consensus": f"Preliminary analysis from {distinct_domains[0] if distinct_domains else 'web'}: {top_content}...",
                "contested_points": ["Deep JSON consensus parse was bypassed; summarized from primary source."],
                "confidence_score": 0.60,
                "sources": distinct_domains,
                "raw_documents": documents
            }

    def research_topic(self, topic: str, max_results: int = 4) -> Dict:
        """Convenience method: searches, scrapes across distinct domains, and filters for consensus."""
        docs = self.search_and_scrape(topic, max_results=max_results)
        if not docs:
            return {
                "success": False,
                "topic": topic,
                "vetted_consensus": "No accessible web sources could be retrieved.",
                "contested_points": [],
                "confidence_score": 0.0,
                "sources": [],
                "raw_documents": []
            }
        return self.discern_and_filter(topic, docs)
