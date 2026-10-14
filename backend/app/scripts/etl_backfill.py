"""
One-off backfill: load the quality-station SQLite DB (measurements.db) into the
unified PostgreSQL schema.

Run AFTER restoring the production dump and `alembic upgrade head`:

    cd backend
    .venv/Scripts/python.exe -m app.scripts.etl_backfill ../measurements.db

Steps:
  1. machine_aliases: maker '1' -> machine 'M1', '2' -> 'M2' (the dump's machines
     table is named M1/M2). 'Other' is test data -> no alias (unlinked).
  2. shift_sessions + production_runs derived from legacy production_reports
     (machine_name + report_date + shift_name, using the shifts template times).
  3. quality_samples (from `batches`) + quality_measurements (from `measurements`),
     linked to shifts via shift_resolver by (machine, produced_at) interval.

Idempotency: machine_aliases and shift_sessions are looked up before insert, but
samples/measurements are appended — treat this as a ONE-SHOT backfill and run it
once against a freshly restored + migrated database (the run_migration.ps1 runner
recreates the test DB from scratch each run).
"""

import argparse
import pathlib
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from app import models
from app.database import SessionLocal
from app.services import shift_resolver

from app.config import get_plant_timezone

PLANT_TZ = get_plant_timezone()
SOURCE = "quantum_neo"
ALIAS_FIELD = "maker"
OTHER_MAKER = "Other"

_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%d.%m.%Y %H:%M:%S",
    "%Y-%m-%d %H:%M",
)


