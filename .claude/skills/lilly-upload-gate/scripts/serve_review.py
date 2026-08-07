#!/usr/bin/env python3
"""Serve a lilly-upload-gate report for interactive review: fix, drop, or
override every flag directly on the page.

Usage: serve_review.py <run_result.json> [port]

GET  /               -> the review page, re-rendered with current decisions
POST /api/fix        -> {id, value}   POST /api/fixall -> {check}
POST /api/drop       -> {email}       POST /api/dropall -> {check?}
POST /api/override   -> {ids}         POST /api/confirm -> {item}
POST /api/upload     -> {mode: approve|force}
GET  /api/state, GET /api/rows

Every decision requires "by". Email verification has NO in-page action —
unverified leads are re-verified in chat (lilly-email-verification) or dropped.
Decisions persist to <run>.decisions.json.
"""
import json, sys, pathlib, datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render_report as rr

RUN_FILE = pathlib.Path(sys.argv[1]).resolve()
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 7912
DEC_FILE = RUN_FILE.with_suffix(".decisions.json")
RUN = rr.normalise_run(json.loads(RUN_FILE.read_text()))


def load():
    return json.loads(DEC_FILE.read_text()) if DEC_FILE.exists() else []


def save(decisions):
    DEC_FILE.write_text(json.dumps(decisions, indent=1))


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, default=str), "application/json")

    def do_GET(self):
        dec = load()
        if self.path.startswith("/api/state"):
            state, dropped, _ = rr.resolve(RUN, dec)
            self._json(200, {"decisions": dec, "gate": rr.gate_state(RUN, dec),
                             "open": sum(1 for s, _ in state.values() if s == "open"),
                             "dropped": sorted(dropped),
                             "upload": next((x for x in dec if x.get("action") == "upload"), None)})
        elif self.path.startswith("/api/rows"):
            self._json(200, rr.working_rows(RUN, dec))
        else:
            self._send(200, rr.render(RUN, dec, live=True))

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        except (ValueError, TypeError):
            return self._send(400, "bad request", "text/plain")
        dec = load()
        flags = RUN["flags"]
        by = (body.get("by") or "").strip()
        if not by:
            return self._send(400, "a reviewer name ('by') is required on every decision", "text/plain")

        def ok():
            save(dec)
            return self._json(200, {"ok": True, "gate": rr.gate_state(RUN, dec)})

        if self.path.startswith("/api/fixall") or self.path == "/api/fix" or self.path.startswith("/api/fix?"):
            todo = []
            if self.path.startswith("/api/fixall"):
                check = body.get("check")
                seen = set()
                for i, f in enumerate(flags):
                    if f["check"] != check or (f["email"], f["field"]) in seen:
                        continue
                    _, suggest = rr.humanise(f)
                    if suggest:
                        seen.add((f["email"], f["field"]))
                        todo.append((i, suggest))
                if not todo:
                    return self._send(400, "no suggested fixes in that check", "text/plain")
            else:
                i, value = body.get("id"), (body.get("value") or "").strip()
                if not (isinstance(i, int) and 0 <= i < len(flags)) or not value:
                    return self._send(400, "invalid flag id or empty value", "text/plain")
                todo = [(i, value)]
            is_bulk = self.path.startswith("/api/fixall")
            existing = {(x["email"], x["field"]): x for x in dec if x["action"] == "fixed"}
            for i, value in todo:
                f = flags[i]
                pair = (f["email"], f["field"])
                resolved = [j for j, g in enumerate(flags)
                            if (g["email"], g["field"]) == pair and g["check"] == f["check"]]
                if pair in existing and is_bulk:
                    continue  # bulk never clobbers a deliberate manual re-fix
                if pair in existing:  # explicit re-fix updates the value, never a silent no-op
                    existing[pair].update({"value": value, "at": now(), "by": by,
                                           "flag_ids": resolved})
                else:
                    x = {"action": "fixed", "id": i, "email": f["email"], "field": f["field"],
                         "value": value, "flag_ids": resolved, "at": now(), "by": by}
                    dec.append(x)
                    existing[pair] = x
            return ok()

        if self.path.startswith("/api/dropall"):
            check = body.get("check")
            state, _, _ = rr.resolve(RUN, dec)
            emails = {flags[i]["email"] for i, (st, _) in state.items()
                      if st == "open" and (not check or flags[i]["check"] == check)}
            if not emails:
                return self._send(400, "no open flags to drop", "text/plain")
            done = {x["email"] for x in dec if x["action"] == "dropped"}
            for e in sorted(emails):
                if e not in done:
                    dec.append({"action": "dropped", "email": e, "at": now(), "by": by})
            return ok()

        if self.path.startswith("/api/drop"):
            email = (body.get("email") or "").strip()
            if not any(r["email"] == email for r in RUN.get("rows", [])):
                return self._send(400, "unknown email", "text/plain")
            if email not in {x["email"] for x in dec if x["action"] == "dropped"}:
                dec.append({"action": "dropped", "email": email,
                            "check": body.get("check"), "at": now(), "by": by})
            return ok()

        if self.path.startswith("/api/confirm"):
            item = (body.get("item") or "").strip()
            if item not in RUN.get("checklist", []):
                return self._send(400, "unknown checklist item", "text/plain")
            if item not in {x["item"] for x in dec if x["action"] == "confirmed"}:
                dec.append({"action": "confirmed", "item": item, "at": now(), "by": by})
            return ok()

        if self.path.startswith("/api/override"):
            ids, reason = body.get("ids"), (body.get("reason") or "").strip() or None
            if not ids or not all(isinstance(i, int) and 0 <= i < len(flags) for i in ids):
                return self._send(400, "invalid flag ids", "text/plain")
            # deliverability is verify-or-drop, NEVER approved: every uploading
            # lead must hold a real verified verdict (cache/AI-Ark/ListMint/MV)
            ev = [i for i in ids if flags[i]["check"] == "email_verification"]
            if ev:
                return self._send(400, "unverified emails can't be approved — use "
                                  "'Verify remaining now', re-run verification in chat, "
                                  "or drop those leads", "text/plain")
            state, _, _ = rr.resolve(RUN, dec)
            bad = [i for i in ids if state[i][0] not in ("open", "overridden")]
            if bad:
                return self._send(400, f"flags {bad} are already fixed/dropped/verified — nothing to approve", "text/plain")
            existing = {x["id"]: x for x in dec if x["action"] == "overridden"}
            for i in ids:
                if i in existing:
                    existing[i].update({"reason": reason, "at": now(), "by": by})
                else:
                    f = flags[i]
                    dec.append({"action": "overridden", "id": i, "check": f["check"],
                                "email": f["email"], "field": f["field"],
                                "reason": reason, "at": now(), "by": by})
            return ok()

        if self.path.startswith("/api/upload"):
            mode = body.get("mode")
            if mode not in ("approve", "force"):
                return self._send(400, "mode must be 'approve' or 'force'", "text/plain")
            if any(x.get("action") == "upload" for x in dec):
                return self._json(200, {"ok": True, "already": True})
            g = rr.gate_state(RUN, dec)
            if mode == "approve" and g in ("BLOCKED", "CONFIRM CHECKLIST"):
                state, _, _ = rr.resolve(RUN, dec)
                open_by_check = {}
                for i, (st, _) in state.items():
                    if st == "open":
                        k = RUN["flags"][i]["check"]
                        open_by_check[k] = open_by_check.get(k, 0) + 1
                first = next((k for k in RUN["results"] if open_by_check.get(k)), None)
                msg = ("Can't upload yet — " + ", ".join(
                    f"{n} open in {rr.CHECK_LABELS.get(k, k)}" for k, n in open_by_check.items())
                    + ". Fix, drop, verify, or approve them first."
                    if open_by_check else "Can't upload yet — the routine checklist isn't confirmed.")
                return self._json(409, {"blocked": True, "gate": g, "open": open_by_check,
                                        "first_fail": first, "message": msg})
            dec.append({"action": "upload", "mode": "forced" if mode == "force" else "approved",
                        "gate_at_upload": g, "at": now(), "by": by})
            return ok()

        self._send(404, "not found", "text/plain")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Review server: http://localhost:{PORT}  (decisions -> {DEC_FILE})")
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
