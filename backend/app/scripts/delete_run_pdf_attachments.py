"""Delete stale run-level Quality Report PDF attachments from Odoo.

The dispatcher used to attach ONE ``Quality_Report_<MO>_run<id>.pdf`` per
production run. Those have been replaced by a single aggregated shift report
(``<date> <machine> <shift> Quality Report.pdf``). This script removes the old
run-level attachments from ``mrp.production`` only — it never touches the
Production Report PDFs (``Production_Report_*``) or the new shift reports.

Run:
    cd backend
    python -m app.scripts.delete_run_pdf_attachments [--dry-run]
"""

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from app.config import load_env
from app.services.odoo.client import OdooClient, OdooConfig

# e.g. Quality_Report_WH/MO/00219_run424.pdf  (old per-run attachment)
_RUN_PATTERN = re.compile(r"^quality_report_.*_run\d+\.pdf$", re.IGNORECASE)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="only list, do not delete")
    args = parser.parse_args()

    load_env()
    cfg = OdooConfig.from_env()
    if not (cfg.enabled and cfg.valid()):
        print("Odoo is not enabled/configured — nothing to do.")
        return

    client = OdooClient(cfg)
    client.connect()

    attachments = client.search_read(
        "ir.attachment",
        [["res_model", "=", "mrp.production"]],
        ["id", "name", "res_id"],
    )
    stale = [a for a in attachments if _RUN_PATTERN.search(str(a.get("name") or ""))]

    print(f"Found {len(stale)} stale run-level Quality Report attachment(s):")
    for a in stale:
        print(f"  #{a.get('id')}  {a.get('name')}  (res_id={a.get('res_id')})")
        if not args.dry_run:
            client._call("ir.attachment", "unlink", [[a["id"]]])

    if args.dry_run:
        print("[dry-run] no deletions performed")
    else:
        print(f"Deleted {len(stale)} attachment(s)")


if __name__ == "__main__":
    main()
