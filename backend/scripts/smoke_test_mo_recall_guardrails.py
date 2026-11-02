"""Dev-only smoke test: verify the mes_integration MO recall guardrails over
XML-RPC against the DEV Odoo (127.0.0.1:8070, db 'test'). Never 8069.

Checks (addon >= 18.0.1.4.0):
  1. mes_sync_status selection contains 'recalled'.
  2. unlink() of a 'synced' MO is refused ("Cannot delete ...").
  3. action_cancel() of a 'synced' MO is refused ("Cannot cancel ...").
  4. action_recall_from_mes() is deployed (only invoked when mes_pft.url is
     NOT configured, so the live call has zero side effects).
The MO's original mes_sync_status is restored at the end.
"""

import sys

sys.path.insert(0, r"c:\Users\Maximusm\Documents\Python\mes_pft\backend")

import app.database  # noqa: E402,F401  (loads .env into os.environ)

from app.services.odoo.client import OdooClient, OdooConfig, OdooError  # noqa: E402

MIN_VERSION = "18.0.1.4.0"


def main() -> int:
    cfg = OdooConfig.from_env()
    if not (cfg.enabled and cfg.valid()):
        print("SKIP: Odoo not configured in .env")
        return 0
    client = OdooClient(cfg)
    client.connect()

    # 0. Addon version.
    mods = client.search_read(
        "ir.module.module", [["name", "=", "mes_integration"]], ["latest_version"])
    if not mods:
        print("FAIL: mes_integration module not found")
        return 1
    version = mods[0]["latest_version"] or ""
    print(f"mes_integration version: {version}")
    if version < MIN_VERSION:
        print(f"FAIL: addon too old (need >= {MIN_VERSION}) - restart the dev Odoo")
        return 1

    # 1. Selection contains 'recalled'.
    fields = client.call_args("mrp.production", "fields_get", [["mes_sync_status"]])
    selection = [v[0] for v in (fields.get("mes_sync_status") or {}).get("selection", [])]
    assert "recalled" in selection, f"'recalled' missing from selection: {selection}"
    print("OK   mes_sync_status selection contains 'recalled'")

    # 2-4. Guardrails on a real (confirmed) dev MO, restoring its status after.
    mos = client.search_read(
        "mrp.production",
        [["state", "in", ["confirmed", "progress", "done"]], ["product_id", "!=", False]],
        ["id", "name", "mes_sync_status", "origin"], limit=1, order="id desc")
    if not mos:
        print("SKIP: no MO found in dev DB to exercise the guardrails")
        return 0
    mo = mos[0]
    original_status = mo["mes_sync_status"] or "pending"
    print(f"Using MO id={mo['id']} name={mo['name']} (status restored at the end)")

    client.write("mrp.production", [mo["id"]], {"mes_sync_status": "synced"})

    try:
        client.call_args("mrp.production", "unlink", [[mo["id"]]])
        print("FAIL: unlink() of a synced MO did not raise")
        return 1
    except OdooError as exc:
        assert "Cannot delete" in str(exc), f"unexpected unlink error: {exc}"
        print("OK   unlink blocked: Cannot delete ...")

    try:
        client.call_args("mrp.production", "action_cancel", [[mo["id"]]])
        print("FAIL: action_cancel() of a synced MO did not raise")
        return 1
    except OdooError as exc:
        assert "Cannot cancel" in str(exc), f"unexpected cancel error: {exc}"
        print("OK   action_cancel blocked: Cannot cancel ...")

    # The live recall POST could mutate real data when the MES is reachable, so
    # it is only exercised when the MES is unreachable (deterministic network
    # error proves the method + HTTP path are deployed). Exercise the real
    # end-to-end flow from the Odoo UI against a throwaway MO instead.
    import socket
    mes_up = True
    try:
        with socket.create_connection(("127.0.0.1", 8001), timeout=2):
            pass
    except OSError:
        mes_up = False
    if mes_up:
        print("SKIP action_recall_from_mes live call (dev MES reachable - "
              "exercise it from the Odoo UI against a throwaway MO instead)")
    else:
        try:
            client.call_args("mrp.production", "action_recall_from_mes", [[mo["id"]]])
            print("FAIL: action_recall_from_mes did not raise while MES is down")
            return 1
        except OdooError as exc:
            assert "recall failed" in str(exc), f"unexpected recall error: {exc}"
            print("OK   action_recall_from_mes deployed (network error while MES down)")

    # Restore.
    client.write("mrp.production", [mo["id"]], {"mes_sync_status": original_status})
    print(f"OK   mes_sync_status restored to '{original_status}'")
    print("OK   SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
