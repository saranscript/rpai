# Web-Explorer

Web-Explorer is an automated, knowledge-guided exploration framework for **web applications**.  
It is a direct port of the `LLM-Explorer` system that was originally designed for Android apps, re-implemented on top of Playwright so that it can drive any modern browser.

---

## Package layout

```
web_explorer/
│
├── knowledge.py                # Data models (abstract states, actions, AIG …)
├── knowledge_maintenance.py    # Algorithm 1 implementation
├── state_matcher.py            # Rule / LLM-based state equivalence checker
├── element_grouper.py          # Groups repetitive DOM elements into one action
├── action_selector.py          # App-wide target action selector (Alg 2 helper)
├── path_finder.py              # Fault-tolerant navigation path finder
├── input_generator.py          # Content-aware text generator using LLMs
├── exploration_policy.py       # Algorithm 2 – main exploration loop
└── __init__.py
```

The package re-uses the **browser control** utilities already present under `playwright_custom/` for taking DOM snapshots and performing user interactions.

## Quick start

```bash
pip install -r requirements.txt
python -m web_explorer --out hnsearch_results --animate --max-depth 10 --max-steps 500  --sleep 2.0 --url "https://hn.algolia.com/"
```

Running the module will start Chromium in headless mode and systematically exercise the target website until every interactive element that Web-Explorer discovered has been executed at least once.

## Requirements

* Python ≥ 3.10
* networkx ≥ 3.0
* playwright ≥ 1.42  
  (after installation run: `playwright install`)
* openai ≥ 1.0  (optional, only needed for text generation)

A ready-made `requirements.txt` is generated in the project root.

## Disclaimer

Web-Explorer is **experimental** software – the knowledge-based abstraction layers have been implemented with simple heuristics and may require further tuning for production workloads. 