"""
dashboard.py — read-only local web dashboard for the outreach pipeline.

Stdlib only (http.server). Serves dashboard.html plus a JSON status API that
reads prospects.db, run_days, and logs/*.log. Also exposes a pause/resume toggle
(creates/deletes the PAUSED sentinel — same mechanism runlog.py already
honors) and a button to launch a findprospects run via the `claude`
CLI. Never writes prospects.db, never touches Gmail.

Run: python brace.py dashboard [--port 8377]
"""

import os
import re
import sys
import json
import time
import shutil
import sqlite3
import argparse
import datetime
import threading
import subprocess
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from outreach import db
from outreach.engine import MODES
from core.runlog import LOCK_STALE_SECONDS, lock_path

from core.paths import (
    ROOT as AGENT_ROOT, DB_PATH, LOGS_DIR as LOG_DIR, PAUSED_FILE,
)

HERE = Path(__file__).resolve().parent
DASHBOARD_HTML = HERE / "dashboard.html"   # a template, not data — lives with the code

DEFAULT_PORT = 8377

STATUSES = ["new", "cold", "F1", "F2", "failed", "replied", "sibling_replied"]

FINDPROSPECTS_PROMPT = (
    "Read skills/findprospects/SKILL.md and run it end to end for 15 accounts. "
    "Write the CSV to data/runs/<today>.csv, then stop."
)

# Log line shape: "%Y-%m-%d %H:%M:%S,ms name LEVEL msg"
WORKER_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ (\S+) (\S+) (.*)$"
)
MOVED_RE = re.compile(r"Bounce pass complete:\s*(\d+)\s*addresses? moved")

ERROR_LOOKBACK_HOURS = 6

# ---------------------------------------------------------------------------
# scheduler-process check — cached 15s so page refreshes don't spawn PowerShell
# ---------------------------------------------------------------------------

_sched_lock = threading.Lock()
_sched_cache = {"ts": 0.0, "result": None}


def _check_scheduler_process():
    """Is an engine running FOR THIS CHECKOUT?

    Two things have to be true, and the second one is the subtle one:

    1. The command line looks like a scheduler - either `brace.py ... engine`
       (how the CLI launches it) or a direct `scheduler.py` run.
    2. It is running out of THIS directory.

    Matching on the script name alone is what a naive version does, and it is
    wrong on any machine with more than one copy of this repo, or any other
    project that happens to have a `scheduler.py`. Caught exactly that in
    testing: an unrelated scheduler elsewhere on the machine made a fresh clone
    report its engine online while nothing was running. A false "online" is
    worse than no indicator, because it is the signal you would trust when
    wondering why nothing has sent.
    """
    # Embedded as a PowerShell single-quoted literal, so ' must be doubled.
    # .Contains() rather than -like: a path can contain [ and ], which -like
    # treats as a character class and would silently stop matching.
    root = str(AGENT_ROOT).lower().replace("'", "''")
    try:
        cmd = [
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
            "Where-Object {$_.CommandLine -and "
            f"$_.CommandLine.ToLower().Contains('{root}') -and "
            "($_.CommandLine -like '*engine*' "
            "-or $_.CommandLine -like '*scheduler.py*')} | "
            "Select-Object -ExpandProperty ProcessId",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        out = (proc.stdout or "").strip()
        pids = [int(tok) for tok in out.split() if tok.strip().isdigit()]
        own_pid = os.getpid()
        pids = [p for p in pids if p != own_pid]
        if pids:
            return {"scheduler_online": True, "scheduler_pid": pids[0]}
        return {"scheduler_online": False, "scheduler_pid": None}
    except Exception as e:
        return {
            "scheduler_online": False,
            "scheduler_pid": None,
            "scheduler_check_error": str(e),
        }


def get_scheduler_status():
    with _sched_lock:
        now = time.time()
        if _sched_cache["result"] is not None and now - _sched_cache["ts"] < 15:
            return _sched_cache["result"]
        result = _check_scheduler_process()
        _sched_cache["ts"] = now
        _sched_cache["result"] = result
        return result


# ---------------------------------------------------------------------------
# burst / window status
# ---------------------------------------------------------------------------

def _lock_active(mode):
    path = lock_path(f"v2_{mode}")
    if not path.exists():
        return False
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age <= LOCK_STALE_SECONDS


def _in_window(now, window):
    start, end = window
    return start <= now.time() < end


def get_engine_status(now, paused, scheduler_online):
    if paused:
        return {"state": "off", "reason": "paused", "mode": None, "next_burst": None}
    if not scheduler_online:
        return {"state": "off", "reason": "scheduler offline", "mode": None, "next_burst": None}

    for mode in ("cold", "followup"):
        if _lock_active(mode):
            return {"state": "bursting", "reason": None, "mode": mode, "next_burst": None}

    today = db.local_today()
    for mode, cfg in MODES.items():
        if _in_window(now, cfg["window"]):
            next_burst = None
            try:
                conn = _ro_conn()
                try:
                    r = conn.execute(
                        "SELECT next_burst_at FROM run_days WHERE run_date=? AND mode=?",
                        (today, mode),
                    ).fetchone()
                    if r and r["next_burst_at"]:
                        next_burst = r["next_burst_at"]
                finally:
                    conn.close()
            except Exception:
                pass
            return {"state": "waiting", "reason": None, "mode": mode, "next_burst": next_burst}

    return {"state": "on", "reason": None, "mode": None, "next_burst": None}


# ---------------------------------------------------------------------------
# DB reads (read-only connection, never writes)
# ---------------------------------------------------------------------------

def _ro_conn():
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_counts_today():
    today = db.local_today()
    counts = {"cold": 0, "F1": 0, "F2": 0}
    conn = _ro_conn()
    try:
        for row in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM sends WHERE send_date=? AND state='sent' "
            "GROUP BY kind",
            (today,),
        ):
            if row["kind"] in counts:
                counts[row["kind"]] = row["n"]
        queue_new = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE status='new'"
        ).fetchone()[0]
        funnel = {s: 0 for s in STATUSES}
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM leads GROUP BY status"):
            if row["status"] in funnel:
                funnel[row["status"]] = row["n"]
    finally:
        conn.close()
    return counts, queue_new, funnel


