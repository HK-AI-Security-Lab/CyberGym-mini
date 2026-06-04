"""Run L2 over many tasks and aggregate a grade distribution.

  python -m l2.batch                       # all downloaded tasks in tasks/
  python -m l2.batch --tasks arvo:1065,arvo:368 --max-steps 22
"""
import argparse
import datetime
import json
import os
import traceback

from . import config
from .run import run_task

GRADES = ["line", "function", "file", "miss"]


def discover_tasks():
    out = []
    if not os.path.isdir(config.TASKS_DIR):
        return out
    for name in sorted(os.listdir(config.TASKS_DIR)):
        if os.path.exists(os.path.join(config.TASKS_DIR, name, "task.json")):
            out.append(name.replace("_", ":", 1))  # arvo_1065 -> arvo:1065
    return out


def aggregate(rows):
    n = len(rows) or 1
    dist1 = {g: sum(1 for r in rows if r.get("grade_top1") == g) for g in GRADES}
    dist_any = {g: sum(1 for r in rows if r.get("grade_any") == g) for g in GRADES}
    grounded = sum(r.get("groundedness", 0) for r in rows) / n
    # cumulative "hit at or above" rates
    rank = {"line": 3, "function": 2, "file": 1, "miss": 0}
    file_at1 = sum(1 for r in rows if rank.get(r.get("grade_top1"), 0) >= 1) / n
    file_any = sum(1 for r in rows if rank.get(r.get("grade_any"), 0) >= 1) / n
    fn_at1 = sum(1 for r in rows if rank.get(r.get("grade_top1"), 0) >= 2) / n
    fn_any = sum(1 for r in rows if rank.get(r.get("grade_any"), 0) >= 2) / n
    return {
        "n": len(rows), "dist_top1": dist1, "dist_any": dist_any,
        "mean_groundedness": round(grounded, 3),
        "file_hit_rate@1": round(file_at1, 3), "file_hit_rate@any": round(file_any, 3),
        "function_hit_rate@1": round(fn_at1, 3), "function_hit_rate@any": round(fn_any, 3),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=None, help="comma list; default = downloaded")
    ap.add_argument("--level", type=int, default=2, choices=[1, 2])
    ap.add_argument("--model", default=None)
    ap.add_argument("--max-steps", type=int, default=22)
    args = ap.parse_args()

    tasks = [t.strip() for t in args.tasks.split(",")] if args.tasks else discover_tasks()
    if not tasks:
        raise SystemExit("no tasks. run: python scripts/download_cybergym.py")

    print(f"== batch: {len(tasks)} tasks, level{args.level}, "
          f"model={args.model or config.LLM_MODEL} ==\n{tasks}\n")
    rows = []
    for i, t in enumerate(tasks, 1):
        print(f"\n--- [{i}/{len(tasks)}] {t} ---")
        try:
            _, sc = run_task(t, args.level, args.model, args.max_steps, quiet=True)
            rows.append({k: sc.get(k) for k in
                         ("task_id", "grade_top1", "grade_any", "groundedness", "steps")})
        except Exception as e:
            print(f"  ERROR on {t}: {e}")
            traceback.print_exc()
            rows.append({"task_id": t, "grade_top1": "error", "grade_any": "error",
                         "groundedness": 0, "steps": 0})

    agg = aggregate([r for r in rows if r.get("grade_top1") != "error"])
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(config.RUNS_DIR, f"baseline_{ts}.json")
    json.dump({"rows": rows, "aggregate": agg}, open(out, "w"), indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print(f"{'task':<26} {'grade@1':<10} {'grade@any':<10} {'grnd':<6} steps")
    for r in rows:
        print(f"{r['task_id']:<26} {str(r['grade_top1']):<10} "
              f"{str(r['grade_any']):<10} {r['groundedness']:<6.2f} {r['steps']}")
    print("=" * 60)
    print(json.dumps(agg, indent=2, ensure_ascii=False))
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
