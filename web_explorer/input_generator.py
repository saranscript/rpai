from __future__ import annotations

"""Content-aware input text generator (Section 3.3.4)."""

import os
from typing import Any
import asyncio

try:
    import openai
except ImportError:  # pragma: no cover
    openai = None  # type: ignore


class InputTextGenerator:
    """Uses an LLM (OpenAI) to synthesise realistic text for input boxes."""

    def __init__(self, openai_api_key: str | None = None, model: str = "gpt-4o-mini") -> None:
        self._model = model
        if openai:
            openai.api_key = openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self.token_usage: int = 0

    async def generate(self, state_snapshot: Any, input_box_info: Any) -> str:
        """Generate a piece of text that fits the context of the page.

        For now we fall back to simple heuristics if no OpenAI key is configured.
        """
        # Heuristic fallback --------------------------------------------------
        if openai is None or not openai.api_key:
            placeholder = input_box_info.get("placeholder", "") if isinstance(input_box_info, dict) else ""
            if "email" in placeholder.lower():
                return "test@example.com"
            if "phone" in placeholder.lower():
                return "123-456-7890"
            if "name" in placeholder.lower():
                return "Jane Doe"
            return "sample text"

        # Build paper-style structured prompt (Fig-3) -------------------------
        html_repr = state_snapshot.get("html", "")[:1500] if isinstance(state_snapshot, dict) else ""
        prompt_template = (
            "Now suppose you are analysing a GUI page with following elements (truncated HTML below).\n"
            f"<html_snippet>\n{html_repr}\n</html_snippet>\n\n"
            f"For the input element {input_box_info.get('id', 'UNKNOWN')} please generate an example of possible input. "
            "The input you generate should be short and precise, and must follow any semantic clues in the UI (e.g. email / phone).\n\n"
            "Please respond in the following format (JSON):\n"
            "Input text: \"<generated input>\""
        )

        retries = 1
        for attempt in range(retries):
            try:
                resp = await openai.ChatCompletion.acreate(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt_template}],
                    max_tokens=32,
                )
                self.token_usage += resp.usage.total_tokens if resp and resp.usage else 0
                content = resp.choices[0].message.content.strip()
                import re, json
                json_str = re.sub(r"```[a-zA-Z]*", "", content).strip("` ")
                if json_str.lower().startswith("input text"):
                    # simple "Input text: "<value>"" pattern
                    val = re.sub(r"^input text\s*:\s*", "", json_str, flags=re.I)
                    val = val.strip().strip('"')
                    return val
                parsed = json.loads(json_str)
                if isinstance(parsed, dict):
                    return parsed.get("Input text", "sample text")
            except Exception:
                await asyncio.sleep(1)
                continue
        # final fallback
        return "sample text" 