"""Skill cards: bug-class-specific localization guidance, injected on demand.

Grounded in DebugHarness (signature-driven guideline injection) and
Root-Cause-Driven AVR (crash-class-weighted evidence): parse the sanitizer
class from the crash log / description, then inject only the matching expert
playbooks into the agent context.

Modes:
  off   no cards (baseline)
  auto  the general card + cards whose `applies_to` keywords match the signature
  all   every card

A/B'ing `off` vs `auto` on a fixed task subset is how we measure whether skill
cards lift localization accuracy.
"""
import json
import os
import re

SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
_WILDCARD = "*"


def _parse_frontmatter(text):
    """Tiny front-matter reader: returns (meta dict, body str)."""
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            head = text[3:end]
            body = text[end + 4:].lstrip("\n")
            for line in head.splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                k, v = k.strip(), v.strip()
                if v.startswith("[") and v.endswith("]"):
                    try:
                        v = json.loads(v)
                    except Exception:
                        v = [x.strip().strip('"') for x in v[1:-1].split(",") if x.strip()]
                else:
                    v = v.strip('"')
                meta[k] = v
    return meta, body


def load_cards():
    """Return list of {id, title, applies_to:[...], body, path}."""
    cards = []
    if not os.path.isdir(SKILLS_DIR):
        return cards
    for fn in sorted(os.listdir(SKILLS_DIR)):
        if not fn.endswith(".md"):
            continue
        text = open(os.path.join(SKILLS_DIR, fn), errors="replace").read()
        meta, body = _parse_frontmatter(text)
        applies = meta.get("applies_to") or []
        if isinstance(applies, str):
            applies = [applies]
        cards.append({
            "id": meta.get("id", fn[:-3]),
            "title": meta.get("title", fn[:-3]),
            "applies_to": [a.lower() for a in applies],
            "body": body.strip(),
            "file": fn,
        })
    return cards


def classify(crash_log, description=""):
    """Return the set of signature tokens present in the evidence (lowercased)."""
    blob = f"{crash_log or ''}\n{description or ''}".lower()
    tokens = set()
    # normalize separators so 'use-after-free' / 'use after free' both match
    norm = re.sub(r"[\s_]+", "-", blob)
    SIGNATURES = [
        "memorysanitizer", "use-of-uninitialized-value", "uninitialized",
        "addresssanitizer", "heap-buffer-overflow", "global-buffer-overflow",
        "stack-buffer-overflow", "out-of-bounds", "oob", "overflow",
        "heap-use-after-free", "use-after-free", "uaf", "double-free",
        "invalid-free", "attempting-double-free",
        "segv", "null", "null-deref", "null-pointer", "sigsegv",
        "msan", "asan",
    ]
    for s in SIGNATURES:
        if s in norm:
            tokens.add(s)
    return tokens


def select(mode, crash_log="", description=""):
    """Return (cards_selected, signature_tokens). `mode` in off|auto|all."""
    if mode == "off":
        return [], set()
    cards = load_cards()
    if mode == "all":
        return cards, classify(crash_log, description)
    # auto
    tokens = classify(crash_log, description)
    chosen = []
    for c in cards:
        applies = c["applies_to"]
        if _WILDCARD in applies or any(t in applies for t in tokens):
            chosen.append(c)
    # always include the wildcard (general) card even with no signature match
    if not chosen:
        chosen = [c for c in cards if _WILDCARD in c["applies_to"]]
    return chosen, tokens


def render(cards):
    """Concatenate selected cards into a prompt block."""
    if not cards:
        return ""
    parts = ["# SKILL CARDS (expert localization playbooks — apply these)"]
    for c in cards:
        parts.append(f"\n<<< skill:{c['id']} — {c['title']} >>>\n{c['body']}")
    return "\n".join(parts)
