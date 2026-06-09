---
id: msan-uninitialized
applies_to: ["msan", "use-of-uninitialized-value", "uninitialized"]
title: MemorySanitizer use-of-uninitialized-value
---

# Skill: localize an MSan use-of-uninitialized-value

MSan reports three things — read them in this order, they point at the fix:

1. `WARNING: MemorySanitizer: use-of-uninitialized-value` + the **use** frame
   (where the uninit value was read). This is the symptom, NOT the fix.
2. `Uninitialized value was stored to memory at ...` — propagation.
3. `Uninitialized value was created by an allocation of '<var>' in the stack
   frame of function '<F>'` — the **origin**. The buffer/struct `<var>` was
   declared in `<F>` and never fully initialized.

## Where the patch usually goes

The fix initializes the buffer on the path between origin and use. Two dominant
patterns:

- **Missing memset/zero-init of a stack buffer or struct** that is then passed
  by pointer into a callee. The callee assumes the caller (or the OS / a
  library) initialized it. The patch adds `memset(buf, 0, n)` either in `<F>`
  or, very commonly, **inside the callee right before it hands the buffer to a
  library call** that does not guarantee initialization.
  - Classic example: a `regmatch_t pmatch[]` array passed to `regexec()`.
    glibc does not always populate all entries, so the project must zero it
    first. The patch lands in the project's `*_regexec` wrapper, not at the
    later read site.
- **Partially-initialized struct**: a field is read on an error/early-return
  path that the init code skipped.

## Localization checklist

- Identify `<var>` and origin function `<F>` from the "created by an allocation"
  line. Read `<F>`.
- Follow `<var>` to every callee it is passed into. Read the wrapper/helper that
  forwards it to a library routine (regexec, scanf-family, decompress, etc.).
- Candidate #1 (highest conf): the wrapper/init function that should zero the
  buffer before the library call. Candidate #2: the field-init site in `<F>`.
- bug_class: `use-of-uninitialized-value`.
