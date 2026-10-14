"""Per-station push agent.

Runs on each measurement-station PC (a plain Python 3 install is enough). It
watches a LOCAL output folder and POSTs each new CSV/XML to the MES server's
``POST /api/v2/quality/ingest`` endpoint with retry, so a network outage never
loses a measurement: files are kept locally until the server ACKs.

Authentication uses a long-lived station API key (``X-Station-Key`` header),
issued on the MES server with ``create_station_key.py``. No interactive login or
admin credentials are stored on the station PC.

Configuration is read from ``station_agent.ini`` (or ``station_agent.env``) in
the agent's own folder, then overridden by OS environment variables, then by
CLI flags (highest precedence).

Settings (precedence: CLI flag > env var > config file > default):
  watch_dir     STATION_AGENT_WATCH_DIR    local folder the station writes into (required)
  mes_base_url  MES_BASE_URL               MES server root, e.g. http://10.10.0.202:8000
  station_key   STATION_AGENT_KEY          long-lived ingest API key (required)
  archive_dir   STATION_AGENT_ARCHIVE_DIR  local archive (default: <watch>/Archive)
  error_dir     STATION_AGENT_ERROR_DIR    local error folder (default: <watch>/Errors)
  scan_interval STATION_AGENT_SCAN_INTERVAL poll seconds (default: 30)
  ledger        STATION_AGENT_LEDGER       JSON ledger path (default: <archive>/ledger.json)
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

log = logging.getLogger("station_push_agent")

EXTENSIONS = (".csv", ".xml")
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_SCAN_INTERVAL = 30
MAX_ATTEMPTS = 60


def _agent_dir() -> Path:
    """Folder holding the agent (the .exe dir when frozen by PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _load_config_file() -> dict:
    """Read station_agent.ini / station_agent.env from the agent's own folder."""
    cfg: dict = {}
    base = _agent_dir()
    ini_path = base / "station_agent.ini"
    if ini_path.is_file():
        parser = configparser.ConfigParser()
        try:
            parser.read(ini_path, encoding="utf-8")
        except configparser.Error:
            parser = configparser.ConfigParser()
            parser.read(ini_path)
        section = "agent" if parser.has_section("agent") else parser.default_section
        for key in ("watch_dir", "mes_base_url", "station_key", "archive_dir",
                    "error_dir", "scan_interval", "ledger"):
            if parser.has_option(section, key):
                cfg[key] = parser.get(section, key).strip()
    env_path = base / "station_agent.env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k:
                cfg[k] = v.strip().strip('"').strip("'")
    return cfg


_CONFIG = _load_config_file()


def _resolve(cli_val, env_name: str, cfg_key: str, default=None):
    """Resolve a setting: CLI flag > env var > config file > default."""
    if cli_val is not None:
        return cli_val
    env = os.getenv(env_name)
    if env:
        return env
    cfg = _CONFIG.get(cfg_key)
    if cfg:
        return cfg
    return default


def _resolve_path(value: str) -> Path:
    """Resolve a possibly-relative path against the agent's own folder."""
    p = Path(value)
    if not p.is_absolute():
        p = _agent_dir() / p
    return p


class Ledger:
    """Tiny JSON ledger tracking each file hash -> status + attempt count."""

    def __init__(self, path: Path):
        self.path = path
        self.rows: dict = {}
        if path.is_file():
            try:
                self.rows = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.rows = {}

    def get(self, digest):
        return self.rows.get(digest)

    def set(self, digest, **fields):
        row = self.rows.setdefault(digest, {})
        row.update(fields)
        self.rows[digest] = row
        self.save()

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.rows, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)


