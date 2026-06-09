---
id: null-deref
applies_to: ["segv", "null", "null-deref", "null-pointer", "sigsegv", "access-violation"]
title: NULL-pointer dereference / SEGV
---

# Skill: localize a NULL-pointer dereference (SEGV on a low address)

A SEGV `on unknown address 0x000000000000` (or a small offset like
`0x000000000010`) is a NULL/near-NULL dereference. The small offset is the
field offset inside a struct that was NULL.

## Where the patch usually goes

The crash frame *is* often close to the fix here (unlike other classes), but the
fix is the **missing check**, one of:

- an allocation (`malloc`/`calloc`/project allocator) whose NULL return was not
  checked before use;
- a lookup/parse function that can legitimately return NULL (not found / EOF /
  malformed) whose result is dereferenced unconditionally;
- an optional field assumed present.

## Localization checklist

- Identify the dereferenced pointer and the small offset → which struct/field.
- Trace where that pointer was last assigned: which function produced it, and
  can it return NULL? Read that function's failure paths.
- Candidate #1: the dereference site missing the `if (p == NULL)` guard.
  Candidate #2: the producer that returns NULL on a path the caller didn't
  expect.
- bug_class: `null-pointer-dereference`.
