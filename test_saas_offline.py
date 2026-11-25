"""SaaS-edition checks that need no internet and no web server.   Run:  uv run test_saas_offline.py"""
import ast
import os
import re
import tempfile
from pathlib import Path

os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "saas_test.db")   # never touches real data

import agent
import store
import tenants
from agent import FrontDesk
from chatpage import CHAT_HTML
from webutil import (RateLimiter, csrf_ok, csrf_token, render_landing_html,
                     render_owner_html, render_super_html)

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok    {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except ValueError:
        return True
    return False


print("Business accounts")
check("creates a business", tenants.create_tenant("fitzone-patna", "FitZone Patna", "secret123")["slug"] == "fitzone-patna")
check("web address is lower-cased", tenants.create_tenant("GlowSalon", "Glow Salon", "secret123")["slug"] == "glowsalon")
check("duplicate address refused", raises(tenants.create_tenant, "fitzone-patna", "Other", "secret123"))
for bad in ("a", "-abc", "abc-", "ab c", "x" * 41, "admin", "super", "api", "a/b", "../x"):
    check(f"bad address refused: {bad!r}", raises(tenants.create_tenant, bad, "Name", "secret123"))
check("short password refused", raises(tenants.create_tenant, "newgym", "Name", "short"))
check("empty name refused", raises(tenants.create_tenant, "newgym", " ", "secret123"))
check("huge info refused", raises(tenants.create_tenant, "newgym", "Name", "secret123", "x" * 20001))
check("default info is the template", "## Timings" in tenants.get_tenant("fitzone-patna")["info"])
t = tenants.get_tenant("fitzone-patna")
check("password hash never exposed", "password_hash" not in t)
check("unknown business -> None", tenants.get_tenant("nope-nope") is None and tenants.get_tenant("../etc") is None)

print("Passwords")
check("right password accepted", tenants.verify_tenant("fitzone-patna", "secret123") is not None)
check("wrong password rejected", tenants.verify_tenant("fitzone-patna", "secret124") is None)
check("unknown business rejected", tenants.verify_tenant("ghost-gym", "secret123") is None)
check("hashes are salted (differ each time)", tenants.hash_password("abcdefgh") != tenants.hash_password("abcdefgh"))
check("plain password not stored", "secret123" not in tenants.hash_password("secret123"))
tenants.set_password("fitzone-patna", "brand-new-pass")
check("password change works", tenants.verify_tenant("fitzone-patna", "brand-new-pass") is not None
      and tenants.verify_tenant("fitzone-patna", "secret123") is None)
check("weak new password refused", raises(tenants.set_password, "fitzone-patna", "123"))

print("Information, switch on/off, limits")
tenants.update_info("fitzone-patna", "## Plans\n- Monthly: Rs 1,500\n- Timings 6am to 9pm")
check("owner can update info", "Rs 1,500" in tenants.get_tenant("fitzone-patna")["info"])
check("empty info refused", raises(tenants.update_info, "fitzone-patna", "  "))
tenants.set_active("glowsalon", False)
check("can switch a business off", tenants.get_tenant("glowsalon")["active"] is False)
tenants.set_limit("glowsalon", 3)
allowed = [tenants.check_and_count("glowsalon")[0] for _ in range(5)]
check("limit of 3 allows exactly 3 messages", allowed == [True, True, True, False, False])
check("usage stops counting at the limit", tenants.usage_this_month("glowsalon") == 3)
check("unknown business is never allowed", tenants.check_and_count("ghost-gym")[0] is False)
check("bad limit refused", raises(tenants.set_limit, "glowsalon", 0))
real_month = tenants._month
tenants._month = lambda: "2099-01"
check("new month resets the counter", tenants.check_and_count("glowsalon")[0] is True)
tenants._month = real_month
rows = {r["slug"]: r for r in tenants.list_tenants()}
check("list shows usage + status", rows["glowsalon"]["used"] == 3 and rows["glowsalon"]["active"] is False)

print("Data isolation between businesses")
a, _ = store.add_lead("fitzone-patna", "s1", "enquiry", "Amit", "9876543210", "gym", "", True)
b, _ = store.add_lead("glowsalon", "s2", "enquiry", "Riya", "9123456789", "haircut", "", True)
store.add_handoff("fitzone-patna", "s1", "refund", "money back")
check("each business sees only its own leads",
      [r["name"] for r in store.list_leads("fitzone-patna")] == ["Amit"]
      and [r["name"] for r in store.list_leads("glowsalon")] == ["Riya"])
check("hand-offs are separate", len(store.list_handoffs("glowsalon")) == 0 and len(store.list_handoffs("fitzone-patna")) == 1)
check("cannot delete another business's lead", store.delete_lead("glowsalon", a) == 0 and len(store.list_leads("fitzone-patna")) == 1)
csv_a = store.leads_csv_text("fitzone-patna")
check("CSV contains only that business", "Amit" in csv_a and "Riya" not in csv_a)
check("CSV opens cleanly in Excel (BOM)", csv_a.startswith("\ufeff"))
store.add_lead("fitzone-patna", "s3", "enquiry", "=HYPERLINK(\"http://evil\")", "9000000001", "+cmd", "", True)
evil = store.leads_csv_text("fitzone-patna")
check("spreadsheet formulas are neutralised", "'=HYPERLINK" in evil and ",=HYPERLINK" not in evil and "'+cmd" in evil)
check("owner can delete their own lead", store.delete_lead("fitzone-patna", a) == 1)
check("non-numeric lead id is rejected, not crashed", raises(store.delete_lead, "fitzone-patna", "abc"))
store.log_message("glowsalon", "s2", "user", "hi")
counts = tenants.delete_tenant("glowsalon")
check("deleting a business removes its data", counts["leads"] == 1 and counts["messages"] == 1 and counts["tenant"] == 1
      and tenants.get_tenant("glowsalon") is None and store.list_leads("glowsalon") == [])
check("deleting one business leaves the others alone", tenants.get_tenant("fitzone-patna") is not None
      and any(r["name"] != "Amit" for r in store.list_leads("fitzone-patna")))

print("Assistant uses the business's own details")
t1 = tenants.get_tenant("fitzone-patna")
t2 = tenants.create_tenant("spa-one", "Spa One", "secret123", "## Menu\n- Massage: Rs 999 for 60 minutes")
b1, b2 = FrontDesk(tenant=t1, session_id="aaaaaaaa"), FrontDesk(tenant=t2, session_id="bbbbbbbb")
check("prompt has this business's name + info", "FitZone Patna" in b1.system_prompt and "Rs 1,500" in b1.system_prompt)
check("prompt never contains another business's info", "Massage" not in b1.system_prompt and "Rs 1,500" not in b2.system_prompt)
check("leads are saved under the right business", b1.business_id == "fitzone-patna" and b2.business_id == "spa-one")
tools_b1 = b1.tools[0]
alerts = []
import tools as toolmod
toolmod.notify_owner = lambda m: alerts.append(m)
tools_b1("Sam", "9812345678", "gym", True)
check("a lead from business 1 lands only in business 1",
      any(r["name"] == "Sam" for r in store.list_leads("fitzone-patna")) and store.list_leads("spa-one") == [])

print("Security tokens and limits")
check("csrf token is stable per scope", csrf_token("k", "owner:a") == csrf_token("k", "owner:a"))
check("csrf differs per business", csrf_token("k", "owner:a") != csrf_token("k", "owner:b"))
check("csrf differs per server secret", csrf_token("k1", "super") != csrf_token("k2", "super"))
check("good token accepted", csrf_ok("k", "super", csrf_token("k", "super")))
check("token for another business rejected", not csrf_ok("k", "owner:b", csrf_token("k", "owner:a")))
check("missing/garbage token rejected", not csrf_ok("k", "super", None) and not csrf_ok("k", "super", "abc"))
now = [0.0]
rl = RateLimiter(3, 60, clock=lambda: now[0])
check("login limiter: open until failures are recorded", not rl.blocked("ip"))
for _ in range(3):
    rl.allow("ip")
check("login limiter: blocked after 3 failures", rl.blocked("ip"))
check("checking 'blocked' does not itself add hits", rl.blocked("ip") and len(rl._hits["ip"]) == 3)
now[0] += 61
check("login limiter: unblocked after the window", not rl.blocked("ip"))

print("Pages are safe")
evil_t = {"slug": "xss-gym", "name": "<script>alert(1)</script>", "monthly_limit": 10,
          "info": "</textarea><script>alert(2)</script>"}
lead = [{"id": 7, "created_at": 1.0, "kind": "visit_request", "name": "<img src=x onerror=alert(3)>",
         "phone": "9", "interest": "a&b", "preferred_time": "\"q\""}]
hand = [{"created_at": 1.0, "reason": "<b>r</b>", "last_message": "<script>alert(4)</script>"}]
owner = render_owner_html(evil_t, lead, hand, 3, "TOKEN123", "https://x.test/c/xss-gym", "<i>note</i>")
check("no raw script tags anywhere on owner page", "<script" not in owner.lower())
check("textarea cannot be broken out of", "&lt;/textarea&gt;" in owner and owner.count("</textarea>") == 1)
check("customer-typed HTML is escaped", "<img src=x" not in owner and "&lt;img src=x" in owner)
check("every form carries the security token", owner.count('name="csrf"') == owner.count("<form"))
check("delete button names the lead id", 'name="id" value="7"' in owner)
sup = render_super_html([{"slug": "ok-gym", "name": "<script>x</script>", "active": True,
                          "monthly_limit": 5, "used": 1, "created_at": 1.0}], "TOKEN", "https://x.test", "<b>n</b>")
check("super page escapes names", "<script" not in sup.lower() and "&lt;script&gt;" in sup)
check("super forms carry the token", sup.count('name="csrf"') == sup.count("<form"))
check("landing page escapes", "<script" not in render_landing_html("<script>", "a@b.c\"><x>").lower())

print("Chat page works for both editions")
check("chat page picks the business from the URL", '"/api/c/"' in CHAT_HTML and 'parts[1] === "c"' in CHAT_HTML)
check("single-business API path still supported", ': "/api";' in CHAT_HTML)
check("unavailable chat hides the form", 'form.style.display = "none"' in CHAT_HTML)

print("Web routes (checked without running the server)")
src = Path("saas.py").read_text(encoding="utf-8")
routes = re.findall(r'@app\.(get|post)\("([^"]+)"', src)
post_paths = {p for m, p in routes if m == "post"}
get_paths = {p for m, p in routes if m == "get"}
tree = ast.parse(src)
unprotected = []
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for d in node.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "post"
                    and d.args and isinstance(d.args[0], ast.Constant)):
                path = d.args[0].value
                body = ast.get_source_segment(src, node)
                if path.startswith(("/c/{slug}/admin", "/super")):
                    if "check_csrf(" not in body or "Depends(" not in body:
                        unprotected.append(path)
check("every owner/admin POST route checks the security token and login", unprotected == [])
actions = set(re.findall(r'action="([^"]+)"', owner + sup))
missing = []
for a in actions:
    pattern = re.sub(r"^/c/[a-z0-9-]+/", "/c/{slug}/", a)
    if pattern not in post_paths:
        missing.append(a)
check("every form on the pages points at a real POST route", missing == [])
links = set(re.findall(r'href="(/c/[^"]*admin/[^"]+)"', owner))
check("owner page download link has a route", all(re.sub(r"^/c/[a-z0-9-]+/", "/c/{slug}/", l) in get_paths for l in links))
check("no route accepts an unauthenticated lead export", "owner_csv(t: dict = Depends(owner_auth))" in src)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
