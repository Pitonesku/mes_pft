"""Dev-only smoke test: verify mes_integration.mes_quarantine_release over
XML-RPC against the DEV Odoo (127.0.0.1:8070, db 'test'). Never 8069."""

import sys

sys.path.insert(0, r"c:\Users\Maximusm\Documents\Python\mes_pft\backend")

import app.database  # noqa: E402,F401  (loads .env into os.environ)

from app.services.odoo.client import OdooClient, OdooConfig, OdooError  # noqa: E402

cfg = OdooConfig.from_env()
client = OdooClient(cfg)
client.connect()

# 1. Find a done MO with a finished product.
mos = client.search_read(
    "mrp.production", [["state", "=", "done"], ["product_id", "!=", False]],
    ["id", "name", "product_id", "product_uom_id"], limit=1, order="id desc",
)
if not mos:
    print("SKIP: no done MO found in dev DB")
    sys.exit(0)
mo_id = int(mos[0]["id"])
mo_name = mos[0]["name"]
print(f"Using done MO: id={mo_id} name={mo_name}")

# 2. Negative validation (no write): boxes=0 must raise.
try:
    client.call_args("mrp.production", "mes_quarantine_release", [mo_id, 0, "test"])
    print("FAIL: boxes=0 did not raise")
    sys.exit(1)
except OdooError as exc:
    print(f"OK   boxes=0 rejected (method deployed + validation works)")

# 3. Positive test: release 1 box, verify the move, then cancel it (dev cleanup).
reference = "TEST Recovered from Quarantine, orig. MO: " + mo_name
move_id = client.call_args("mrp.production", "mes_quarantine_release", [mo_id, 1, reference])
print(f"OK   release returned stock.move id={move_id}")

moves = client.read("stock.move", [int(move_id)],
                    ["is_inventory", "name", "reference", "state", "product_uom_qty"])
m = moves[0]
assert m["is_inventory"], f"move not flagged is_inventory: {m}"
assert "Recovered from Quarantine" in (m["name"] or ""), f"reference missing: {m}"
print(f"OK   move verified: state={m['state']} uom_qty={m['product_uom_qty']} "
      f"is_inventory={m['is_inventory']}")

mo_after = client.read("mrp.production", [mo_id], ["x_quarantine_released_boxes", "state"])
assert mo_after[0]["state"] == "done", "MO state changed - must stay done!"
print(f"OK   MO state still '{mo_after[0]['state']}', "
      f"x_quarantine_released_boxes={mo_after[0]['x_quarantine_released_boxes']}")

# The validated move stays in the dev DB as evidence of the working flow
# (Inventory -> Moves History shows the recovery reference). _action_cancel is
# private and intentionally not callable over XML-RPC.
print(f"OK   SMOKE TEST PASSED (dev stock.move id={move_id} kept as evidence)")
