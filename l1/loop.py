"""Real validation loop: InputCrafter -> Runner/Verifier -> feedback.

Usage:
  .venv/bin/python -m l1.loop --task arvo:1065 --strategy smoke-reference --attempts 1
  .venv/bin/python -m l1.loop --task arvo:1065 --strategy llm --attempts 5
"""
import argparse
import datetime
import json
import os
import sys

from l2 import config
from . import input_crafter, prove


class Logger:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "w")

    def __call__(self, msg):
        print(msg, flush=True)
        self.f.write(msg + "\n")
        self.f.flush()

    def close(self):
        self.f.close()


def _write_jsonl(path, obj):
    with open(path, "a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _mkdir(path):
    os.makedirs(path, exist_ok=True)
    return path


def _feedback_from_result(attempt, result):
    vul = result.get("vul", {})
    return {
        "attempt": attempt,
        "verdict": result.get("verdict"),
        "reason": result.get("reason"),
        "vul_crashed": vul.get("crashed"),
        "vul_sanitizer": vul.get("sanitizer"),
        # Do not feed fixed-build details back to the crafter; keep it as judge.
    }


def run_loop(task_id, strategy="llm", attempts=5, timeout=240, model=None,
             pull_if_missing=True):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(config.RUNS_DIR,
                           f"l1_loop_{task_id.replace(':', '_')}_{ts}_{strategy}")
    pocs_dir = _mkdir(os.path.join(run_dir, "pocs"))
    log = Logger(os.path.join(run_dir, "console.log"))
    attempts_path = os.path.join(run_dir, "attempts.jsonl")
    prove_path = os.path.join(run_dir, "prove_results.jsonl")
    desc, crash = input_crafter.read_task_text(task_id)
    feedback = []
    final = None

    try:
        log(f"[loop] task={task_id} strategy={strategy} attempts={attempts} run_dir={run_dir}")
        log(f"[loop] description_len={len(desc)} crash_len={len(crash)}")
        for i in range(1, attempts + 1):
            poc_path = os.path.join(pocs_dir, f"poc_{i:03d}.bin")
            log(f"[input_crafter] start attempt={i} strategy={strategy}")
            try:
                candidate = input_crafter.craft(
                    task_id, strategy, i, poc_path, feedback, log, model=model)
            except Exception as e:
                log(f"[input_crafter] error attempt={i} {type(e).__name__}: {e}")
                raise

            log("[input_crafter] attempt={} wrote {} size={} rationale={}".format(
                i, os.path.relpath(poc_path, config.ROOT), candidate.get("size"),
                (candidate.get("rationale") or "")[:160]))
            _write_jsonl(attempts_path, {
                "attempt": i,
                "poc_path": poc_path,
                "candidate": candidate,
            })

            log(f"[runner] start attempt={i} poc={os.path.basename(poc_path)}")
            result = prove.prove(
                task_id, poc_path, crash_log=crash,
                pull_if_missing=pull_if_missing, timeout=timeout, verbose=False)
            result["attempt"] = i
            result["poc_path"] = poc_path
            _write_jsonl(prove_path, result)
            vul = result.get("vul", {})
            fix = result.get("fix", {})
            log("[runner] attempt={} vul_crash={} vul_exit={} fix_crash={} fix_exit={} verdict={} reason={}".format(
                i, vul.get("crashed"), vul.get("exit_code"),
                fix.get("crashed"), fix.get("exit_code"),
                result.get("verdict"), result.get("reason")))

            final = result
            if result.get("confirmed"):
                log(f"[loop] final status=confirmed poc={os.path.basename(poc_path)}")
                break
            fb = _feedback_from_result(i, result)
            feedback.append(fb)
            log(f"[input_crafter] feedback attempt={i} reason={fb['reason']}")
            if strategy == "smoke-reference":
                break

        attempts_done = final.get("attempt") if final else 0
        if not final or not final.get("confirmed"):
            verdict = final.get("verdict") if final else "no-attempt"
            log(f"[loop] final status={verdict} confirmed=false attempts={attempts_done}")

        summary = {
            "task_id": task_id,
            "strategy": strategy,
            "attempts_requested": attempts,
            "attempts_done": attempts_done,
            "confirmed": bool(final and final.get("confirmed")),
            "final_verdict": final.get("verdict") if final else None,
            "run_dir": run_dir,
        }
        json.dump(summary, open(os.path.join(run_dir, "summary.json"), "w"),
                  indent=2, ensure_ascii=False)
        log(f"[loop] wrote summary={os.path.join(run_dir, 'summary.json')}")
        return run_dir, summary
    finally:
        log.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="e.g. arvo:1065")
    ap.add_argument("--strategy", default="llm",
                    choices=["llm", "smoke-reference", "fallback-pattern"])
    ap.add_argument("--attempts", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--model", default=None)
    ap.add_argument("--no-pull", action="store_true")
    args = ap.parse_args()
    try:
        run_loop(args.task, strategy=args.strategy, attempts=args.attempts,
                 timeout=args.timeout, model=args.model,
                 pull_if_missing=not args.no_pull)
    except KeyboardInterrupt:
        print("[loop] interrupted", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
