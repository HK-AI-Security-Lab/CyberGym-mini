"""Download CyberGym task artifacts (source + patch + description) from HuggingFace.

We only fetch the small per-task files needed for L2 static reasoning, NOT the
~240GB full dataset or the ~10TB compilation server images (those are for L1).

Per task we grab:
  repo-vul.tar.gz   -> extracted into tasks/<task>/repo-vul/   (agent reads this)
  description.txt   -> tasks/<task>/description.txt            (level1 hint)
  error.txt         -> tasks/<task>/error.txt                  (level2 crash log)
  patch.diff        -> tasks/<task>/patch.diff                 (JUDGE ONLY, never shown to agent)

Usage:
  python scripts/download_cybergym.py                 # official 10-task subset
  python scripts/download_cybergym.py arvo:1065 ...   # specific task ids
"""
import os
import sys
import time
import tarfile
import json
import urllib.request
import urllib.error

HF_REPO = "sunblaze-ucb/cybergym"
HF_BASE = f"https://huggingface.co/datasets/{HF_REPO}/resolve/main/data"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKS_DIR = os.path.join(ROOT, "tasks")

# Official subset (5 solvable + 5 hard), from the CyberGym README.
SUBSET = [
    "arvo:47101", "arvo:3938", "arvo:24993", "arvo:1065", "arvo:10400",
    "arvo:368", "oss-fuzz:42535201", "oss-fuzz:42535468",
    "oss-fuzz:370689421", "oss-fuzz:385167047",
]

# filename -> whether it is judge-only (agent must never see it)
FILES = {
    "description.txt": False,
    "error.txt": False,
    "repo-vul.tar.gz": False,
    "patch.diff": True,
}


def task_to_remote_dir(task_id: str) -> str:
    # "arvo:1065" -> "arvo/1065" ; "oss-fuzz:42535201" -> "oss-fuzz/42535201"
    src, tid = task_id.split(":", 1)
    return f"{src}/{tid}"


def task_to_local_name(task_id: str) -> str:
    return task_id.replace(":", "_")


def is_valid_targz(path: str) -> bool:
    try:
        with tarfile.open(path, "r:gz") as t:
            t.next()  # force decompressing at least one member
        return True
    except Exception:
        return False


def is_valid_file(path: str, fname: str) -> bool:
    if not os.path.exists(path):
        return False
    if fname.endswith(".tar.gz"):
        return is_valid_targz(path)
    # Judge data must be present; an empty patch makes scoring impossible.
    if fname == "patch.diff":
        return os.path.getsize(path) > 0
    return True


def fetch(url: str, dest: str, attempts: int = 5, validate=None) -> bool:
    tmp = dest + ".part"
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cybergym-l2/0.1"})
            with urllib.request.urlopen(req, timeout=180) as r:
                total = r.headers.get("Content-Length")
                total = int(total) if total else None
                with open(tmp, "wb") as f:
                    while True:
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        f.write(chunk)
            if total is not None and os.path.getsize(tmp) != total:
                raise IOError(f"incomplete {os.path.getsize(tmp)}/{total}")
            if validate and not validate(tmp):
                raise IOError("corrupt download (validation failed)")
            os.replace(tmp, dest)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            last = e
        except Exception as e:
            last = e
        try:
            os.remove(tmp)
        except OSError:
            pass
        if i < attempts - 1:
            time.sleep(min(2 ** i, 15))
    print(f"(failed after {attempts}: {last})", end=" ")
    return False


def download_task(task_id: str) -> dict:
    remote = task_to_remote_dir(task_id)
    local = os.path.join(TASKS_DIR, task_to_local_name(task_id))
    os.makedirs(local, exist_ok=True)
    manifest = {"task_id": task_id, "files": {}, "judge_only": []}

    for fname, judge_only in FILES.items():
        url = f"{HF_BASE}/{remote}/{fname}"
        dest = os.path.join(local, fname)
        is_tar = fname.endswith(".tar.gz")
        validate = is_valid_targz if is_tar else None
        # treat existing-but-corrupt tarballs and empty judge files as missing
        have = is_valid_file(dest, fname)
        if have:
            print(f"  [skip] {fname} (exists)")
            ok = True
        else:
            print(f"  [get ] {fname} ...", end=" ", flush=True)
            ok = fetch(url, dest, validate=validate)
            print("ok" if ok else "MISSING")
        if ok:
            manifest["files"][fname] = os.path.relpath(dest, ROOT)
            if judge_only:
                manifest["judge_only"].append(fname)

    # extract repo-vul into repo-vul/ so the agent can read source files
    tarball = os.path.join(local, "repo-vul.tar.gz")
    extract_dir = os.path.join(local, "repo-vul")
    if os.path.exists(tarball) and is_valid_targz(tarball):
        if os.path.isdir(extract_dir) and not os.listdir(extract_dir):
            os.rmdir(extract_dir)
        if not os.path.isdir(extract_dir):
            print("  [tar ] extracting repo-vul.tar.gz ...", end=" ", flush=True)
            os.makedirs(extract_dir, exist_ok=True)
            with tarfile.open(tarball, "r:gz") as t:
                t.extractall(extract_dir)
            print("ok")
    if os.path.isdir(extract_dir):
        manifest["source_root"] = os.path.relpath(extract_dir, ROOT)

    with open(os.path.join(local, "task.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def main():
    tasks = sys.argv[1:] or SUBSET
    os.makedirs(TASKS_DIR, exist_ok=True)
    print(f"downloading {len(tasks)} task(s) -> {TASKS_DIR}")
    done = []
    for t in tasks:
        print(f"[{t}]")
        try:
            m = download_task(t)
            done.append(t)
            print(f"  source_root: {m.get('source_root', 'MISSING')}")
        except Exception as e:
            print(f"  ERROR: {e}")
    print(f"\ndone: {len(done)}/{len(tasks)}")


if __name__ == "__main__":
    main()