def get_failed_leads():
    conn = _ro_conn()
    try:
        rows = conn.execute(
            "SELECT id, company, designation FROM leads WHERE status='failed' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [{"id": r["id"], "company": r["company"], "designation": r["designation"]} for r in rows]


# ---------------------------------------------------------------------------
# log parsing
# ---------------------------------------------------------------------------

def tail_lines(path, n=3000):
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-n:]


def get_bounced_today():
    today = db.local_today()
    total = 0
    for line in tail_lines(LOG_DIR / "bounce_sweep.log"):
        if not line.startswith(today):
            continue
        m = MOVED_RE.search(line)
        if m:
            total += int(m.group(1))
    return total


def get_recent_errors(now):
    cutoff = now - datetime.timedelta(hours=ERROR_LOOKBACK_HOURS)
    errors = []
    for workflow, fname in (
        ("cold", "cold.log"),
        ("followup", "followup.log"),
        ("bounce_sweep", "bounce_sweep.log"),
    ):
        for line in tail_lines(LOG_DIR / fname):
            m = WORKER_RE.match(line)
            if not m:
                continue
            ts_str, _name, level, msg = m.groups()
            if level not in ("ERROR", "WARNING"):
                continue
            try:
                ts = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if ts < cutoff:
                continue
            errors.append({"ts": ts_str, "workflow": workflow, "msg": msg})
    errors.sort(key=lambda e: e["ts"], reverse=True)
    return errors[:10]


# ---------------------------------------------------------------------------
# /api/state
# ---------------------------------------------------------------------------

def build_state():
    now = datetime.datetime.now()
    sched = get_scheduler_status()
    paused = PAUSED_FILE.exists()
    engine = get_engine_status(now, paused, sched["scheduler_online"])
    counts, queue_new, funnel = get_counts_today()

    state = {
        "now": now.strftime("%Y-%m-%d %H:%M:%S"),
        "paused": paused,
        "scheduler_online": sched["scheduler_online"],
        "engine": engine,
        "counts": {
            "cold_today": counts["cold"],
            "f1_today": counts["F1"],
            "f2_today": counts["F2"],
            "bounced_today": get_bounced_today(),
            "queue_new": queue_new,
        },
        "funnel": funnel,
        "failed_leads": get_failed_leads(),
        "errors_recent": get_recent_errors(now),
    }
    return state


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "OutreachDashboard/2.0"

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, text, status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        try:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/dashboard.html"):
                if DASHBOARD_HTML.exists():
                    self._send_html(DASHBOARD_HTML.read_text(encoding="utf-8"))
                else:
                    self._send_html("dashboard.html not found")
                return
            if path == "/api/state":
                self._send_json(build_state())
                return
            self._send_json({"error": "not found"}, status=404)
        except Exception as e:
            self._send_json({"error": str(e)}, status=500)

    def do_POST(self):
        try:
            path = self.path.split("?", 1)[0]
            if path == "/api/toggle":
                body = self._read_json_body()
                want_paused = bool(body.get("paused"))
                if want_paused:
                    if not PAUSED_FILE.exists():
                        PAUSED_FILE.touch()
                else:
                    if PAUSED_FILE.exists():
                        PAUSED_FILE.unlink()
                self._send_json({"paused": PAUSED_FILE.exists()})
                return
            if path == "/api/run-findprospects":
                claude_path = shutil.which("claude")
                if not claude_path:
                    self._send_json(
                        {"ok": False, "error": "`claude` not found on PATH"}, status=500
                    )
                    return
                try:
                    subprocess.Popen(
                        [claude_path, "--bg", FINDPROSPECTS_PROMPT],
                        cwd=str(AGENT_ROOT),
                    )
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, status=500)
                    return
                self._send_json({"ok": True})
                return
            self._send_json({"error": "not found"}, status=404)
        except Exception as e:
            self._send_json({"error": str(e)}, status=500)


def main():
    parser = argparse.ArgumentParser(description="Brace outreach dashboard server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Brace dashboard running at http://127.0.0.1:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
