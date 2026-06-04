"""Tools the agent can call. Read tools are read-only over the task source tree;
write tools mutate external memory. All dispatched via a text JSON action."""
import os
import re

TEXT_EXT = {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".inc",
            ".py", ".js", ".ts", ".go", ".rs", ".java", ".sh", ".txt",
            ".md", ".cfg", ".conf", ".am", ".ac", ".in", ".m4", ".y", ".l"}
SKIP_DIRS = {".git", "node_modules", ".svn", "build", "CMakeFiles"}
MAX_FILE_BYTES = 2_000_000


class Tools:
    def __init__(self, browse_root: str, memory):
        self.root = os.path.abspath(browse_root)
        self.mem = memory
        self.done = False
        self.read_lines = {}  # file -> set of line numbers actually read (for groundedness)
        self.challenge_count = 0

    def _resolve(self, rel):
        p = os.path.abspath(os.path.join(self.root, rel or ""))
        if not (p == self.root or p.startswith(self.root + os.sep)):
            raise ValueError(f"path escapes source root: {rel}")
        return p

    def _find_file(self, path):
        """Tolerant lookup: exact, else strip junk prefixes, else suffix/basename
        match across the tree. Returns (abs_path, rel_path) or (None, candidates)."""
        if not path:
            return None, []
        cand = os.path.join(self.root, path)
        if os.path.isfile(cand):
            return cand, os.path.relpath(cand, self.root)
        norm = path.replace("\\", "/").lstrip("/")
        # drop a leading copy of the browse-root dir name if the model included it
        rootname = os.path.basename(self.root)
        norm = re.sub(rf"^.*?{re.escape(rootname)}/", "", norm)
        cand = os.path.join(self.root, norm)
        if os.path.isfile(cand):
            return cand, os.path.relpath(cand, self.root)
        base = norm.split("/")[-1]
        suffix_hits, base_hits = [], []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fn), self.root)
                if rel.endswith(norm):
                    suffix_hits.append(rel)
                elif fn == base:
                    base_hits.append(rel)
        hits = suffix_hits or base_hits
        if len(hits) == 1:
            return os.path.join(self.root, hits[0]), hits[0]
        return None, hits[:8]

    # ---- read ------------------------------------------------------------
    def list_files(self, subdir="", max_results=200):
        base = self._resolve(subdir)
        if not os.path.isdir(base) and subdir:
            rootname = os.path.basename(self.root)
            stripped = re.sub(rf"^.*?{re.escape(rootname)}/?", "", subdir.replace("\\", "/"))
            cand = self._resolve(stripped)
            base = cand if os.path.isdir(cand) else self.root
        out = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, self.root)
                out.append(rel)
                if len(out) >= max_results:
                    return f"{len(out)} files (truncated):\n" + "\n".join(sorted(out))
        return f"{len(out)} files:\n" + "\n".join(sorted(out))

    def read_file(self, path, start=1, end=None):
        p, rel = self._find_file(path)
        if p is None:
            if rel:
                return (f"ERROR: '{path}' not found. Did you mean one of these "
                        f"(use the exact path)?\n" + "\n".join(rel))
            return f"ERROR: '{path}' not found. Call list_files to see the layout."
        if os.path.getsize(p) > MAX_FILE_BYTES:
            return f"ERROR: file too large: {rel}"
        with open(p, "r", errors="replace") as f:
            lines = f.readlines()
        start = max(1, int(start))
        end = int(end) if end else min(len(lines), start + 199)
        end = min(end, len(lines))
        chunk = []
        for i in range(start, end + 1):
            chunk.append(f"{i:6}| {lines[i-1].rstrip(chr(10))}")
            self.read_lines.setdefault(rel, set()).add(i)
        header = f"{rel} lines {start}-{end} of {len(lines)}"
        return header + "\n" + "\n".join(chunk)

    def search_code(self, pattern, max_results=40):
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"ERROR: bad regex: {e}"
        hits = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() not in TEXT_EXT:
                    continue
                full = os.path.join(dirpath, fn)
                if os.path.getsize(full) > MAX_FILE_BYTES:
                    continue
                rel = os.path.relpath(full, self.root)
                try:
                    with open(full, "r", errors="replace") as f:
                        for ln, line in enumerate(f, 1):
                            if rx.search(line):
                                hits.append(f"{rel}:{ln}: {line.strip()[:160]}")
                                if len(hits) >= max_results:
                                    return f"{len(hits)} hits (truncated):\n" + "\n".join(hits)
                except OSError:
                    continue
        return f"{len(hits)} hits:\n" + "\n".join(hits) if hits else "no matches"

    # ---- write (memory) --------------------------------------------------
    def add_note(self, text):
        return self.mem.add_note(text)

    def add_evidence(self, **kw):
        amap = {"type": "ev_type", "evidence_type": "ev_type", "filepath": "file",
                "content": "note", "text": "note", "reason": "note"}
        kw = {amap.get(k, k): v for k, v in kw.items()}
        # accept a single "location" string like "path/file.c:1879" or "...:1879-1906"
        loc = kw.pop("location", None)
        if loc and "file" not in kw:
            m = re.match(r"\s*(.+?):(\d+)(?:-(\d+))?\s*$", str(loc))
            if m:
                kw["file"] = m.group(1)
                kw["line_start"] = int(m.group(2))
                kw["line_end"] = int(m.group(3)) if m.group(3) else int(m.group(2))
            else:
                kw["file"] = str(loc)
        allowed = {"ev_type", "file", "line_start", "line_end", "snippet",
                   "note", "supports", "contradicts"}
        kw = {k: v for k, v in kw.items() if k in allowed}
        return "evidence " + self.mem.add_evidence(**kw)

    def upsert_hypothesis(self, **kw):
        amap = {"id": "hyp_id", "evidence": "evidence_refs", "filepath": "file",
                "description": "claim", "summary": "claim", "detail": "claim",
                "note": "claim", "notes": "claim"}
        kw = {amap.get(k, k): v for k, v in kw.items()}
        loc = kw.pop("location", None)
        if loc and ("file" not in kw or "line" not in kw):
            m = re.match(r"\s*(.+?):(\d+)(?:-\d+)?\s*$", str(loc))
            if m:
                kw.setdefault("file", m.group(1))
                kw.setdefault("line", int(m.group(2)))
            else:
                kw.setdefault("file", str(loc))
        allowed = {"hyp_id", "claim", "file", "function", "line", "bug_class",
                   "status", "confidence", "evidence_refs"}
        kw = {k: v for k, v in kw.items() if k in allowed}
        return "hypothesis " + self.mem.upsert_hypothesis(**kw)

    def add_todo(self, text):
        return "todo " + self.mem.add_todo(text)

    def complete_todo(self, tid):
        return self.mem.complete_todo(tid)

    def update_graph(self, nodes=None, edges=None):
        return self.mem.update_graph(nodes=nodes, edges=edges)

    def challenge(self, text):
        """Record a counter-analysis: argue why the root cause might be elsewhere
        (e.g. an upstream initializer/validator the patch would actually fix)."""
        self.challenge_count += 1
        self.mem.add_note("CHALLENGE: " + text)
        return "challenge recorded"

    def _location_read(self, file, line):
        if not file or not line:
            return False
        try:
            ln = int(line)
        except (ValueError, TypeError):
            return False
        for rf, lines in self.read_lines.items():
            if (rf.endswith(file) or file.endswith(rf)
                    or rf.split("/")[-1] == str(file).split("/")[-1]):
                if any(abs(ln - x) <= 15 for x in lines):
                    return True
        return False

    def conclude(self, summary=""):
        if not self.mem.hypotheses:
            return ("ERROR: cannot conclude — record your candidate(s) first with "
                    "upsert_hypothesis (file/function/line/bug_class/confidence). "
                    "This is the most important deliverable.")
        ungrounded = [h["id"] for h in self.mem.hypotheses.values()
                      if not self._location_read(h.get("file"), h.get("line"))]
        if ungrounded:
            return (f"ERROR: hypotheses {ungrounded} point at a file:line you have "
                    f"not read. read_file that exact location first (so the claim is "
                    f"grounded), or fix the hypothesis line, then conclude.")
        self.done = True
        if summary:
            self.mem.add_note("CONCLUSION: " + summary)
        return "concluded"

    # ---- dispatch --------------------------------------------------------
    _ALIASES = {
        "list_files": {"path": "subdir", "directory": "subdir", "dir": "subdir",
                       "subdirectory": "subdir", "max": "max_results", "limit": "max_results"},
        "read_file": {"start_line": "start", "end_line": "end", "from": "start",
                      "to": "end", "line_start": "start", "line_end": "end",
                      "begin": "start", "line": "start", "file": "path",
                      "filepath": "path", "filename": "path"},
        "search_code": {"query": "pattern", "regex": "pattern", "q": "pattern",
                        "max": "max_results", "limit": "max_results"},
        "add_note": {"note": "text", "content": "text"},
        "challenge": {"note": "text", "content": "text", "argument": "text",
                      "counter": "text", "challenge": "text"},
        "add_todo": {"todo": "text", "task": "text", "content": "text"},
        "complete_todo": {"id": "tid", "todo_id": "tid"},
        "conclude": {"text": "summary", "conclusion": "summary",
                     "result": "summary", "findings": "summary",
                     "root_cause": "summary"},
    }

    def dispatch(self, name, args):
        import inspect
        fn = getattr(self, name, None)
        if not callable(fn) or name.startswith("_") or name in ("dispatch",):
            return f"ERROR: unknown tool '{name}'. See the action list."
        if not isinstance(args, dict):
            args = {"text": args} if name in ("add_note", "add_todo", "challenge", "conclude") else {}
        amap = self._ALIASES.get(name, {})
        args = {amap.get(k, k): v for k, v in args.items()}
        sig = inspect.signature(fn)
        has_var_kw = any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())
        if not has_var_kw:
            allowed = set(sig.parameters)
            args = {k: v for k, v in args.items() if k in allowed}
        try:
            return fn(**args)
        except Exception as e:
            return f"ERROR: {name} failed: {e}"


