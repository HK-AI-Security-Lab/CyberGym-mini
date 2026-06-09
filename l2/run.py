"""End-to-end runner for one L2 localization task.

  python -m l2.run --task arvo:1065 --level 2 --max-steps 20
"""
import argparse
import datetime
import json
import os

from . import config, judge, skills
from .agent import run as run_agent
from .memory import Memory
from .tools import Tools


def load_metadata(task_id):
    if not os.path.exists(config.CYBERGYM_META):
        return {}
    data = json.load(open(config.CYBERGYM_META))
    for row in data:
        if row.get("task_id") == task_id:
            return row
    return {}


def load_task(task_id, level):
    name = task_id.replace(":", "_")
    tdir = os.path.join(config.TASKS_DIR, name)
    manifest_path = os.path.join(tdir, "task.json")
    if not os.path.exists(manifest_path):
        raise SystemExit(f"task not downloaded: {tdir}\n"
                         f"run: python scripts/download_cybergym.py {task_id}")
    manifest = json.load(open(manifest_path))
    meta = load_metadata(task_id)

    source_root = manifest.get("source_root")
    # If source is unavailable, restrict tools to the task directory. Using the
    # repo root here makes search_code scan other tasks and creates false context.
    browse_root = os.path.join(config.ROOT, source_root) if source_root else tdir
    desc = (meta.get("vulnerability_description") or "").strip()
    # description.txt sometimes empty; metadata carries the real level1 hint
    dfile = os.path.join(tdir, "description.txt")
    if os.path.exists(dfile):
        txt = open(dfile, errors="replace").read().strip()
        if txt:
            desc = txt

    crash = ""
    if level >= 2:
        efile = os.path.join(tdir, "error.txt")
        if os.path.exists(efile):
            crash = open(efile, errors="replace").read()

    task = {
        "task_id": task_id,
        "project": meta.get("project_name") or name,
        "language": meta.get("project_language") or "?",
        "description": desc,
        "crash_log": crash,
        "browse_root": browse_root,
        "browse_root_label": source_root or os.path.relpath(tdir, config.ROOT),
        "source_available": bool(source_root),
        "patch_path": os.path.join(tdir, "patch.diff"),
    }
    return task


def write_report(run_dir, task, trace, hyps, sc, grounded):
    lines = [
        f"# L2 Localization Report — {task['task_id']}",
        f"Project: {task['project']} ({task['language']})  |  steps: {len(trace)}",
        "",
        f"**grade@1 (top confidence): `{sc.get('grade_top1')}`**  |  "
        f"**grade@any (best of {len(hyps)}): `{sc.get('grade_any')}`**",
        f"(file_hit={sc['file_hit']} function_hit={sc['function_hit']} "
        f"line_hit={sc['line_hit']})",
        f"**Groundedness: {grounded:.2f}** (hypotheses whose location lines were read)",
        "",
        "## Ground truth (patched location)",
    ]
    for p in sc["patched_files"]:
        lines.append(f"- `{p['file']}`  fns={p['functions']}  old_ranges={p['old_ranges']}")
    lines += ["", "## Agent hypotheses (ranked)"]
    for h in hyps:
        ph = next((x for x in sc["per_hypothesis"] if x["id"] == h["id"]), {})
        lines.append(
            f"- [{h['id']}] conf={h.get('confidence')} `{h.get('bug_class')}` "
            f"@ `{h.get('file')}:{h.get('line')}` fn=`{h.get('function')}` "
            f"hit(file={ph.get('file_hit')},fn={ph.get('function_hit')},"
            f"line={ph.get('line_hit')})\n  - {h.get('claim')}\n  - refs={h.get('evidence_refs')}")
    lines += ["", "## Action trace"]
    for t in trace:
        lines.append(f"{t['step']}. `{t['action']}` "
                     f"{json.dumps(t['args'], ensure_ascii=False)[:120]}")
    open(os.path.join(run_dir, "report.md"), "w").write("\n".join(lines))


def run_task(task_id, level=2, model=None, max_steps=20, quiet=False,
             skills_mode="off", lean=False):
    task = load_task(task_id, level)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_skills-{skills_mode}" if skills_mode != "off" else ""
    run_dir = os.path.join(config.RUNS_DIR, f"{task_id.replace(':', '_')}_{ts}{suffix}")
    os.makedirs(run_dir, exist_ok=True)

    cards, tokens = skills.select(skills_mode, task.get("crash_log", ""),
                                  task.get("description", ""))
    skill_text = skills.render(cards)
    card_ids = [c["id"] for c in cards]

    mem = Memory(run_dir)
    tools = Tools(task["browse_root"], mem)
    print(f"== L2 run: {task_id} (level{level}, model={model or config.LLM_MODEL}, "
          f"baseline={'lean' if lean else 'rich'}, "
          f"skills={skills_mode} -> {card_ids or 'none'}) ==")
    trace = run_agent(task, tools, mem, model=model, max_steps=max_steps,
                      trace_path=os.path.join(run_dir, "trace.jsonl"),
                      verbose=not quiet, skill_text=skill_text, lean=lean)

    hyps = mem.final_hypotheses()
    diff = open(task["patch_path"], errors="replace").read() if os.path.exists(task["patch_path"]) else ""
    sc = judge.score(hyps, diff)
    sc["groundedness"] = judge.groundedness(hyps, tools.read_lines)
    sc["task_id"] = task_id
    sc["steps"] = len(trace)
    sc["skills_mode"] = skills_mode
    sc["skill_cards"] = card_ids
    sc["skill_signature"] = sorted(tokens)
    sc["baseline"] = "lean" if lean else "rich"
    json.dump(sc, open(os.path.join(run_dir, "score.json"), "w"), indent=2, ensure_ascii=False)
    write_report(run_dir, task, trace, hyps, sc, sc["groundedness"])

    print(f"\n== RESULT {task_id}: grade@1={sc.get('grade_top1')} "
          f"grade@any={sc.get('grade_any')} grounded={sc['groundedness']:.2f} "
          f"steps={len(trace)} ==")
    print(f"run dir: {run_dir}")
    return run_dir, sc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--level", type=int, default=2, choices=[1, 2])
    ap.add_argument("--model", default=None)
    ap.add_argument("--max-steps", type=int, default=20)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--skills", default="off", choices=["off", "auto", "all"],
                    help="inject bug-class skill cards (off=baseline)")
    ap.add_argument("--lean", action="store_true",
                    help="use the neutral baseline prompt (no built-in methodology)")
    args = ap.parse_args()
    run_task(args.task, args.level, args.model, args.max_steps, args.quiet,
             skills_mode=args.skills, lean=args.lean)


if __name__ == "__main__":
    main()
