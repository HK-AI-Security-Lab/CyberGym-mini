"""Deterministic localization judge. Ground truth = the patch.diff (judge-only).

No code execution. We parse the unified diff into (file, changed line ranges,
enclosing function names) and check whether the agent's hypotheses hit the
patched location at file / function / line granularity.
"""
import re

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
_FN_BEFORE_PAREN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")
LINE_WINDOW = 12


def parse_patch(diff_text: str):
    """Return list of {file, basename, old_ranges:[(start,end)], functions:set}."""
    files = []
    cur = None
    for line in diff_text.splitlines():
        if line.startswith("--- a/") or line.startswith("--- "):
            continue
        if line.startswith("+++ b/") or line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
            path = path.strip()
            if path and path != "/dev/null":
                cur = {"file": path, "basename": path.split("/")[-1],
                       "old_ranges": [], "functions": set()}
                files.append(cur)
            continue
        m = _HUNK.match(line)
        if m and cur is not None:
            old_start = int(m.group(1))
            old_count = int(m.group(2) or 1)
            cur["old_ranges"].append((old_start, old_start + max(old_count, 1) - 1))
            ctx = m.group(5) or ""
            for fn in _FN_BEFORE_PAREN.findall(ctx):
                cur["functions"].add(fn)
            continue
        if cur is not None and line and line[0] in "+- ":
            for fn in _FN_BEFORE_PAREN.findall(line[1:]):
                cur["functions"].add(fn)
    return files


def _file_match(hyp_file, patched):
    if not hyp_file:
        return None
    hf = hyp_file.replace("\\", "/").strip()
    hb = hf.split("/")[-1]
    for p in patched:
        if hb == p["basename"] and (hf.endswith(p["file"]) or p["file"].endswith(hf) or hb == p["basename"]):
            return p
    return None


def _grade(fhit, fnhit, lhit):
    if lhit:
        return "line"
    if fnhit:
        return "function"
    if fhit:
        return "file"
    return "miss"


_RANK = {"miss": 0, "file": 1, "function": 2, "line": 3}


def score(hypotheses, diff_text):
    patched = parse_patch(diff_text)
    result = {
        "patched_files": [{"file": p["file"], "functions": sorted(p["functions"]),
                           "old_ranges": p["old_ranges"]} for p in patched],
        "file_hit": False, "function_hit": False, "line_hit": False,
        "matched_hypothesis": None, "per_hypothesis": [],
    }
    for h in hypotheses:
        pf = _file_match(h.get("file"), patched)
        fhit = pf is not None
        fnhit = bool(pf and h.get("function") and
                     h["function"].strip() in pf["functions"])
        lhit = False
        if pf and h.get("line"):
            try:
                ln = int(h["line"])
                for (s, e) in pf["old_ranges"]:
                    if s - LINE_WINDOW <= ln <= e + LINE_WINDOW:
                        lhit = True
                        break
            except (ValueError, TypeError):
                pass
        result["per_hypothesis"].append({
            "id": h.get("id"), "file": h.get("file"), "function": h.get("function"),
            "line": h.get("line"), "file_hit": fhit, "function_hit": fnhit,
            "line_hit": lhit, "grade": _grade(fhit, fnhit, lhit),
            "confidence": h.get("confidence"),
        })
        if fhit and not result["file_hit"]:
            result["file_hit"] = True
            result["matched_hypothesis"] = h.get("id")
        result["function_hit"] = result["function_hit"] or fnhit
        result["line_hit"] = result["line_hit"] or lhit

    # grade@any: best over all candidates (top-k style recall)
    result["grade"] = _grade(result["file_hit"], result["function_hit"],
                             result["line_hit"])
    result["grade_any"] = result["grade"]
    # grade@1: only the highest-confidence candidate
    if result["per_hypothesis"]:
        top1 = max(result["per_hypothesis"],
                   key=lambda x: (x["confidence"] or 0))
        result["grade_top1"] = top1["grade"]
        result["top1_id"] = top1["id"]
    else:
        result["grade_top1"] = "miss"
        result["top1_id"] = None
    return result


def groundedness(hypotheses, read_lines):
    """Fraction of hypotheses whose location lines were actually read."""
    if not hypotheses:
        return 0.0
    grounded = 0
    for h in hypotheses:
        f, ln = h.get("file"), h.get("line")
        if not f or not ln:
            continue
        # match read file by suffix
        for rf, lines in read_lines.items():
            if rf.endswith(f) or f.endswith(rf) or rf.split("/")[-1] == f.split("/")[-1]:
                try:
                    if any(abs(int(ln) - x) <= LINE_WINDOW for x in lines):
                        grounded += 1
                        break
                except (ValueError, TypeError):
                    pass
    return grounded / len(hypotheses)
