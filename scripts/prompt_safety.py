"""
prompt_safety.py — Single source of truth for factual-safety rules.

Every generator in this repo (generate_summaries.py, generate_editorial.py,
generate_gemini.py, generate_vendor_hub.py) imports FACTUAL_SAFETY_BLOCK
from here and prepends it to its own system prompt. This guarantees that
vendor misclassifications, invented standards support, and hype language
are forbidden uniformly across every AI generation path.

If you need to update the safety rules (e.g. add a new vendor to the safe
list, ban a new phrase), edit scripts/factual_safety.txt only. All
generators pick up the change on the next run.
"""
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SAFETY_FILE = os.path.join(_THIS_DIR, "factual_safety.txt")

def _load() -> str:
    try:
        with open(_SAFETY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        # Minimal fallback if the file is missing — never crash a pipeline
        return (
            "STRICT FACTUAL SAFETY: Never guess what a product does. Never "
            "assign a product category unless the source explicitly states it. "
            "Never invent standards support (ST 2110, NMOS, SCTE-35, etc.) "
            "unless the source names them. Never add competitor names not in "
            "the source. Mediagenix is scheduling/rights/BMS — NOT playout. "
            "If the source is vague, stay vague. Accuracy over impressiveness."
        )

FACTUAL_SAFETY_BLOCK = _load()