TOOL_SPEC = """\
Available actions (call exactly ONE per turn). Read tools inspect the target
source tree (read-only). Write tools update your external memory.

READ:
  list_files     {"subdir": "<rel dir, '' for root>", "max_results": 200}
  read_file      {"path": "<rel path>", "start": <int>, "end": <int>}
  search_code    {"pattern": "<python regex>", "max_results": 40}

MEMORY (write):
  add_note          {"text": "<free reasoning>"}
  add_evidence      {"ev_type":"code|crashlog|dataflow|control|sanitizer",
                     "file":"<path>","line_start":<int>,"line_end":<int>,
                     "snippet":"<code>","note":"<why it matters>",
                     "supports":["H1"],"contradicts":[]}
                     -> returns an evidence id like "E1"; use it in evidence_refs.
  upsert_hypothesis {"hyp_id":"H1 (omit to create)","claim":"...",
                     "file":"<path>","function":"<fn>","line":<int>,
                     "bug_class":"<e.g. uninitialized-read>",
                     "status":"open|supported|refuted","confidence":0.0-1.0,
                     "evidence_refs":["E1"]}   <- MUST reference real E-ids
  challenge         {"text":"why the patch location might be ELSEWHERE (e.g. an
                     upstream init/validation fn), and what you checked"}
  add_todo          {"text":"..."}   complete_todo {"tid":"T1"}
  update_graph      {"nodes":[{"id":"n1","type":"sink","label":"..."}],
                     "edges":[{"src":"n1","dst":"n2","type":"reaches","evidence_refs":["E1"]}]}

FINISH:
  conclude       {"summary":"which hypothesis is the root cause and why"}
  (rejected unless: >=1 hypothesis, each grounded in a real E-id, and >=1 challenge done)
"""
