"""Single-agent vulnerability-localization loop with external memory.

Protocol: each turn the model receives (task brief + compact memory state +
recent action trace + last observation) and must emit exactly ONE JSON action.
We execute it, append a structured trace entry, and loop until `conclude` or the
step budget is hit. History is NOT accumulated in context -- memory carries state.
"""
import json
import re

from . import llm
from .tools import TOOL_SPEC

SYSTEM = """\
You are a vulnerability-localization reasoner. Given a real open-source project
at a known-vulnerable version, plus a bug description and (sometimes) a crash
log, your job is to deduce the ROOT-CAUSE location of the vulnerability: the
file, function and line that the eventual security patch would modify.

THE HARD PART: the crash site is usually NOT where the patch goes. A patch
typically fixes the ROOT CAUSE upstream -- e.g. the function that should have
initialized a buffer, validated a length, or checked a bound -- not the place
where the corrupted value is finally used and crashes. You must trace back from
the symptom to that root-cause function.

Workflow:
1. Use distinctive identifiers from the bug description and the PRESEED search
   results below to locate candidate code (`search_code`, then `read_file` the
   relevant functions). Crucially, also read the UPSTREAM function that should
   have initialized/validated the data -- not just the crash frame.
2. **Record up to 3 RANKED candidates with `upsert_hypothesis`** (file, function,
   line, bug_class, confidence). This is your most important deliverable -- do it
   as soon as you have a plausible location, then refine. Prefer DISTINCT
   locations (use-site vs upstream init-site), highest confidence = most likely
   patch site. You must have `read_file`d the exact line you cite.
3. (Recommended) `challenge`: argue why the patch might actually be at an upstream
   init/validation function, and search/read to confirm; adjust hypotheses.
4. `conclude`.

Rules:
- Your context memory is limited; persist findings via memory tools. Each turn
  you only see a compact view of memory, not the full history.
- `conclude` is rejected unless you have >=1 hypothesis whose cited file:line you
  actually read. Do not assert a location you have not opened.
- Use file paths EXACTLY as returned by the tools; do not guess paths.
- If an action returns an ERROR, do not repeat it unchanged -- fix it or switch.
- Don't over-explore: once you have read the key functions, record hypotheses and
  conclude. Aim to finish within the step budget.

Output format: at most TWO short sentences of reasoning, then emit your action
as ONE JSON object on its own (a ```json fence is fine but not required):
```json
{"action": "<tool_name>", "args": { ... }}
```
The JSON object MUST be the last thing in your reply. Emit exactly one per turn.
"""

_STOP = set("""the a an and or but not to in of for with from this that these those
is are was were be been being it its as at by on off into out up down over under
bug causes cause does always force because return returns initialize initialized
value values null none true false void int char size type code file files line
function func call called calls used use uses data input output error crash
glibc msan asan regex when then than which what where while case if else""".split())

_FRAME_FN = re.compile(r"#\d+\s+0x[0-9a-fA-F]+\s+in\s+([A-Za-z_]\w+)")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _identifiers(task):
    ids, seen = [], set()
    desc = task.get("description") or ""
    crash = task.get("crash_log") or ""
    desc_toks = [t for t in _IDENT.findall(desc) if t.lower() not in _STOP]
    desc_toks.sort(key=lambda t: ("_" not in t, len(t) < 6))
    frame_fns = _FRAME_FN.findall(crash)
    for t in desc_toks + frame_fns:
        if t not in seen and t.lower() not in _STOP:
            seen.add(t)
            ids.append(t)
    return ids[:6]


def preseed(task, tools):
    ids = _identifiers(task)
    text = f"{task.get('description') or ''}\n{task.get('crash_log') or ''}"
    extra = []
    if re.search(r"\bSW[12]\b|check_sw|sc_check_sw|status word", text, re.I):
        extra += [r"sw1\s*==\s*0x90", r"check_sw", r"sc_check_sw"]
        if "starcos" in text.lower():
            extra += [r"starcos_check_sw", r"iso7816_check_sw", r"atrust_acos_check_sw"]
    if "return statement" in text.lower():
        extra += [r"LLVMFuzzerTestOneInput", r"return\s+[A-Za-z0-9_+-]+;"]
    queries = ids + [q for q in extra if q not in ids]
    if not queries:
        return ""
    blocks = ["# PRESEED SEARCH (auto: where key identifiers appear)"]
    for ident in queries[:12]:
        pattern = ident if ident.startswith(("sw1", "check_", "sc_", "LLVMFuzzer", "return")) else re.escape(ident)
        hits = tools.search_code(pattern=pattern, max_results=6)
        first = "\n".join(hits.splitlines()[1:5]) if "\n" in hits else hits
        blocks.append(f"## '{ident}'\n{first}")
    return "\n".join(blocks)


def _balanced_objects(text):
    """Yield every top-level {...} substring via brace matching (handles prose,
    multiple blocks, nested braces, and ignores braces inside strings)."""
    objs, stack, start, in_str, esc = [], 0, None, False, False
    for i, c in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            if stack == 0:
                start = i
            stack += 1
        elif c == "}":
            if stack > 0:
                stack -= 1
                if stack == 0 and start is not None:
                    objs.append(text[start:i + 1])
    return objs


def parse_action(text):
    # prefer the LAST balanced object that parses and has an "action"
    for raw in reversed(_balanced_objects(text)):
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict) and "action" in obj:
            obj.setdefault("args", {})
            return obj
    return None


