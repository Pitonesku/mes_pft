"""
Assign quality rods/samples to production runs using the report time windows.

A shift can contain several legacy production reports (one per MO) with their own
start/stop time. Each rod is given to the MO whose report window contains the rod's
timestamp (see app.services.run_assignment). When windows of different MOs overlap,
the station label (quality_samples.sample_id) breaks the tie if it equals exactly one
of them; otherwise the rod is left unassigned and listed for manual review.

Additive only: rows that already have a run_id are never changed; deleted and
obsolete reports are ignored.

    cd backend
    python -m app.scripts.assign_runs --dry-run --csv %TEMP%\\unassigned.csv
    python -m app.scripts.assign_runs
"""

import argparse
import csv
import pathlib
import sys
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text

from app.database import SessionLocal
from app.services import run_assignment as ra

from app.config import get_plant_timezone

PLANT_TZ = get_plant_timezone()
CHUNK = 5000


def _usable_report(r):
    if (r[1] or "") not in ("M1", "M2"):
        return False
    if (r[3] or "") not in ("Shift 1", "Shift 2", "Shift 3"):
        return False
    po = (r[5] or "").upper()
    return not (po.startswith("PO-DIAG") or po.startswith("TEST"))


def build_shift_windows(session):
    """shift_id -> list of (po_number, run_id, t0, t1) for usable, live reports.

    Legacy runs were created one per report in report-id order (and obsolete or
    deleted reports have a run too), so reports and runs are paired by position,
    verified by PO number; otherwise the first run with the same PO is used.
    """
    shifts = session.execute(text(
        "SELECT id, started_at, ended_at, legacy_report_key FROM shift_sessions "
        "WHERE legacy_report_key IS NOT NULL"
    )).fetchall()
    runs = defaultdict(list)
    for r in session.execute(text(
        "SELECT r.id, r.shift_id, COALESCE(p.po_number, r.mo_ref) "
        "FROM production_runs r LEFT JOIN purchase_orders p ON p.id = r.po_id "
        "ORDER BY r.shift_id, r.seq"
    )):
        runs[r[1]].append((r[0], r[2]))
    reports = defaultdict(list)
    for r in session.execute(text(
        "SELECT id, machine_name, report_date, shift_name, shift_time_range, po_number, "
        "is_deleted, status FROM production_reports ORDER BY id"
    )):
        if _usable_report(r):
            reports[f"{r[1]}|{r[2]}|{r[3]}"].append(r)

    out = {}
    for sid, started, ended, key in shifts:
        s0, s1 = started.astimezone(PLANT_TZ), ended.astimezone(PLANT_TZ)
        rns = runs.get(sid, [])
        wins = []
        for idx, rep in enumerate(reports.get(key, [])):
            if rep[6] or rep[7] == "obsolete":
                continue
            if idx < len(rns) and (rns[idx][1] or "") == (rep[5] or ""):
                run_id = rns[idx][0]
            else:
                same = [x[0] for x in rns if (x[1] or "") == (rep[5] or "")]
                run_id = same[0] if same else None
            win = ra.report_window(rep[4], s0, s1)
            if run_id is None or win is None:
                continue
            wins.append((rep[5], run_id, win[0], win[1], rep[0]))  # rep[0] = report id
        out[sid] = wins
    return out


def plan(session):
    """Return (rod_assign {rod_id: run_id}, sample_assign, stats, per_po, leftovers)."""
    windows = build_shift_windows(session)
    rods = session.execute(text(
        "SELECT m.id, m.sample_id, m.shift_id, m.machine_id, m.measured_at, q.sample_id, q.kind "
        "FROM quality_measurements m JOIN quality_samples q ON q.id = m.sample_id "
        "WHERE m.shift_id IS NOT NULL AND m.run_id IS NULL"
    )).fetchall()
    machines = dict(session.execute(text("SELECT id, name FROM machines")).fetchall())

    assign = {}
    sample_runs = defaultdict(set)
    stats = Counter()
    per_po = Counter()
    leftovers = []
    for rod_id, sample_pk, shift_id, machine_id, t, label, kind in rods:
        if kind != "PRODUCTION":
            stats["skipped_non_production"] += 1
            continue
        wins = windows.get(shift_id, [])
        local = t.astimezone(PLANT_TZ)
        po, reason = ra.resolve_po(local, label, [(w[0], w[2], w[3]) for w in wins])
        if po is None:
            reason = reason if wins else "no_report_windows"
            stats[reason] += 1
            leftovers.append((rod_id, machines.get(machine_id), local.isoformat(),
                              label, shift_id, reason))
            sample_runs[sample_pk].add(None)
            continue
        run_id = [w[1] for w in wins if w[0] == po][0]
        assign[rod_id] = run_id
        sample_runs[sample_pk].add(run_id)
        stats["assigned_" + reason] += 1
        per_po[po] += 1
    sample_assign = {
        s: next(iter(v)) for s, v in sample_runs.items() if len(v) == 1 and None not in v
    }
    return assign, sample_assign, stats, per_po, leftovers


def _update_by_run(session, table, mapping):
    by_run = defaultdict(list)
    for pk, run_id in mapping.items():
        by_run[run_id].append(pk)
    updated = 0
    for run_id, ids in by_run.items():
        for i in range(0, len(ids), CHUNK):
            updated += session.execute(
                text(f"UPDATE {table} SET run_id = :r WHERE id = ANY(:ids) AND run_id IS NULL"),
                {"r": run_id, "ids": ids[i:i + CHUNK]},
            ).rowcount
    return updated


def apply(session, assign, sample_assign):
    rods_upd = _update_by_run(session, "quality_measurements", assign)
    samples_upd = _update_by_run(session, "quality_samples", sample_assign)
    session.commit()
    return rods_upd, samples_upd


def main():
    ap = argparse.ArgumentParser(description="Assign rods to runs by report time windows")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--csv", default=None, help="write unassigned rods to this CSV file")
    ap.add_argument("--po", default=None, help="print how many rods get assigned to this PO")
    args = ap.parse_args()

    session = SessionLocal()
    try:
        count_sql = text("SELECT count(*), count(run_id) FROM quality_measurements")
        before = session.execute(count_sql).fetchone()
        assign, sample_assign, stats, per_po, leftovers = plan(session)
        print(f"rods total={before[0]} with run={before[1]}")
        print(f"to assign: rods={len(assign)} samples={len(sample_assign)}")
        print("stats:", dict(stats))
        print("top POs:", per_po.most_common(8))
        if args.po:
            print(f"{args.po}: {per_po.get(args.po, 0)} rods to assign")
        if args.csv:
            with open(args.csv, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["rod_id", "machine", "measured_at", "label", "shift_id", "reason"])
                w.writerows(leftovers)
            print(f"unassigned list: {args.csv} ({len(leftovers)} rows)")
        if args.dry_run:
            print("DRY RUN - nothing written")
            return
        rods_upd, samples_upd = apply(session, assign, sample_assign)
        after = session.execute(count_sql).fetchone()
        print(f"updated rods={rods_upd} samples={samples_upd}; rods with run now={after[1]}")
    finally:
        session.close()


if __name__ == "__main__":
    main()

