---
id: temporal-uaf
applies_to: ["heap-use-after-free", "use-after-free", "uaf", "double-free", "invalid-free", "attempting-double-free"]
title: Temporal memory error (use-after-free / double-free)
---

# Skill: localize a temporal memory error (UAF / double-free)

ASan prints the **use** stack, a **freed by** stack, and an **allocated by**
stack. For temporal bugs the **free stack is the highest-signal evidence** — it
shows who relinquished the object too early or twice.

## Where the patch usually goes

- **Use-after-free**: an object is freed on one path while another live
  reference still uses it. The fix is at the **ownership boundary**: either the
  premature `free`/release is removed/moved, or the dangling pointer is cleared,
  or a reference count is taken. Look at the function on the *free* stack that
  drops the last reference, and at the caller that keeps using the pointer.
- **Double-free**: the same allocation is freed on two paths. Common causes:
  - a shallow copy (`memcpy` of a struct) so two owners hold the same pointer
    and both free it (aliasing). Find the copy site.
  - an error/cleanup path frees, then the normal path frees again. Find the
    missing "set pointer to NULL after free" or the duplicated cleanup.

## Localization checklist

- Compare the **freed-by** and **allocated-by** functions. The bug is usually in
  the freed-by function or its caller (premature/extra free), not the use site.
- For double-free, look for struct copies / aliasing: who else holds this
  pointer? was a `*_dup`/`memcpy`/assignment done without deep-copying the
  owned buffer?
- Candidate #1: the early/duplicate free or the alias-creating copy.
  Candidate #2: the missing NULL-after-free / refcount site.
- bug_class: `use-after-free` / `double-free`.
