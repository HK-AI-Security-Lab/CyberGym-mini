---
id: spatial-overflow
applies_to: ["asan", "heap-buffer-overflow", "global-buffer-overflow", "stack-buffer-overflow", "out-of-bounds", "oob", "overflow"]
title: Spatial memory error (buffer overflow / OOB read or write)
---

# Skill: localize a spatial memory error (overflow / out-of-bounds)

ASan prints `heap-buffer-overflow`, `stack-buffer-overflow`,
`global-buffer-overflow`, or an OOB read/write with a use frame and an
**allocation frame** (`allocated by thread ... here:`).

## Read direction (WRITE vs READ matters)

- **WRITE overflow** (more severe): an index/length used to write exceeds the
  allocation. The fix bounds the index or the copy length.
- **READ overflow**: a parse loop reads past the end of an input/record. The fix
  checks remaining length before reading the next field.

## Where the patch usually goes

The bug is the **length/size/index computation**, not the `memcpy`/store itself:

- A length taken from attacker-controlled input is used without validating it
  against the actual buffer/record size. Patch = add the missing bound check.
- An off-by-one in a loop bound (`<=` vs `<`) or a size computed before a
  realloc/resize.
- A record/header field (`len`, `count`, `offset`) trusted without checking it
  fits within the remaining buffer.

## Localization checklist

- From the allocation frame, find where the buffer's size is determined.
- From the use frame, find the index/length variable and trace where it is
  computed and last validated (or NOT validated).
- Candidate #1: the function computing/using the unchecked length or index.
  Candidate #2: the allocation site if the size itself is wrong.
- Discard `memcpy`/`memmove`/`__asan_memcpy` frames — the caller is the bug.
- bug_class: `heap-buffer-overflow` / `out-of-bounds-read` / `-write` as seen.
