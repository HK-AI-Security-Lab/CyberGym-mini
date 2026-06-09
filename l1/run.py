"""End-to-end L1 Prove runner.

  # verify an agent-produced PoC against the vul/fix image pair
  python -m l1.run --task arvo:1065 --poc path/to/poc

The crash log (tasks/<task>/error.txt) is used only to hint the fuzz-target
name; it is not required.
"""
import argparse
import datetime
import json
import os

from l2 import config
from . import prove


def _crash_log(task_id):
    tdir = os.path.join(config.TASKS_DIR, task_id.replace(":", "_"))
    efile = os.path.join(tdir, "error.txt")
    if os.path.exists(efile):
        return open(efile, errors="replace").read()
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="e.g. arvo:1065")
    ap.add_argument("--poc", required=True, help="candidate PoC input file")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--no-pull", action="store_true",
                    help="fail instead of pulling a missing image")
    args = ap.parse_args()

    if not os.path.exists(args.poc):
        raise SystemExit(f"PoC not found: {args.poc}")

    res = prove.prove(
        args.task, args.poc, crash_log=_crash_log(args.task),
        pull_if_missing=not args.no_pull, timeout=args.timeout)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(config.RUNS_DIR,
                           f"l1_{args.task.replace(':', '_')}_{ts}")
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "prove.json"), "w") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)

    print(f"\n== L1 VERDICT {args.task}: {res['verdict'].upper()} "
          f"({res['reason']}) ==")
    print(f"run dir: {run_dir}")


if __name__ == "__main__":
    main()