class PushAgent:
    def __init__(self, watch: Path, base_url: str, station_key: str,
                 archive: Path, error: Path, scan_interval: int, ledger: Ledger):
        self.watch = watch
        self.base_url = base_url.rstrip("/")
        self.station_key = station_key
        self.archive = archive
        self.error = error
        self.scan_interval = scan_interval
        self.ledger = ledger

    # -- upload -------------------------------------------------------------
    def _upload(self, filename: str, data: bytes):
        boundary = "----mes" + uuid.uuid4().hex
        body = self._multipart(filename, data, boundary)
        req = urllib.request.Request(
            f"{self.base_url}/api/v2/quality/ingest",
            data=body,
            headers={
                "X-Station-Key": self.station_key,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
        return resp.status, payload

    @staticmethod
    def _multipart(filename, data, boundary):
        parts = []
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            b'Content-Disposition: form-data; name="file"; filename="'
            + Path(filename).name.encode("utf-8")
            + b'"\r\n'
        )
        parts.append(b"Content-Type: application/octet-stream\r\n\r\n")
        parts.append(data)
        parts.append(b"\r\n--" + boundary.encode() + b"--\r\n")
        return b"".join(parts)

    # -- file handling ------------------------------------------------------
    def _process_file(self, path: Path):
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        row = self.ledger.get(digest)
        if row and row.get("status") == "done":
            self._move(path, self.archive)
            return

        attempts = (row or {}).get("attempts", 0)
        if attempts >= MAX_ATTEMPTS:
            self.ledger.set(digest, status="error", note="max attempts reached")
            self._move(path, self.error)
            return

        try:
            status, payload = self._upload(path.name, data)
            if status == 200:
                # 'duplicate' is also success (already ingested by another path).
                self.ledger.set(digest, status="done",
                                server_state=payload.get("status", "processed"),
                                attempts=attempts + 1)
                self._move(path, self.archive)
                log.info("uploaded %s -> %s", path.name, payload.get("status"))
            else:
                self.ledger.set(digest, status="retry", note=f"http {status}", attempts=attempts + 1)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                note = "station key rejected (revoked or rotated)"
            else:
                note = f"http {exc.code}"
            self.ledger.set(digest, status="retry", note=note, attempts=attempts + 1)
            log.warning("%s on %s (will retry): %s", note, path.name, exc)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.ledger.set(digest, status="retry", note=str(exc)[:200], attempts=attempts + 1)
            log.warning("network error on %s (will retry): %s", path.name, exc)

    def _move(self, path: Path, target: Path):
        target.mkdir(parents=True, exist_ok=True)
        dest = target / path.name
        if dest.exists():
            dest.unlink()
        os.replace(path, dest)

    # -- loop ----------------------------------------------------------------
    def run_forever(self):
        log.info("watching %s -> %s", self.watch, self.base_url)
        while True:
            try:
                if self.watch.is_dir():
                    for entry in sorted(self.watch.iterdir()):
                        if entry.is_file() and entry.suffix.lower() in EXTENSIONS:
                            try:
                                self._process_file(entry)
                            except Exception:
                                log.exception("failed to process %s", entry.name)
            except Exception:
                log.exception("scan iteration failed")
            time.sleep(self.scan_interval)


def main():
    log_file = _agent_dir() / "station_push_agent.log"
    handlers = [logging.FileHandler(log_file, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )

    parser = argparse.ArgumentParser(description="MES station push agent")
    parser.add_argument("--watch", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--station-key", default=None)
    parser.add_argument("--archive", default=None)
    parser.add_argument("--error", default=None)
    parser.add_argument("--scan-interval", type=int, default=None)
    parser.add_argument("--ledger", default=None)
    args = parser.parse_args()

    watch_raw = _resolve(args.watch, "STATION_AGENT_WATCH_DIR", "watch_dir")
    key_raw = _resolve(args.station_key, "STATION_AGENT_KEY", "station_key")
    if not watch_raw:
        raise SystemExit("watch_dir (STATION_AGENT_WATCH_DIR or --watch) is required")
    if not key_raw:
        raise SystemExit("station_key (STATION_AGENT_KEY or --station-key) is required")

    watch = _resolve_path(watch_raw)
    base_url = _resolve(args.base_url, "MES_BASE_URL", "mes_base_url", DEFAULT_BASE_URL)
    archive_raw = _resolve(args.archive, "STATION_AGENT_ARCHIVE_DIR", "archive_dir")
    error_raw = _resolve(args.error, "STATION_AGENT_ERROR_DIR", "error_dir")
    ledger_raw = _resolve(args.ledger, "STATION_AGENT_LEDGER", "ledger")
    scan_interval = int(_resolve(args.scan_interval, "STATION_AGENT_SCAN_INTERVAL", "scan_interval", DEFAULT_SCAN_INTERVAL))

    archive = _resolve_path(archive_raw) if archive_raw else watch / "Archive"
    error = _resolve_path(error_raw) if error_raw else watch / "Errors"
    ledger_path = _resolve_path(ledger_raw) if ledger_raw else archive / "ledger.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    agent = PushAgent(watch, base_url, key_raw, archive, error, scan_interval, Ledger(ledger_path))
    agent.run_forever()


if __name__ == "__main__":
    main()


