"""External memory: the agent's scratch paper.

The whole point of L2 is that the model has limited context, so reasoning state
lives in files, not in the chat history. Every turn the agent reads a *compact
view* of this state, takes one action, and writes back a structured delta.
"""
import json
import os


class Memory:
    def __init__(self, run_dir: str):
        self.run_dir = run_dir
        os.makedirs(run_dir, exist_ok=True)
        self.hypotheses = {}   # id -> dict
        self.evidence = []     # list of dict
        self.graph = {"nodes": [], "edges": []}
        self.notes = []        # list of str
        self.todos = []        # list of {id, text, status}
        self._hyp_seq = 0
        self._ev_seq = 0
        self._todo_seq = 0

    # ---- mutations -------------------------------------------------------
    def add_note(self, text: str):
        self.notes.append(text)
        self._flush()
        return "note recorded"

    def add_evidence(self, ev_type="code", file=None, line_start=None, line_end=None,
                     snippet="", note="", supports=None, contradicts=None):
        self._ev_seq += 1
        eid = f"E{self._ev_seq}"
        self.evidence.append({
            "id": eid, "type": ev_type, "file": file,
            "line_start": line_start, "line_end": line_end,
            "snippet": (snippet or "")[:500], "note": note,
            "supports": supports or [], "contradicts": contradicts or [],
        })
        self._flush()
        return eid

    def upsert_hypothesis(self, hyp_id=None, claim=None, file=None, function=None,
                          line=None, bug_class=None, status=None,
                          confidence=None, evidence_refs=None):
        if hyp_id is not None:
            hyp_id = str(hyp_id)
        if hyp_id and hyp_id in self.hypotheses:
            h = self.hypotheses[hyp_id]
        else:
            self._hyp_seq += 1
            hyp_id = hyp_id or f"H{self._hyp_seq}"
            h = {"id": hyp_id, "claim": "", "file": None, "function": None,
                 "line": None, "bug_class": None, "status": "open",
                 "confidence": 0.0, "evidence_refs": []}
            self.hypotheses[hyp_id] = h
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (ValueError, TypeError):
                confidence = None
        for k, v in [("claim", claim), ("file", file), ("function", function),
                     ("line", line), ("bug_class", bug_class),
                     ("status", status), ("confidence", confidence)]:
            if v is not None:
                h[k] = v
        if evidence_refs:
            for r in evidence_refs:
                if r not in h["evidence_refs"]:
                    h["evidence_refs"].append(r)
        self._flush()
        return hyp_id

    def add_todo(self, text):
        self._todo_seq += 1
        tid = f"T{self._todo_seq}"
        self.todos.append({"id": tid, "text": text, "status": "open"})
        self._flush()
        return tid

    def complete_todo(self, tid):
        for t in self.todos:
            if t["id"] == tid:
                t["status"] = "done"
        self._flush()
        return "ok"

    def update_graph(self, nodes=None, edges=None):
        existing = {n["id"] for n in self.graph["nodes"]}
        for n in nodes or []:
            if n.get("id") and n["id"] not in existing:
                self.graph["nodes"].append(n)
                existing.add(n["id"])
        for e in edges or []:
            self.graph["edges"].append(e)
        self._flush()
        return "graph updated"

    # ---- views -----------------------------------------------------------
    def compact_view(self) -> str:
        lines = []
        lines.append("## HYPOTHESES")
        if self.hypotheses:
            for h in sorted(self.hypotheses.values(),
                            key=lambda x: -(x.get("confidence") or 0)):
                loc = f"{h.get('file')}:{h.get('line')}"
                lines.append(
                    f"  [{h['id']}] {h['status']} conf={h.get('confidence'):.2f} "
                    f"{h.get('bug_class')} @ {loc} fn={h.get('function')} "
                    f"refs={h.get('evidence_refs')}\n      {h.get('claim')}")
        else:
            lines.append("  (none yet)")

        lines.append("## OPEN TODOS")
        open_todos = [t for t in self.todos if t["status"] == "open"]
        if open_todos:
            for t in open_todos:
                lines.append(f"  [{t['id']}] {t['text']}")
        else:
            lines.append("  (none)")

        lines.append("## RECENT EVIDENCE (last 8)")
        if self.evidence:
            for e in self.evidence[-8:]:
                rng = f":{e['line_start']}-{e['line_end']}" if e["line_start"] else ""
                lines.append(f"  [{e['id']}] {e['type']} {e['file']}{rng} "
                             f"supports={e['supports']} :: {e['note']}")
        else:
            lines.append("  (none yet)")

        if self.graph["edges"]:
            lines.append("## GRAPH EDGES")
            for e in self.graph["edges"][-12:]:
                lines.append(f"  {e.get('src')} --{e.get('type')}--> {e.get('dst')}")
        return "\n".join(lines)

    def final_hypotheses(self):
        return sorted(self.hypotheses.values(),
                      key=lambda x: -(x.get("confidence") or 0))

    # ---- persistence -----------------------------------------------------
    def _flush(self):
        d = self.run_dir
        with open(os.path.join(d, "hypotheses.jsonl"), "w") as f:
            for h in self.hypotheses.values():
                f.write(json.dumps(h, ensure_ascii=False) + "\n")
        with open(os.path.join(d, "evidence.jsonl"), "w") as f:
            for e in self.evidence:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        with open(os.path.join(d, "graph.json"), "w") as f:
            json.dump(self.graph, f, ensure_ascii=False, indent=2)
        with open(os.path.join(d, "todo.json"), "w") as f:
            json.dump(self.todos, f, ensure_ascii=False, indent=2)
        with open(os.path.join(d, "notes.md"), "w") as f:
            f.write("\n\n".join(self.notes))
