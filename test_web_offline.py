"""Web-app checks that need no internet.   Run:  uv run test_web_offline.py"""

from webutil import RateLimiter, render_admin_html, valid_session_id

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok    {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")


print("Session ids")
check("normal uuid accepted", valid_session_id("3f2b8c1e-9a4d-4e2b-8f61-0c7d5a9e1b22"))
check("too short rejected", not valid_session_id("abc"))
check("too long rejected", not valid_session_id("a" * 65))
check("symbols rejected", not valid_session_id("abc12345; DROP TABLE"))
check("empty / None rejected", not valid_session_id("") and not valid_session_id(None))

print("Rate limiter")
now = [1000.0]
rl = RateLimiter(max_calls=3, window=60, clock=lambda: now[0])
check("first 3 allowed", all(rl.allow("1.1.1.1") for _ in range(3)))
check("4th blocked", not rl.allow("1.1.1.1"))
check("other visitor unaffected", rl.allow("2.2.2.2"))
now[0] += 61
check("allowed again after the window", rl.allow("1.1.1.1"))
now[0] += 500
rl.cleanup()
check("idle visitors forgotten (memory stays small)", len(rl._hits) == 0)

print("Owner page is safe")
leads = [{"created_at": 1.0, "kind": "visit_request", "name": "<script>alert(1)</script>",
          "phone": "9876543210", "interest": "gym & yoga", "preferred_time": "Mon \"7am\""}]
hands = [{"created_at": 1.0, "reason": "<img src=x onerror=alert(1)>", "last_message": "refund <b>now</b>"}]
page = render_admin_html(leads, hands, "Gym <Pro>")
check("script tag escaped", "<script>alert(1)" not in page and "&lt;script&gt;" in page)
check("img/onerror escaped", "<img src=x" not in page)
check("business name escaped", "Gym &lt;Pro&gt;" in page)
check("ampersand escaped", "gym &amp; yoga" in page)
check("visit request label readable", "visit request" in page)
check("empty state message", "No leads yet." in render_admin_html([], [], "X"))

print("Chat page")
from chatpage import CHAT_HTML as html
import re
unsafe = re.search(r"\.innerHTML|\.outerHTML|insertAdjacentHTML|document\.write", html)
check("replies inserted as text, not HTML", unsafe is None and "textContent" in html)
check("AI disclosure shown", "AI assistant" in html)
check("nothing stored in the browser", "localStorage" not in html and "sessionStorage" not in html)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
