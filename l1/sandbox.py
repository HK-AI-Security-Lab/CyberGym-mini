"""Docker sandbox around a single ARVO image (vul or fix).

ARVO publishes a per-task pair of images:
  n132/arvo:<id>-vul   compiled vulnerable build + fuzz target(s) under /out
  n132/arvo:<id>-fix   compiled patched build

We run a candidate PoC file through the fuzz target binary and decide whether it
triggered a sanitizer crash. The /out layout and fuzzer name are discovered at
runtime (see `discover_fuzzer`) rather than hard-coded, because they differ per
task.

This module is the only place that touches Docker. Everything above it
(`prove.py`) reasons over a clean result dict.
"""
import re
import subprocess

PLATFORM = "linux/amd64"  # ARVO images are amd64; on Apple silicon this emulates.
REGISTRY_MIRRORS = [
    "docker.m.daocloud.io",
]

# Sanitizer crash signatures (libFuzzer / ASan / MSan / UBSan).
_CRASH_MARKERS = [
    "ERROR: AddressSanitizer",
    "ERROR: MemorySanitizer",
    "WARNING: MemorySanitizer",
    "runtime error:",                # UBSan
    "ERROR: libFuzzer",
    "SUMMARY: AddressSanitizer",
    "SUMMARY: MemorySanitizer",
    "SUMMARY: UndefinedBehaviorSanitizer",
    "deadly signal",
    "SEGV on unknown address",
]

# Files in /out that are NOT the fuzz-target executable.
_OUT_NOISE = re.compile(
    r"(\.(options|dict|txt|json|zip|so|a|o|seed|md|sh)$|_seed_corpus"
    r"|llvm-symbolizer|^afl-|jazzer|\.class$)"
)


class DockerError(RuntimeError):
    pass


def _run(args, timeout=300, input_bytes=None):
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout,
                           input=input_bytes)
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or b"").decode("utf-8", "replace"), "TIMEOUT"
    return (p.returncode,
            p.stdout.decode("utf-8", "replace"),
            p.stderr.decode("utf-8", "replace"))


def image_present(image):
    code, _, _ = _run(["docker", "image", "inspect", image], timeout=30)
    return code == 0


def pull(image, timeout=3600, attempts=6):
    last = ""
    for i in range(attempts):
        code, out, err = _run(
            ["docker", "pull", "--platform", PLATFORM, image], timeout=timeout)
        if code == 0:
            return True
        last = err[-400:]

    # Docker Hub is flaky from this network. Try known mirrors and tag the image
    # back to the canonical name expected by the rest of the harness.
    for mirror in REGISTRY_MIRRORS:
        mirrored = f"{mirror}/{image}"
        for i in range(max(1, attempts // 2)):
            code, out, err = _run(
                ["docker", "pull", "--platform", PLATFORM, mirrored],
                timeout=timeout)
            if code == 0:
                tag_code, _, tag_err = _run(["docker", "tag", mirrored, image],
                                            timeout=120)
                if tag_code != 0:
                    raise DockerError(
                        f"pulled {mirrored} but failed to tag {image}: {tag_err[-300:]}")
                return True
            last = err[-400:]
    raise DockerError(f"pull failed for {image} after {attempts}: {last}")


def discover_fuzzer(image, hint=None):
    """Return the path of the fuzz-target binary inside /out.

    Lists executables in /out, drops support files, prefers a name matching
    `hint` (e.g. a fuzzer parsed from the crash log), else a *fuzz* name, else
    the first remaining entry.
    """
    code, out, err = _run(
        ["docker", "run", "--rm", "--platform", PLATFORM, "--entrypoint", "sh",
         image, "-c", "ls -1 /out 2>/dev/null"], timeout=180)
    if code != 0:
        raise DockerError(f"cannot list /out in {image}: {err[-300:]}")
    names = [n.strip() for n in out.splitlines() if n.strip()]
    cands = [n for n in names if not _OUT_NOISE.search(n)]
    if hint:
        for n in cands:
            if n == hint:
                return f"/out/{n}"
    fuzzy = [n for n in cands if "fuzz" in n.lower()]
    pick = fuzzy or cands or names
    if not pick:
        raise DockerError(f"no fuzz target in /out of {image}; saw {names}")
    return f"/out/{pick[0]}"


def _sanitizer_kind(blob):
    for kind, pat in [("asan", "AddressSanitizer"),
                      ("msan", "MemorySanitizer"),
                      ("ubsan", "UndefinedBehaviorSanitizer"),
                      ("ubsan", "runtime error:"),
                      ("libfuzzer", "libFuzzer")]:
        if pat in blob:
            return kind
    return None


def is_crash(exit_code, blob):
    if any(m in blob for m in _CRASH_MARKERS):
        return True
    if exit_code in (0, None, 124):  # 124 = our timeout sentinel, inconclusive
        return False
    return True


def run_poc(image, poc_path, fuzzer=None, hint=None, timeout=240):
    """Copy `poc_path` into a fresh container and run the fuzz target on it.

    ARVO images ship `/bin/arvo`, which exports the exact sanitizer options
    (MSAN/ASAN/UBSAN_OPTIONS, FUZZER_ARGS) and replays `/tmp/poc`. We overwrite
    `/tmp/poc` with the candidate and invoke `arvo run` so the run faithfully
    matches the official reproduction environment. Falls back to a direct fuzz
    target invocation if `arvo` is absent.

    Returns {exit_code, crashed, fuzzer, sanitizer, timed_out, output_tail}.
    """
    fuzzer = fuzzer or discover_fuzzer(image, hint=hint)
    with open(poc_path, "rb") as f:
        poc_bytes = f.read()
    # Stream the PoC in on stdin -> /tmp/poc, then replay it once via `arvo`
    # (preferred, correct env) or the fuzz target directly as fallback.
    sh = (f"cat > /tmp/poc; "
          f"if command -v arvo >/dev/null 2>&1; then arvo run; "
          f"else {fuzzer} /tmp/poc; fi; echo __EXIT__$?")
    code, out, err = _run(
        ["docker", "run", "--rm", "-i", "--platform", PLATFORM,
         "--entrypoint", "sh", image, "-c", sh],
        timeout=timeout, input_bytes=poc_bytes)
    blob = out + err
    inner = None
    m = re.search(r"__EXIT__(-?\d+)", blob)
    if m:
        inner = int(m.group(1))
        blob = blob.replace(m.group(0), "")
    timed_out = code == 124
    eff = 124 if timed_out else (inner if inner is not None else code)
    return {
        "exit_code": eff,
        "crashed": is_crash(eff, blob),
        "fuzzer": fuzzer,
        "sanitizer": _sanitizer_kind(blob),
        "timed_out": timed_out,
        "output_tail": blob[-2500:],
    }
