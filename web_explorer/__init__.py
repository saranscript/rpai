"""Web Explorer package providing automated UI exploration for web applications.

This package replicates the functionality of the original mobile-focused `LLM-Explorer` but relies on Playwright to
interact with browser‐based applications.

Key sub-modules:

knowledge.py              – Core data models representing abstract states, actions and the graph.
knowledge_maintenance.py  – Implementation of Algorithm 1 (knowledge update).
state_matcher.py          – Rule- and LLM-based state equivalence checking utilities.
action_selector.py        – Implements the app-wide target action selection logic.
path_finder.py            – Fault-tolerant navigation path discovery over the abstract interaction graph.
input_generator.py        – Content-aware text generation using LLMs for input boxes.
exploration_policy.py     – Implementation of Algorithm 2 (end-to-end exploration loop).

All runtime-level browser operations are delegated to the helpers already available under the
`playwright_custom` package (e.g. `PlaywrightController`).
""" 