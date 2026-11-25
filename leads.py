"""See what the assistant collected.
    uv run leads.py          show leads and hand-offs
    uv run leads.py export   save leads to data/leads.csv (opens in Excel)
"""
import sys
import time

import config
import store


def fmt(ts):
    return time.strftime("%d-%b %H:%M", time.localtime(ts))


if len(sys.argv) > 1 and sys.argv[1] == "export":
    n = store.export_leads_csv(config.DB_PATH.parent / "leads.csv")
    print(f"Saved {n} leads to {config.DB_PATH.parent / 'leads.csv'}")
    sys.exit()

leads = store.list_leads()
print(f"\nLEADS ({len(leads)})")
for r in leads:
    print(f"  #{r['id']} {fmt(r['created_at'])} [{r['kind']}] {r['name']} | {r['phone']} "
          f"| {r['interest']} | preferred: {r['preferred_time'] or '-'}")

handoffs = store.list_handoffs()
print(f"\nHAND-OFFS ({len(handoffs)})")
for r in handoffs:
    print(f"  #{r['id']} {fmt(r['created_at'])} {r['reason']} | said: {r['last_message']}")
print()
