"""Regression: an abandoned (timed-out) source thread must not roll back a sibling.

Reproduces the 2026-07-08 incident shape:
  t0  source B reads the sources list  (A has 112 prospects)
  t1  source A pulls, appends 33 -> 145, persists
  t2  source B's ABANDONED thread finishes and persists what it read at t0
Before the fix, t2 rewrote every doc and A went back to 112.
"""
import sys, threading, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import server

STORE = {}  # id -> doc, the "sources" table

def fake_sb(method, path, body=None, prefer=""):
    if method == "POST" and path.startswith("sources?on_conflict=id"):
        for row in body:
            STORE[row["id"]] = row["doc"]
        return []
    if method == "GET" and path.startswith("sources?select=id"):
        return [{"id": k} for k in STORE]
    return []

server.sb = fake_sb

def reset():
    STORE.clear()
    STORE["A"] = {"id": "A", "prospects": list(range(112)), "last_pull": "15:05"}
    STORE["B"] = {"id": "B", "prospects": [], "last_pull": None}

def scenario(persist_a, persist_b, use_flag):
    """persist_*: callable(doc_snapshot) -> writes. Returns len(A.prospects) after."""
    reset()
    b_snapshot = [dict(d) for d in STORE.values()]        # B reads the whole list at t0
    a_doc = dict(STORE["A"]); a_doc["prospects"] = list(range(145))  # A pulls +33
    persist_a(a_doc)

    done = threading.Event()
    def b_zombie():
        if use_flag:
            th = threading.current_thread()
            th._navreo_abandoned = threading.Event()
            th._navreo_abandoned.set()           # the watchdog already gave up on us
        persist_b(b_snapshot)
        done.set()
    t = threading.Thread(target=b_zombie); t.start(); done.wait(5)
    return len(STORE["A"]["prospects"])

fails = []
def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  (A.prospects={got}, want {want})")
    if not ok: fails.append(name)

print("\nold behaviour: whole-list write from a zombie thread, no flag")
check("clobbers the sibling back to 112",
      scenario(lambda d: server._pg_replace("sources", [d, STORE["B"]]),
               lambda snap: server._pg_replace("sources", snap),
               use_flag=False), 112)

print("\nfix 1 - row-scoped write_source(): zombie touches only its own row")
check("sibling survives at 145",
      scenario(server.write_source,
               lambda snap: [server.write_source(d) for d in snap if d["id"] == "B"],
               use_flag=False), 145)

print("\nfix 2 - abandoned flag: even a whole-list write is refused")
check("sibling survives at 145",
      scenario(server.write_source,
               lambda snap: server.write_drafts(snap),
               use_flag=True), 145)

print("\nsanity - a NON-abandoned thread still persists normally")
reset()
def live():
    d = dict(STORE["B"]); d["prospects"] = [1, 2, 3]
    server.write_source(d)
t = threading.Thread(target=live); t.start(); t.join()
check("live thread's own write lands", len(STORE["B"]["prospects"]), 3)

print("\n" + ("ALL PASS" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
