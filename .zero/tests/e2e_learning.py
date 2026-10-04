r"""Live end-to-end check (needs .env keys + network, ~1 min, ~$0.01) of notes recall + the feedback loop, through the real CEO.

    cd K:\Zero\.zero && set PYTHONIOENCODING=utf-8 && K:\Zero\.venv\Scripts\python.exe tests\e2e_learning.py


Leaves nothing behind: hot memory goes to a temp file, and every interaction,
feedback doc, feedback.jsonl line and skill this creates is removed at the end.
"""
import json
import logging
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
logging.disable(logging.CRITICAL)
from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

import memory.hot as hot
hot._STORE = Path(tempfile.mkdtemp()) / "hot.jsonl"     # keep Cyph's conversation clean
hot.hot_memory._entries.clear()

from core.ceo import ceo
from core.feedback import record, _LOG
from memory.cold import cold_memory
from skills.skill_store import Skill, skill_store

created_interactions: list[str] = []
log_size_before = _LOG.stat().st_size if _LOG.exists() else 0
ok = True

def check(cond: bool, label: str) -> None:
    global ok
    ok &= cond
    print(("  PASS " if cond else "  FAIL ") + label)

try:
    print("1. Notes reach the prompt only when relevant")
    ctx_on = ceo._load_memory_context("what is my dissertation about")
    ctx_off = ceo._load_memory_context("India Pakistan cricket result")
    check("From Cyph's own notes" in ctx_on, "dissertation question pulls his notes")
    check("From Cyph's own notes" not in ctx_off, "cricket question sends no notes")

    print("\n2. A real answer, through the whole pipeline")
    skills_before = {s.id for s in skill_store.load_all()}
    ctx = ceo.handle("in two sentences, what is my dissertation about?")
    created_interactions.append(ctx.memory_id)
    print("   agents:", [a.name for a in ctx.selected_agents], "| model:", ctx.model_used)
    print("   " + ctx.final_response.replace("\n", " ")[:420])
    low = ctx.final_response.lower()
    check(any(w in low for w in ("event camera", "event-camera", "event-based", "event-driven", "spiking", "fluctlite", "neuromorphic")),
          "answer is about HIS dissertation (event cameras / spiking nets)")
    check(ctx.memory_id.startswith("interaction_"), "answer carries an id for the 👍/👎 buttons")
    check({s.id for s in skill_store.load_all()} == skills_before,
          "an UNRATED answer teaches no route")

    print("\n3. 👎 is remembered and steers a similar question")
    msg = record(ctx.memory_id, -1)
    print("   bot says:", msg)
    steer = ceo._load_memory_context("what's my dissertation about, briefly?")
    check("rated this answer 👎" in steer, "similar question now sees the 👎")
    check("rated this answer" not in ceo._load_memory_context("weather in Manchester"),
          "unrelated question is not steered")
    msg = record(ctx.memory_id, +1)
    print("   bot says:", msg)
    steer = ceo._load_memory_context("what's my dissertation about, briefly?")
    check("rated this answer 👍" in steer and "👎" not in steer, "re-rating 👍 replaces the 👎")
    learned = {s.id for s in skill_store.load_all()} - skills_before
    check(len(learned) == 1 and "Learned the route" in msg, "👍 on a multi-agent answer teaches the route")

    print("\n4. 👎 deletes the learned skill that routed the answer")
    fake = Skill(id="e2e_test_skill", name="e2e_test_skill", description="test",
                 trigger_phrases=["zorblax quarterly frobnication report"],
                 agent_sequence=["research", "study"], synthesis_hint="")
    skill_store.save(fake)
    q = "zorblax quarterly frobnication report"
    mid = cold_memory.store_interaction(q, "a test answer", ["research", "study"])
    created_interactions.append(mid)
    print("   bot says:", record(mid, -1))
    check(not any(s.id == "e2e_test_skill" for s in skill_store.load_all()), "bad skill deleted")

    print("\n5. Every rating is in the dataset")
    lines = _LOG.read_text(encoding="utf-8").splitlines() if _LOG.exists() else []
    mine = [json.loads(l) for l in lines if any(i in l for i in created_interactions)]
    check(len(mine) == 3 and {m["rating"] for m in mine} == {1, -1}, "3 ratings logged with query + answer")
finally:
    for mid in created_interactions:
        cold_memory.delete("interactions", mid)
        cold_memory.delete("feedback", f"fb_{mid}")
    skill_store.delete("e2e_test_skill")
    for sid in {s.id for s in skill_store.load_all()} - skills_before:   # learned by the test's 👍
        skill_store.delete(sid)
    if _LOG.exists():
        with _LOG.open("r+b") as f:
            f.truncate(log_size_before)
    print("\ncleaned up:", len(created_interactions), "interactions, their feedback, the test skill")

print("\nALL PASS" if ok else "\nSOME FAILED")