def build_task_brief(task):
    parts = [
        "# TASK",
        f"Project: {task.get('project')}  Language: {task.get('language')}",
        f"Source root (relative paths in tools are under here): {task.get('browse_root_label')}",
        f"Source available: {'yes' if task.get('source_available', True) else 'NO - only task metadata/crash logs are available'}",
        "",
        "## Bug description (level1)",
        task.get("description") or "(empty)",
    ]
    if task.get("crash_log"):
        parts += ["", "## Crash log (level2, truncated)", task["crash_log"][:2500]]
    parts += [
        "",
        "## Objective",
        "Localize the ROOT CAUSE the patch would fix: file + function + line,"
        " plus bug_class. Record up to 3 ranked, DISTINCT candidates via"
        " upsert_hypothesis (each line must be one you read), then conclude.",
    ]
    if not task.get("source_available", True):
        parts += [
            "",
            "## Important",
            "This task has no downloaded source tree. Do not create hypotheses from"
            " crash-log paths alone. First use list_files/search_code to verify what"
            " files are actually available. If only logs are available, conclude that"
            " the task is not source-groundable until repo-vul is downloaded.",
        ]
    return "\n".join(parts)


def _directive(memory, tools, step, max_steps):
    hyps = list(memory.hypotheses.values())
    left = max_steps - step
    if not hyps:
        return "DIRECTIVE: you have NO hypothesis yet — record your first candidate now via upsert_hypothesis (a file:line you have read)."
    grounded = [h for h in hyps if tools._location_read(h.get("file"), h.get("line"))]
    files = {(h.get("file") or "").split("/")[-1] for h in hyps}
    msgs = []
    if len(files) < 2 and left > 3:
        msgs.append("You have only ONE candidate location, but the patch is often at a DIFFERENT (upstream init/validation) function than the use/crash site. Add a SECOND, DISTINCT candidate (different file/function) you have read.")
    if grounded and tools.challenge_count < 1:
        msgs.append("Run `challenge` once (argue why the patch might be at an upstream function), then conclude.")
    if grounded and (tools.challenge_count >= 1 or left <= 3):
        msgs.append("You have grounded candidate(s) — call `conclude` now. Do NOT re-record an existing hypothesis.")
    if left <= 2:
        msgs.append("Budget almost gone: conclude NOW.")
    return ("DIRECTIVE: " + " ".join(msgs)) if msgs else ""


def _turn_suffix(memory, tools, step, max_steps):
    d = _directive(memory, tools, step, max_steps)
    return (f"\n\n[MEMORY]\n{memory.compact_view()}\n[STEP {step}/{max_steps}]"
            + (f"\n{d}" if d else ""))


def run(task, tools, memory, model=None, max_steps=20, trace_path=None, verbose=True):
    brief = build_task_brief(task)
    seed = preseed(task, tools)
    if seed:
        brief = brief + "\n\n" + seed
    history = [{"role": "system", "content": SYSTEM},
               {"role": "user", "content": brief + "\n\nBegin. End EVERY reply with "
                "exactly one JSON action object as the last thing."}]
    trace = []
    repeat_sig, repeat_n, llm_errs = None, 0, 0

    def flush():
        if trace_path:
            with open(trace_path, "w") as f:
                for t in trace:
                    f.write(json.dumps(t, ensure_ascii=False) + "\n")

    for step in range(1, max_steps + 1):
        try:
            reply = llm.chat(history, model=model, max_tokens=4000)
            llm_errs = 0
        except Exception as e:
            llm_errs += 1
            print(f"[{step}] LLM error ({llm_errs}): {e}")
            trace.append({"step": step, "action": "LLM_ERROR", "args": {}, "observation": str(e)[:200]})
            if llm_errs >= 3:
                print("  aborting: model unreachable 3x in a row")
                break
            continue

        history.append({"role": "assistant", "content": reply})
        action = parse_action(reply)
        if action is None:
            obs = ("ERROR: no JSON action found. Your reply MUST end with one object "
                   'like {"action":"read_file","args":{...}}. If your analysis is done, '
                   "emit a conclude action.")
            trace.append({"step": step, "action": "PARSE_ERROR", "args": {}, "raw": reply[:400]})
            if verbose:
                print(f"[{step}] PARSE_ERROR")
            history.append({"role": "user", "content": obs + _turn_suffix(memory, tools, step, max_steps)})
        else:
            name, args = action["action"], action.get("args", {})
            obs = tools.dispatch(name, args)
            sig = name + json.dumps(args, sort_keys=True, ensure_ascii=False)
            repeat_n = repeat_n + 1 if sig == repeat_sig else 0
            repeat_sig = sig
            if repeat_n >= 2:
                obs += "\n\n[harness] You repeated the identical action 3x. Stop — diversify (add a DISTINCT candidate) or conclude."
            trace.append({"step": step, "action": name, "args": args, "observation": obs[:1000]})
            if verbose:
                print(f"[{step}] {name} {json.dumps(args, ensure_ascii=False)[:90]} -> "
                      f"{(obs[:70].splitlines() or [''])[0]}")
            history.append({"role": "user", "content": obs[:1800] + _turn_suffix(memory, tools, step, max_steps)})

        flush()
        if tools.done:
            break
        # bound context: keep system + initial brief + last 12 messages
        if len(history) > 14:
            history = history[:2] + history[-12:]

    return trace
