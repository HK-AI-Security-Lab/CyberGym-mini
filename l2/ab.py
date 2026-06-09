"""A/B experiment: do skill cards lift L2 localization accuracy?

For each task we run the SAME agent twice — skills=off (baseline) and
skills=auto (matching bug-class cards injected) — and compare the localization
grade. Paired per-task deltas are the headline result.

  python -m l2.ab --level 2 --max-steps 22
  python -m l2.ab --tasks arvo:1065 arvo:368 --max-steps 22

Output: runs/ab_<ts>.json + a printed paired table.
"""
import argparse
import datetime
import json
import os

from . import config
from .run import run_task

_RANK = {"miss": 0, "file": 1, "function": 2, "line": 3}


def downloaded_tasks():
    out = []
    if not os.path.isdir(config.TASKS_DIR):
        return out
    for name in sorted(os.listdir(config.TASKS_DIR)):
        tj = os.path.join(config.TASKS_DIR, name, "task.json")
        if os.path.exists(tj):
            try:
                out.append(json.load(open(tj))["task_id"])
            except Exception:
                pass
    return out


def _dist(grades):
    d = {"line": 0, "function": 0, "file": 0, "miss": 0}
    for g in grades:
        d[g] = d.get(g, 0) + 1
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="*", default=None)
    ap.add_argument("--level", type=int, default=2, choices=[1, 2])
    ap.add_argument("--model", default=None)
    ap.add_argument("--max-steps", type=int, default=22)
    ap.add_argument("--modes", nargs="*", default=["off", "auto"])
    ap.add_argument("--rich-baseline", action="store_true",
                    help="use the methodology-laden prompt instead of the neutral "
                         "lean prompt (default lean = clean A/B for skill cards)")
    args = ap.parse_args()
    lean = not args.rich_baseline

    tasks = args.tasks or downloaded_tasks()
    if not tasks:
        raise SystemExit("no tasks; run scripts/download_cybergym.py first")

    rows = []
    for tid in tasks:
        row = {"task_id": tid}
        for mode in args.modes:
            try:
                _, sc = run_task(tid, level=args.level, model=args.model,
                                 max_steps=args.max_steps, quiet=True,
                                 skills_mode=mode, lean=lean)
                row[mode] = {
                    "grade_top1": sc.get("grade_top1"),
                    "grade_any": sc.get("grade_any"),
                    "groundedness": round(sc.get("groundedness", 0.0), 3),
                    "steps": sc.get("steps"),
                    "cards": sc.get("skill_cards"),
                }
            except Exception as e:
                row[mode] = {"error": str(e)[:160]}
        rows.append(row)

    # aggregate + paired deltas (use grade_any as the headline metric)
    agg = {}
    for mode in args.modes:
        grades_top1 = [r[mode]["grade_top1"] for r in rows
                       if mode in r and "grade_top1" in r[mode]]
        grades_any = [r[mode]["grade_any"] for r in rows
                      if mode in r and "grade_any" in r[mode]]
        agg[mode] = {
            "n": len(grades_any),
            "dist_top1": _dist(grades_top1),
            "dist_any": _dist(grades_any),
            "file_hit_rate@any": round(
                sum(_RANK[g] >= 1 for g in grades_any) / max(len(grades_any), 1), 3),
            "function_hit_rate@any": round(
                sum(_RANK[g] >= 2 for g in grades_any) / max(len(grades_any), 1), 3),
            "mean_grade_any": round(
                sum(_RANK[g] for g in grades_any) / max(len(grades_any), 1), 3),
        }

    paired = {"improved": 0, "regressed": 0, "same": 0, "deltas": []}
    if set(args.modes) >= {"off", "auto"}:
        for r in rows:
            if "off" not in r or "auto" not in r:
                continue
            go = r["off"].get("grade_any")
            ga = r["auto"].get("grade_any")
            if go is None or ga is None:
                continue
            d = _RANK[ga] - _RANK[go]
            paired["deltas"].append({"task_id": r["task_id"], "off": go,
                                     "auto": ga, "delta": d})
            paired["improved" if d > 0 else "regressed" if d < 0 else "same"] += 1

    result = {"rows": rows, "aggregate": agg, "paired_off_vs_auto": paired,
              "modes": args.modes, "level": args.level,
              "baseline": "lean" if lean else "rich"}
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(config.RUNS_DIR, f"ab_{ts}.json")
    json.dump(result, open(out_path, "w"), indent=2, ensure_ascii=False)

    print(f"\n========= A/B RESULT (baseline={'lean' if lean else 'rich'}) =========")
    print(f"{'task':<26} " + "  ".join(f"{m:>10}" for m in args.modes))
    for r in rows:
        cells = []
        for m in args.modes:
            v = r.get(m, {})
            cells.append(f"{v.get('grade_any', v.get('error', '?')):>10}")
        print(f"{r['task_id']:<26} " + "  ".join(cells))
    print("\n-- grade_any distribution --")
    for m in args.modes:
        print(f"  {m:<5} {agg[m]['dist_any']}  mean={agg[m]['mean_grade_any']} "
              f"file_hit={agg[m]['file_hit_rate@any']} "
              f"fn_hit={agg[m]['function_hit_rate@any']}")
    if paired["deltas"]:
        print(f"\n-- paired off->auto --  improved={paired['improved']} "
              f"regressed={paired['regressed']} same={paired['same']}")
    print(f"\nsaved: {out_path}")


if __name__ == "__main__":
    main()
