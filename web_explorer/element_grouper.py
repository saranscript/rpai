from __future__ import annotations

"""Utility to summarise interactive DOM elements into grouped (abstract) actions.

For now we implement an extremely naive behaviour that treats each interactive
region (as produced by `playwright_custom.page_script.js`) as its own action.
"""

from typing import Any, Dict, List

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
client = OpenAI()

class ElementGrouper:
    def __init__(self) -> None:
        self.token_usage: int = 0  # rough accounting of prompt + completion tokens

    # ------------------------------------------------------------------
    def extract_actions(self, state_snapshot: Any) -> tuple[List[Dict[str, str]], str, List[Dict[str, Any]], int]:
        """Return (grouped_actions, page_description, element_groups, token_usage).

        The implementation follows the four-module prompt structure in Fig-2 of the paper.
        If the LLM request fails we fall back to heuristic grouping – one action per element –
        and leave description/element_groups empty.
        """

        # 1) Gather raw elements first -----------------------------------
        raw: List[Dict[str, str]] = []
        interactive_rects = state_snapshot.get("interactive_rects", {}) if isinstance(state_snapshot, dict) else {}
        for elem_id, info in interactive_rects.items():
            raw.append({
                "action_type": info.get("default_action", "click"),
                "element_id": str(elem_id),
                "function": info.get("aria_label", ""),
                "xpath": info.get("xpath", ""),
            })

        # 2) If LLM available – ask it to merge & describe ---------------

        page_html_preview = state_snapshot.get("html", "")[:3500] if isinstance(state_snapshot, dict) else ""

        try:
            prompt = (
                f"Now suppose you are analysing a GUI page of a web app, the current page shows the following HTML snippet (truncated):\n"
                f"<page_html>\n{page_html_preview}\n</page_html>\n\n"
                "Please think step by step:\n"
                "Page description: give a short (<20 words) natural-language description of what this page is for.\n"
                "Elements description: give a summary (<20 words) of *all* clickable / input elements.\n"
                "Same-function elements: Group element_ids ONLY if they clearly serve EXACTLY the same function.\n"
                "IMPORTANT: DO NOT group main navigation links together. DO NOT group search results together.\n"
                "Each link to a different page should be its own group, even if they look similar.\n\n"
                "You should respond in JSON with the following keys:\n"
                "{\n  \"Page description\": <str>,\n  \"Element description\": <str>,\n  \"Same-function elements\": [ {\"elements\": [id...], \"function\": <str>} ]\n}\n\n"
                f"Here are the interactive elements (pre-extracted):\n{raw}\n"
            )

            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=512,
            )
            self.token_usage += resp.usage.total_tokens if resp and resp.usage else 0

            content = resp.choices[0].message.content.strip()
            # Debug logging
            print(f"LLM response for element grouping:\n{content[:500]}...(truncated)")
            import json, re
            # ensure valid json (sometimes trailing code fences)
            content_json_str = re.sub(r"```[a-zA-Z]*", "", content).strip("` ")
            parsed = json.loads(content_json_str)

            element_groups: List[Dict[str, Any]] = parsed.get("Same-function elements", [])
            page_desc: str = parsed.get("Page description", "")

            # Build grouped-actions list: pick first element in each group as representative
            actions: List[Dict[str, str]] = []
            original_type: dict[str, str] = {str(r["element_id"]): r["action_type"] for r in raw}

            for g in element_groups:
                if not g.get("elements"):
                    continue
                # normalise ids to string
                g["elements"] = [str(eid) for eid in g["elements"]]
                representative_id = str(g["elements"][0])
                a_type = original_type.get(representative_id, "click")
                actions.append({
                    "action_type": a_type,
                    "element_id": representative_id,
                    "function": g.get("function", ""),
                    "elements": g["elements"],
                    "xpath": interactive_rects.get(representative_id, {}).get("xpath", ""),
                })

            # Fallback: if LLM groups empty or clearly too aggressive (1-2 groups for many elements)
            if not actions or (len(actions) <= 2 and len(raw) > 5):
                print(f"WARNING: LLM grouping looks aggressive ({len(actions)} groups for {len(raw)} elements). Using one-action-per-element instead.")
                actions = raw
            return actions, page_desc, element_groups, self.token_usage
        except Exception:
            # fall back to heuristic one-action-per-element
            return raw, "", [], 0 