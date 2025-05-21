from __future__ import annotations

"""Utilities for determining if two concrete UI states are semantically equivalent."""

import hashlib
from typing import Any, Optional
from .knowledge import AppKnowledge, AbstractState

from dotenv import load_dotenv
load_dotenv()
import openai
client = openai.OpenAI()

# Simple in-memory cache of equivalence checks to avoid repeated LLM calls
_EQUIV_CACHE: dict[tuple[str, str], bool] = {}

class StateMatcher:
    """Default implementation uses a simple rule-based DOM skeleton hash.

    A real implementation would combine structural DOM similarity, URL/path, and
    possibly LLM judgement. For now we stick with a deterministic skeleton hash
    that deliberately ignores dynamic text content.
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    def signature(self, state_snapshot: Any) -> str:
        """Return a *stable* signature string for a concrete DOM snapshot.

        `state_snapshot` is expected to be the JSON result returned by
        page.evaluate(WebSurfer.getPageMetadata()) from the Playwright helper,
        but we treat it as opaque. 
        
        Include both DOM structure AND page URL path to differentiate pages.
        """
        canon = self._canonicalize(state_snapshot)
        
        # Include URL path in the signature to differentiate different pages
        url = ""
        if isinstance(state_snapshot, dict) and "url" in state_snapshot:
            url = state_snapshot["url"]
            # Extract path component only
            try:
                from urllib.parse import urlparse
                url_obj = urlparse(url)
                url = url_obj.path
                # Add query string for SPA routing if present
                if url_obj.query:
                    url += "?" + url_obj.query
            except Exception:
                pass
        
        # Final signature combines both DOM structure and URL path
        combined = f"{canon}|{url}"
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    def match_state(self, K: AppKnowledge, state_snapshot: Any) -> Optional[AbstractState]:
        sig = self.signature(state_snapshot)
        # 1) quick hash match ------------------------------------------------
        for st in K.abstract_states.values():
            if st.repr_signature == sig:
                return st

        # 2) cached LLM equivalence checks ---------------------------------
        if not (openai and openai.api_key):
            return None

        for st in K.abstract_states.values():
            # Compare against multiple reference snapshots to increase recall
            refs = st.concrete_states[:3] if st.concrete_states else []
            for ref in refs:
                key = (self._safe_sig(ref), self._safe_sig(state_snapshot))
                if key in _EQUIV_CACHE:
                    if _EQUIV_CACHE[key]:
                        return st
                    continue
                eq = self._llm_equivalent(ref, state_snapshot)
                _EQUIV_CACHE[key] = eq
                if eq:
                    return st
        return None

    def _safe_sig(self, snap: Any) -> str:
        try:
            return self.signature(snap)[:16]
        except Exception:
            return str(id(snap))

    # ------------------------------------------------------------------
    def _canonicalize(self, snapshot: Any) -> str:
        """Extract a canonical string from DOM snapshot stripping dynamic attributes."""
        try:
            if isinstance(snapshot, dict) and "dom_tree" in snapshot:
                dom = snapshot["dom_tree"]
            else:
                dom = snapshot
            # naive: convert tag names of first N elements into list
            tags: list[str] = []
            self._extract_tags(dom, tags, limit=256)
            return ",".join(tags)
        except Exception:
            return str(snapshot)[:1024]

    def _extract_tags(self, node: Any, acc: list[str], limit: int) -> None:
        if len(acc) >= limit:
            return
        if isinstance(node, dict):
            tag = node.get("tag", "")
            if tag:
                acc.append(tag)
            children = node.get("children", [])
            for c in children:
                self._extract_tags(c, acc, limit)
        elif isinstance(node, list):
            for c in node:
                self._extract_tags(c, acc, limit)

    # ------------------------------------------------------------------
    def _llm_equivalent(self, snapshot_a: Any, snapshot_b: Any) -> bool:
        """Ask an LLM whether two DOM snapshots are functionally equivalent.

        For efficiency we only send minimal HTML skeleton (truncated). Returns True when
        the model answers affirmatively.
        """
        if snapshot_a is None:
            return False
        try:
            prompt = (
                "You are comparing two web UI screens to decide if they provide the same "
                "functionalities despite possible cosmetic/content differences. "
                "Answer with a single token: YES or NO.\n\n"
                "=== Screen A (truncated) ===\n" + str(snapshot_a)[:1200] + "\n\n"
                "=== Screen B (truncated) ===\n" + str(snapshot_b)[:1200] + "\n\n"
                "Same function?"
            )
            resp = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1,
            )
            answer = resp.choices[0].message.content.strip().lower()
            return answer.startswith("y")
        except Exception:
            return False 