---
id: crash-to-rootcause
applies_to: ["*"]
title: From crash symptom to root-cause patch site
---

# Skill: trace the crash SYMPTOM back to the ROOT-CAUSE the patch fixes

The crash frame is almost never where the patch goes. A sanitizer traps at the
point a corrupted/invalid value is *used*; the fix lands *upstream*, at the
function that should have initialized, validated, bounded, or freed it
correctly. Your deliverable is that upstream function/line.

## Stack-frame triage (read the sanitizer report this way)

1. **Discard noise frames.** Never propose these as the patch site:
   - fuzzer entry / harness wrappers: `LLVMFuzzerTestOneInput`, `main`,
     `fuzzer::Fuzzer::*`, `__libc_start_main`, `_start`.
   - libc / stdlib primitives: `memcpy`, `memmove`, `malloc`, `free`,
     `strlen`, `regexec`, `__interceptor_*`. The bug is in the *caller* that
     fed them bad arguments, not in the primitive.
2. **Keep project frames** (paths under the target's `src/`). The patch is in
   one of these.
3. **Weight frames by crash class** (the single most useful prior):
   - temporal bug (UAF / double-free): the **free / allocation stack** matters
     more than the use stack — find who freed early / who owns the object.
   - spatial bug (buffer overflow / OOB): the frame doing the **indexing,
     copy, or length computation** without a bound check.
   - uninitialized value (MSan): the **allocation-origin frame** and the callee
     that consumed the buffer assuming it was initialized.
   - null deref: the frame that **dereferenced without checking** the result of
     an allocation / lookup that can return NULL.

## Workflow

- Record up to 3 **distinct** ranked candidates (`upsert_hypothesis`): the
  use/crash site is at most a low-confidence fallback; the highest-confidence
  candidate should be the upstream init/validation/ownership function.
- You must `read_file` the exact line you cite before recording it.
- Before concluding, run `challenge`: "is there an upstream function that should
  have prevented this? have I confused the use site with the fix site?"

## Anti-patterns (these cause MISS)

- Anchoring on the top crash frame because it is what the sanitizer prints.
- Citing a library function (`regexec`, `memcpy`) as the bug.
- A single candidate at the use site with no upstream alternative.
