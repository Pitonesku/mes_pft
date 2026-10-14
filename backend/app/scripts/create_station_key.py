"""Create / list / revoke long-lived station API keys for the push agent.

The plaintext key is printed ONCE at creation and never stored (only its SHA-256
hash is kept in ``station_keys``). The key is scoped to POST /api/v2/quality/ingest.

Run from ``backend/``:
    python -m app.scripts.create_station_key --label "Station 1 - Quantum Neo"
    python -m app.scripts.create_station_key --list
    python -m app.scripts.create_station_key --revoke 1
    python -m app.scripts.create_station_key --activate 1
"""

import argparse
import hashlib
import secrets

from sqlalchemy import text

from app.database import SessionLocal
from app import models
from app.seed import seed_station_ingest


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create(label: str) -> None:
    raw = secrets.token_urlsafe(32)
    user_id = seed_station_ingest()
    db = SessionLocal()
    try:
        key = models.StationKey(key_hash=hash_key(raw), label=label, user_id=user_id)
        db.add(key)
        db.flush()
        db.commit()
        print(f"Created station key (id={key.id}, label={label!r}):")
        print(raw)
        print("Store this in the agent config (station_agent.ini). It will NOT be shown again.")
    finally:
        db.close()


def list_keys() -> None:
    db = SessionLocal()
    try:
        rows = db.query(models.StationKey).order_by(models.StationKey.id).all()
        if not rows:
            print("No station keys.")
            return
        print(f"{'id':>3}  {'active':<6}  {'label':<28}  {'created_at':<22}  last_used_at")
        for k in rows:
            print(f"{k.id:>3}  {str(k.is_active):<6}  {k.label:<28}  {str(k.created_at):<22}  {k.last_used_at}")
    finally:
        db.close()


def set_active(key_id: int, active: bool) -> None:
    db = SessionLocal()
    try:
        key = db.get(models.StationKey, key_id)
        if key is None:
            print(f"No station key with id={key_id}")
            return
        key.is_active = active
        db.commit()
        print(f"Station key {key_id} -> active={active}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage station ingest API keys")
    parser.add_argument("--label", help="create a key with this label")
    parser.add_argument("--list", action="store_true", help="list keys")
    parser.add_argument("--revoke", type=int, metavar="ID", help="deactivate a key by id")
    parser.add_argument("--activate", type=int, metavar="ID", help="re-activate a key by id")
    args = parser.parse_args()

    if args.label:
        create(args.label)
    elif args.list:
        list_keys()
    elif args.revoke is not None:
        set_active(args.revoke, False)
    elif args.activate is not None:
        set_active(args.activate, True)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
