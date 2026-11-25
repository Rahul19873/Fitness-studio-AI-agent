"""Checks that need no internet and no API key.   Run:  uv run test_offline.py"""
import inspect
import os
import tempfile
from pathlib import Path

os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.db")   # never touches real data

import agent
import store
import tools
from agent import FrontDesk

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok    {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")


# silence owner alerts but record them
alerts = []
tools.notify_owner = lambda m: alerts.append(m)

print("Phone numbers")
n = tools.normalize_phone
check("plain 10 digits", n("9876543210") == "9876543210")
check("+91 with spaces", n("+91 98765 43210") == "9876543210")
check("leading 0", n("09876543210") == "9876543210")
check("too short rejected", n("98765") is None)
check("starts with 5 rejected", n("5876543210") is None)
check("empty rejected", n("") is None)

print("save_lead tool")
save, handoff = tools.make_tools("gym", "s1")
check("refuses without consent", save("Amit", "9876543210", "gym", False)["saved"] is False)
check("refuses bad phone", save("Amit", "123", "gym", True)["saved"] is False)
check("refuses empty name", save("  ", "9876543210", "gym", True)["saved"] is False)
check("nothing stored so far", store.list_leads() == [])
r = save("Amit", "+91 98765 43210", "monthly plan", True, "Monday 7am", "visit_request")
check("saves a valid lead", r["saved"] is True)
r2 = save("Amit", "9876543210", "monthly plan", True, "Monday 7am", "visit_request")
check("retry does not duplicate", r2["lead_id"] == r["lead_id"] and len(store.list_leads()) == 1)
check("owner alerted once", len(alerts) == 1 and "VISIT REQUEST" in alerts[0])
save("Ravi", "9123456789", "yoga", True, kind="weird")
check("unknown kind becomes enquiry", store.list_leads()[0]["kind"] == "enquiry")
h = handoff("refund request", "I want my money back")
check("hand-off recorded", h["handoff_requested"] and len(store.list_handoffs()) == 1)

print("Tools are readable by the model")
for fn in (save, handoff):
    check(f"{fn.__name__} has docstring + type hints",
          bool(inspect.getdoc(fn)) and all(p.annotation is not inspect._empty
                                           for p in inspect.signature(fn).parameters.values()))

print("Storage")
store.log_message("gym", "s1", "user", "hello")
check("old chat logs are purged", store.purge_old_messages(days=-1) == 1)
out = Path(os.environ["DB_PATH"]).parent / "leads.csv"
check("CSV export works", store.export_leads_csv(out) == 2 and "Amit" in out.read_text(encoding="utf-8-sig"))

print("Prompt")
bot = FrontDesk()
check("business name filled in", "Sample Fitness Studio" in bot.system_prompt)
check("business info included", "Rs 1,500" in bot.system_prompt)
check("no unfilled placeholders", "__NAME__" not in bot.system_prompt and "__INFO__" not in bot.system_prompt)
check("greeting says it is an AI", "AI" in bot.greeting())


# ---- fake Gemini chats to test retry / model fallback ----
class Resp:
    def __init__(self, t): self.text = t


class FakeChat:
    def __init__(self, script, history): self.script, self.history = list(script), list(history)
    def send_message(self, text):
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        self.history.append(text)
        return Resp(step)
    def get_history(self): return self.history


def make_bot(scripts):
    """scripts: one list of outcomes per model, tried in order."""
    b = FrontDesk()
    used = []
    def _new_chat(model, history):
        used.append((model, list(history)))
        return FakeChat(scripts[len(used) - 1] if len(used) <= len(scripts) else ["late ok"], history)
    b._new_chat = _new_chat
    b.used = used
    return b


agent.time.sleep = lambda s: None
agent.sys.stderr = open(os.devnull, "w")   # hide expected error lines

print("Retry and model fallback")
b = make_bot([[Exception("503 UNAVAILABLE"), Exception("503 UNAVAILABLE")], ["Hello from model 2"]])
check("busy model -> falls back and answers", b.reply("hi") == "Hello from model 2")
check("used two different models", len(b.used) == 2 and b.used[0][0] != b.used[1][0])

b = make_bot([[Exception("503 UNAVAILABLE"), "recovered on retry"]])
check("one hiccup -> retry on same model", b.reply("hi") == "recovered on retry" and len(b.used) == 1)

b = make_bot([[Exception("404 NOT_FOUND model")], ["next model answers"]])
check("unavailable model skipped immediately", b.reply("hi") == "next model answers")

b = make_bot([[Exception("403 PERMISSION_DENIED API key invalid")]])
try:
    b.reply("hi"); raised = False
except Exception:
    raised = True
check("bad API key stops (no pointless retries)", raised)

before = len(store.list_handoffs())
b = make_bot([[Exception("503")] * 2] * len(b.models))
ans = b.reply("what is the fee?")
check("everything down -> polite reply", ans == agent.BUSY_REPLY)
check("customer message saved as hand-off", len(store.list_handoffs()) == before + 1
      and store.list_handoffs()[0]["last_message"] == "what is the fee?")
b._new_chat = lambda model, history: FakeChat(["back online"], history)
check("next message works after an outage", b.reply("hello again") == "back online")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