def parse_local(value):
    """Parse a station timestamp (naive local, Europe/Budapest) into aware UTC."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=PLANT_TZ).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def num(value):
    """Coerce a station value ('nan' / comma decimal) to float or None."""
    if value is None:
        return None
    text = str(value).strip()
    if text in ("", "nan", "NaN", "None", "N/A"):
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def iint(value):
    n = num(value)
    return int(n) if n is not None else None


def open_sqlite(path):
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def _norm_key(raw):
    """Normalize a station timestamp to local wall-clock 'YYYY-MM-DD HH:MM:SS'.

    Kept in *wall-clock* (no tz conversion) so it matches measurements.time,
    which stores the naive local time from the station.
    """
    text = str(raw or "").strip()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return text


def load_batches(con):
    """batches keyed by (instrument_id, batch_id, normalized produced_on)."""
    out = {}
    for r in con.execute("SELECT * FROM batches"):
        key = (r["instrument_id"], r["batch_id"], _norm_key(r["produced_on"]))
        out[key] = r
    return out


def time_window(since=None, until=None):
    """Turn inclusive ``YYYY-MM-DD`` dates into ``[lower, upper)`` station-time bounds.

    ``measurements.time`` is naive local ISO text, so plain string comparison is
    chronological. ``until`` is INCLUSIVE of the whole day (upper bound = next midnight).
    Returns ``(lower, upper)``; either may be None (unbounded).
    """
    lower = upper = None
    if since:
        lower = datetime.strptime(since, "%Y-%m-%d").strftime("%Y-%m-%d 00:00:00")
    if until:
        nxt = datetime.strptime(until, "%Y-%m-%d") + timedelta(days=1)
        upper = nxt.strftime("%Y-%m-%d 00:00:00")
    return lower, upper


def load_measurement_groups(con, since=None, until=None):
    """measurements grouped by (instrument_id, batch_id, time), optionally windowed."""
    lower, upper = time_window(since, until)
    where, params = [], []
    if lower:
        where.append("time >= ?")
        params.append(lower)
    if upper:
        where.append("time < ?")
        params.append(upper)
    sql = "SELECT * FROM measurements"
    if where:
        sql += " WHERE " + " AND ".join(where)
    groups = {}
    for r in con.execute(sql + " ORDER BY rowid", params):
        key = (r["instrument_id"], r["batch_id"], r["time"])
        groups.setdefault(key, []).append(r)
    return groups


def distinct_makers(con):
    return [r[0] for r in con.execute("SELECT DISTINCT maker FROM measurements ORDER BY 1")]
# ---------------------------------------------------------------------------
# Machine aliases: maker -> machines.id
# ---------------------------------------------------------------------------

def build_machine_aliases(session, makers):
    aliases = {}
    for maker in makers:
        maker = str(maker).strip()
        if maker == OTHER_MAKER:
            aliases[maker] = None
            continue
        name = f"M{maker}"
        machine = session.query(models.Machine).filter_by(name=name).first()
        if machine is None:
            machine = models.Machine(name=name)
            session.add(machine)
            session.flush()
        alias = (
            session.query(models.MachineAlias)
            .filter_by(source=SOURCE, alias_field=ALIAS_FIELD, alias_value=maker)
            .first()
        )
        if alias is None:
            session.add(models.MachineAlias(
                machine_id=machine.id, source=SOURCE,
                alias_field=ALIAS_FIELD, alias_value=maker,
            ))
        aliases[maker] = machine.id
    session.commit()
    return aliases


# ---------------------------------------------------------------------------
# Shift sessions + runs from production_reports
# ---------------------------------------------------------------------------

_SHIFT_TEMPLATE = {
    "Shift 1": ("06:00", "14:00"),
    "Shift 2": ("14:00", "22:00"),
    "Shift 3": ("22:00", "06:00"),
}


def _shift_bounds(report_date, shift_name):
    start_s, end_s = _SHIFT_TEMPLATE[shift_name]
    base = datetime.strptime(report_date, "%Y-%m-%d").date()
    start = datetime.combine(base, datetime.strptime(start_s, "%H:%M").time()).replace(tzinfo=PLANT_TZ)
    end = datetime.combine(base, datetime.strptime(end_s, "%H:%M").time()).replace(tzinfo=PLANT_TZ)
    if end <= start:  # overnight shift (Shift 3)
        end += timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _skip_report(r):
    if (r.machine_name or "") not in ("M1", "M2"):
        return True
    if (r.shift_name or "") not in _SHIFT_TEMPLATE:
        return True
    po = (r.po_number or "").upper()
    return po.startswith("PO-DIAG") or po.startswith("TEST")


def derive_shifts_and_runs(session):
    reports = (
        session.query(models.ProductionReport)
        .order_by(models.ProductionReport.id)
        .all()
    )
    machine_ids = {m.name: m.id for m in session.query(models.Machine).all()}
    shifts = {}
    run_seqs = {}
    run_count = 0
    for r in reports:
        if _skip_report(r):
            continue
        key = (machine_ids[r.machine_name], r.report_date, r.shift_name)
        shift = shifts.get(key)
        if shift is None:
            started_at, ended_at = _shift_bounds(r.report_date, r.shift_name)
            shift = models.ShiftSession(
                machine_id=key[0],
                started_at=started_at,
                ended_at=ended_at,
                status="CLOSED",
                source="legacy",
                time_confidence="derived",
                legacy_report_key=f"{r.machine_name}|{r.report_date}|{r.shift_name}",
            )
            session.add(shift)
            session.flush()
            shifts[key] = shift
            run_seqs[shift.id] = 0
        run_seqs[shift.id] += 1
        po = (
            session.query(models.PurchaseOrder)
            .filter_by(po_number=r.po_number)
            .first()
            if r.po_number else None
        )
        session.add(models.ProductionRun(
            shift_id=shift.id,
            seq=run_seqs[shift.id],
            po_id=po.id if po else None,
            mo_ref=r.po_number or None,
            started_at=shift.started_at,
            ended_at=shift.ended_at,
            status="CLOSED",
            spec_snapshot={
                "diameter": r.diameter, "length": r.length,
                "pd": r.pd, "weight": r.weight, "box_type": r.box_type,
            },
        ))
        run_count += 1
    session.commit()
    return shifts, run_count


# ---------------------------------------------------------------------------
# Quality samples + measurements
# ---------------------------------------------------------------------------

def _kind_of(maker):
    return "CALIBRATION" if maker == OTHER_MAKER else "PRODUCTION"


def load_quality_data(session, sqlite_path, aliases, since=None, until=None):
    con = open_sqlite(sqlite_path)
    batches = load_batches(con)
    groups = load_measurement_groups(con, since, until)

    sample_count = 0
    measurement_count = 0
    link_stats = {}
    measurement_rows = []

    def flush_measurements():
        nonlocal measurement_rows
        if measurement_rows:
            session.bulk_insert_mappings(models.QualityMeasurement, measurement_rows)
            measurement_rows = []

    for key, mrows in groups.items():
        batch = batches.get(key)
        maker = str((batch or mrows[0])["maker"]).strip() if (batch or mrows) else OTHER_MAKER
        machine_id = aliases.get(maker)
        produced_at = parse_local(mrows[0]["time"]) if mrows else None

        kind = _kind_of(maker)
        shift_id = None
        link_status = "NON_PRODUCTION" if maker == OTHER_MAKER else "NO_SHIFT"
        if maker != OTHER_MAKER:
            if machine_id is None:
                link_status = "UNRESOLVED_MACHINE"
            else:
                shift_id, link_status = shift_resolver.resolve_shift(
                    session, machine_id, produced_at
                )

        sample = models.QualitySample(
            shift_id=shift_id,
            run_id=None,
            machine_id=machine_id,
            link_status=link_status,
            link_source="auto",
            kind=kind,
            source_instrument_id=key[0],
            source_maker=maker,
            source_team=str((batch or mrows[0])["team"]),
            sample_id=key[1],
            mo_ref=None,
            brand=str(batch["brand"]) if batch else None,
            operator=str(batch["operator"]) if batch else None,
            comments=(
                str(batch["reserve_2"])
                if batch and str(batch["reserve_2"]) not in ("nan", "None", "")
                else None
            ),
            produced_at=produced_at,
            batch_started_at=parse_local(batch["batch_start"]) if batch else None,
            batch_ended_at=parse_local(batch["batch_end"]) if batch else None,
            rods_declared=iint(batch["rods_count"]) if batch else len(mrows),
        )
        session.add(sample)
        session.flush()
        sample_count += 1
        link_stats[link_status] = link_stats.get(link_status, 0) + 1

        for m in mrows:
            measurement_rows.append({
                "sample_id": sample.id,
                "shift_id": shift_id,
                "run_id": None,
                "machine_id": machine_id,
                "measured_at": parse_local(m["time"]),
                "rod_no": iint(m["rod_no"]) or 0,
                "pd": num(m["pd"]),
                "weight": num(m["weight"]),
                "diameter": num(m["diameter"]),
                "ovality": num(m["ovality"]),
                "roundness": num(m["roundness"]),
                "shape": num(m["shape"]),
            })
            measurement_count += 1
        if len(measurement_rows) >= 5000:
            flush_measurements()

    flush_measurements()
    session.commit()
    con.close()
    return sample_count, measurement_count, link_stats


# ---------------------------------------------------------------------------

def assign_single_runs(session):
    """Set ``run_id`` on linked samples/rods whose shift has EXACTLY ONE run.

    Additive and conservative: only rows with ``run_id IS NULL`` and a shift are
    touched. Shifts with several runs are left alone (a guess would put rods into the
    wrong run's statistics) and are returned for manual review.
    Returns ``(samples_updated, rods_updated, ambiguous_shift_ids)``.
    """
    from sqlalchemy import text

    one_run = (
        "(SELECT shift_id, MIN(id) AS run_id FROM production_runs "
        "GROUP BY shift_id HAVING COUNT(*) = 1)"
    )
    s_upd = session.execute(text(
        f"UPDATE quality_samples q SET run_id = r.run_id FROM {one_run} r "
        "WHERE q.shift_id = r.shift_id AND q.run_id IS NULL"
    )).rowcount
    m_upd = session.execute(text(
        f"UPDATE quality_measurements q SET run_id = r.run_id FROM {one_run} r "
        "WHERE q.shift_id = r.shift_id AND q.run_id IS NULL"
    )).rowcount
    ambiguous = [row[0] for row in session.execute(text(
        "SELECT DISTINCT q.shift_id FROM quality_samples q WHERE q.shift_id IS NOT NULL "
        "AND q.run_id IS NULL ORDER BY 1"
    ))]
    session.commit()
    return s_upd, m_upd, ambiguous


def main():
    ap = argparse.ArgumentParser(description="Backfill unified quality schema from measurements.db")
    ap.add_argument("sqlite", nargs="?", default=None,
                    help="path to measurements.db (default: <repo>/measurements.db)")
    ap.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                    help="load rods from this day on (inclusive)")
    ap.add_argument("--until", default=None, metavar="YYYY-MM-DD",
                    help="load rods up to and including this whole day")
    ap.add_argument("--no-assign-runs", action="store_true",
                    help="do not assign run_id from the report time windows")
    ap.add_argument("--force", action="store_true",
                    help="allow loading when quality_samples is not empty (appends!)")
    args = ap.parse_args()

    sqlite_path = args.sqlite or str(
        pathlib.Path(__file__).resolve().parent.parent.parent.parent / "measurements.db"
    )
    lower, upper = time_window(args.since, args.until)
    print(f"window: [{lower or 'start'} , {upper or 'end'})")

    session = SessionLocal()
    try:
        from sqlalchemy import func

        existing = session.query(func.count(models.QualitySample.id)).scalar()
        if existing and not args.force:
            print(f"ABORT: quality_samples already holds {existing} rows. This backfill "
                  "appends and would duplicate them; use --force only if that is intended.")
            sys.exit(2)

        con = open_sqlite(sqlite_path)
        makers = distinct_makers(con)
        con.close()
        print(f"makers: {makers}")

        aliases = build_machine_aliases(session, makers)
        print(f"machine aliases (maker -> machine_id): {aliases}")

        legacy_shifts = session.query(func.count(models.ShiftSession.id)).scalar()
        if legacy_shifts:
            print(f"shift sessions already present ({legacy_shifts}): skipping derivation")
        else:
            shifts, run_count = derive_shifts_and_runs(session)
            print(f"shift sessions derived: {len(shifts)}, runs: {run_count}")

        samples, measurements, stats = load_quality_data(
            session, sqlite_path, aliases, args.since, args.until
        )
        print(f"quality samples: {samples}")
        print(f"quality measurements: {measurements}")
        print(f"link stats: {stats}")

        if not args.no_assign_runs:
            # Report time windows (+ station label tie-break), see assign_runs.py.
            from app.scripts import assign_runs

            a_rods, a_samples, a_stats, _per_po, left = assign_runs.plan(session)
            r_upd, s_upd = assign_runs.apply(session, a_rods, a_samples)
            print(f"run_id assigned by report time windows: samples={s_upd}, rods={r_upd}")
            print(f"stats: {dict(a_stats)}; left without a run: {len(left)} rod(s)")
    finally:
        session.close()


if __name__ == "__main__":
    main()