"""
db.py — SQLite access layer for the outreach pipeline.

Single source of truth for lead state. All other scripts import from here.
Stdlib only (sqlite3). See README.md for the full schema and lifecycle.
"""

import json
import sqlite3
import datetime
from pathlib import Path

# Anchored to the repo root via core.paths, never to the process working
# directory, so the scheduler / Task Scheduler can launch jobs from anywhere.
from core.paths import DB_PATH, ensure_dirs

# Valid status values (mirrored in the CHECK constraint below).
# new -> cold -> F1 -> F2 (sequence complete); replied/failed are terminal
# off-ramps reachable from any sent stage. `sibling_replied` is also terminal:
# this contact never personally replied, but a COLLEAGUE at the same company did,
# so their sequence was killed (see mark_company_replied). Distinct from
# 'replied' so the dashboard can tell a real reply from a cascaded suppression.
STATUSES = {"new", "cold", "F1", "F2", "failed", "replied", "sibling_replied"}

# Any status meaning "someone at the company is in conversation, stop nudging".
REPLIED_STATUSES = ("replied", "sibling_replied")

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company      TEXT NOT NULL,
    designation  TEXT,
    mails        TEXT NOT NULL,               -- JSON array of WORKING addresses (up to 4 variations of one person)
    wrongMails   TEXT NOT NULL DEFAULT '[]',  -- JSON array of bounced addresses moved out
    subject      TEXT NOT NULL,
    placeholders TEXT NOT NULL,               -- JSON: {name, company, why_company, f2_content}
    status       TEXT NOT NULL DEFAULT 'new'
                 CHECK (status IN ('new','cold','F1','F2','failed','replied','sibling_replied')),
    sent_at      TEXT,                        -- ISO-8601 UTC of most recent send
    thread_id    TEXT,                        -- Gmail threadId, set on first send
    bounce_checked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_leads_status_sent_at ON leads(status, sent_at);
CREATE INDEX IF NOT EXISTS idx_leads_company ON leads(company);

-- v2: write-ahead send log. One row per LOGICAL send (lead + kind), never one
-- per attempt. `idem_key` is the primary key, so "send cold to lead 140" is
-- structurally impossible to record twice — a duplicate INSERT raises
-- IntegrityError before Gmail is ever called. That covers duplicates caused by
-- logic bugs. Duplicates caused by CRASH TIMING (Gmail accepted the message but
-- the process died before we recorded it) are covered separately: the row is
-- written as 'in_flight' BEFORE the API call, so any 'in_flight' row found by a
-- later process is a known-ambiguous send to reconcile against Gmail, not a
-- silent unknown. See engine.reconcile().
CREATE TABLE IF NOT EXISTS sends (
    idem_key   TEXT PRIMARY KEY,          -- '<lead_id>:<kind>'
    lead_id    INTEGER NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('cold','F1','F2')),
    mode       TEXT NOT NULL CHECK (mode IN ('cold','followup')),
    state      TEXT NOT NULL CHECK (state IN ('in_flight','sent','failed','dead')),
    attempts   INTEGER NOT NULL DEFAULT 0,
    send_date  TEXT NOT NULL,             -- LOCAL YYYY-MM-DD; drives the daily cap
    to_addrs   TEXT NOT NULL DEFAULT '[]',-- JSON, kept so reconcile can search Gmail
    subject    TEXT,
    thread_id  TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sent_at    TEXT,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_sends_date_mode ON sends(send_date, mode, state);
CREATE INDEX IF NOT EXISTS idx_sends_state ON sends(state);

-- v2: one row per (day, mode). Holds BOTH the persisted burst gap
-- (`next_burst_at` — the state that used to live in a sleeping process) and the
-- daily summary that makes silent failure visible. `completed` is the positive
-- signal: its ABSENCE for a weekday is what the dead-man check looks for.
CREATE TABLE IF NOT EXISTS run_days (
    run_date      TEXT NOT NULL,
    mode          TEXT NOT NULL,
    started_at    TEXT,
    next_burst_at TEXT,                   -- ISO local; the gap lives here, on disk
    last_burst_at TEXT,
    jitter_min    INTEGER,                -- the 0-10 min start jitter chosen today
    bursts        INTEGER NOT NULL DEFAULT 0,
    sent          INTEGER NOT NULL DEFAULT 0,
    errors        INTEGER NOT NULL DEFAULT 0,
    completed     INTEGER NOT NULL DEFAULT 0,
    reason        TEXT,
    PRIMARY KEY (run_date, mode)
);
"""


def utc_now_iso():
    """Current UTC time as an ISO-8601 string (no microseconds)."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_conn(db_path=None):
    """Open a connection. WAL + busy_timeout guard against a manual run
    overlapping a scheduled run. row_factory gives dict-like rows."""
    path = Path(db_path) if db_path else DB_PATH
    # sqlite3 creates the file but not its parent directory, and a fresh clone
    # has no data/ subdirectories at all. Without this the first connect dies
    # with "unable to open database file", which reads like a permissions bug.
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(db_path=None):
    """Idempotent — safe to call at the top of every script."""
    conn = get_conn(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return db_path or DB_PATH


# ---------------------------------------------------------------------------
# JSON field helpers
# ---------------------------------------------------------------------------

def load_mails(row):
    return json.loads(row["mails"]) if row["mails"] else []


def load_wrongmails(row):
    return json.loads(row["wrongMails"]) if row["wrongMails"] else []


def load_placeholders(row):
    return json.loads(row["placeholders"]) if row["placeholders"] else {}


def _dump(value):
    return json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def insert_lead(company, designation, mails, subject, placeholders,
                status="new", db_path=None):
    """Insert one lead row. `mails` is a list of addresses (lowercased here);
    `placeholders` is a dict {name, company, why_company, f2_content}."""
    mails = [m.strip().lower() for m in mails if m and m.strip()]
    conn = get_conn(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO leads (company, designation, mails, wrongMails,
                                  subject, placeholders, status)
               VALUES (?, ?, ?, '[]', ?, ?, ?)""",
            (company, designation, _dump(mails), subject,
             _dump(placeholders), status),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def mark_sent(lead_id, thread_id, new_status, sent_at=None, db_path=None):
    """Record a successful send: set thread_id (first send), sent_at, bump status.
    Commits immediately so a crash never causes a re-send."""
    sent_at = sent_at or utc_now_iso()
    conn = get_conn(db_path)
    try:
        conn.execute(
            "UPDATE leads SET thread_id=?, sent_at=?, status=? WHERE id=?",
            (thread_id, sent_at, new_status, lead_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_status(lead_id, status, db_path=None):
    conn = get_conn(db_path)
    try:
        conn.execute("UPDATE leads SET status=? WHERE id=?", (status, lead_id))
        conn.commit()
    finally:
        conn.close()


def set_bounce_checked(lead_id, checked_at=None, db_path=None):
    checked_at = checked_at or utc_now_iso()
    conn = get_conn(db_path)
    try:
        conn.execute("UPDATE leads SET bounce_checked_at=? WHERE id=?",
                     (checked_at, lead_id))
        conn.commit()
    finally:
        conn.close()


def update_mails(lead_id, mails, wrongmails, db_path=None):
    """Overwrite both address lists for a lead (used by the bounce sweep)."""
    conn = get_conn(db_path)
    try:
        conn.execute(
            "UPDATE leads SET mails=?, wrongMails=? WHERE id=?",
            (_dump(mails), _dump(wrongmails), lead_id),
        )
        conn.commit()
    finally:
        conn.close()


def move_to_wrongmails(lead_id, bad_addr, db_path=None):
    """Move one address from `mails` to `wrongMails`. Idempotent — if the
    address is already gone from `mails` it is a no-op. Returns the remaining
    working-address count (so callers can decide whether the lead is dead)."""
    bad_addr = bad_addr.strip().lower()
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT mails, wrongMails FROM leads WHERE id=?", (lead_id,)
        ).fetchone()
        if row is None:
            return None
        mails = json.loads(row["mails"]) if row["mails"] else []
        wrong = json.loads(row["wrongMails"]) if row["wrongMails"] else []
        if bad_addr in mails:
            mails = [m for m in mails if m != bad_addr]
            if bad_addr not in wrong:
                wrong.append(bad_addr)
            conn.execute(
                "UPDATE leads SET mails=?, wrongMails=? WHERE id=?",
                (_dump(mails), _dump(wrong), lead_id),
            )
            conn.commit()
        return len(mails)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_new_leads_grouped(db_path=None):
    """Return status='new' rows ordered by id, grouped into companies in
    first-seen order. Result: list of (company, [rows]) preserving order.
    send_cold.py applies the 15+ whole-company batch rule on top of this."""
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM leads WHERE status='new' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    groups = []          # list of [company, [rows]]
    index = {}           # company -> position in groups
    for r in rows:
        c = r["company"]
        if c not in index:
            index[c] = len(groups)
            groups.append([c, []])
        groups[index[c]][1].append(r)
    return [(c, rs) for c, rs in groups]


def get_due_followups(status, min_hours=48, db_path=None):
    """Rows at the given status whose last send was at least min_hours ago."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=min_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_conn(db_path)
    try:
        return conn.execute(
            """SELECT * FROM leads
               WHERE status=? AND sent_at IS NOT NULL AND sent_at <= ?
               ORDER BY sent_at ASC""",
            (status, cutoff),
        ).fetchall()
    finally:
        conn.close()


def company_has_reply(company, db_path=None):
    """True if anyone at this company is already in conversation — either a real
    'replied' or a cascaded 'sibling_replied'. Cheap status check; the trigger
    for suppressing follow-ups to colleagues."""
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM leads WHERE company=? AND status IN (?,?) LIMIT 1",
            (company, *REPLIED_STATUSES),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_company_threads(company, db_path=None):
    """All leads for a company that have been sent and are still live in the
    sequence (cold/F1/F2). Used to live-check whether ANYONE at the company has
    replied — including a contact who replied after finishing the sequence (F2),
    whose row would otherwise never be revisited by the follow-up queue."""
    conn = get_conn(db_path)
    try:
        return conn.execute(
            """SELECT * FROM leads
               WHERE company=? AND thread_id IS NOT NULL
               AND status IN ('cold','F1','F2')
               ORDER BY sent_at ASC""",
            (company,),
        ).fetchall()
    finally:
        conn.close()


def mark_company_replied(company, exclude_id=None, db_path=None):
    """One contact replied -> the whole company is in conversation. Mark every
    still-live lead (cold/F1/F2) at the company as 'sibling_replied' so colleagues
    stop getting nudged — distinct from the replier's own 'replied' status.
    `exclude_id` skips the row that already carries the real reply.
    Returns the number of colleague rows changed."""
    conn = get_conn(db_path)
    try:
        if exclude_id is not None:
            cur = conn.execute(
                "UPDATE leads SET status='sibling_replied' WHERE company=? AND id!=? "
                "AND status IN ('cold','F1','F2')",
                (company, exclude_id),
            )
        else:
            cur = conn.execute(
                "UPDATE leads SET status='sibling_replied' WHERE company=? "
                "AND status IN ('cold','F1','F2')",
                (company,),
            )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def get_active_rows_with_threads(db_path=None):
    """Rows that have been sent at least once and are still live in the
    sequence (cold/F1/F2) — candidates for the bounce sweep."""
    conn = get_conn(db_path)
    try:
        return conn.execute(
            """SELECT * FROM leads
               WHERE thread_id IS NOT NULL AND status IN ('cold','F1','F2')
               ORDER BY sent_at ASC"""
        ).fetchall()
    finally:
        conn.close()


def get_threads_for_reply_check(db_path=None):
    """Every lead with a thread that is not ALREADY known to have replied.

    Deliberately broader than get_active_rows_with_threads (cold/F1/F2 only):
    the daily reply sweep also wants finished 'F2' sequences and suppressed
    'sibling_replied' colleagues, because those are exactly the rows the
    follow-up path can never revisit — it only ever looks at leads that are due
    for a send."""
    conn = get_conn(db_path)
    try:
        return conn.execute(
            """SELECT * FROM leads
               WHERE thread_id IS NOT NULL AND status != 'replied'
               ORDER BY id"""
        ).fetchall()
    finally:
        conn.close()


def get_lead(lead_id, db_path=None):
    conn = get_conn(db_path)
    try:
        return conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    finally:
        conn.close()


def all_leads(status=None, db_path=None):
    conn = get_conn(db_path)
    try:
        if status:
            return conn.execute(
                "SELECT * FROM leads WHERE status=? ORDER BY id", (status,)
            ).fetchall()
        return conn.execute("SELECT * FROM leads ORDER BY id").fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# v2: send log (idempotency)
# ---------------------------------------------------------------------------

def local_today():
    """Local (IST) calendar date. The send windows and daily caps are all
    wall-clock concepts, so the cap must key off LOCAL date, not UTC."""
    return datetime.datetime.now().strftime("%Y-%m-%d")


def idem_key(lead_id, kind):
    """The idempotency key for one LOGICAL send. Deterministic, so the same
    logical send always collides with itself no matter who computes it."""
    return f"{lead_id}:{kind}"


def claim_send(lead_id, kind, mode, to_addrs, subject, retry_max,
               send_date=None, db_path=None):
    """Write-ahead the INTENT to send, before touching Gmail.

    Returns one of:
      'claimed'   -> caller owns this send and must call finish_send/fail_send
      'duplicate' -> already sent; caller must NOT send (this is the guarantee)
      'dead'      -> retry budget exhausted; needs a human
      'ambiguous' -> a previous process left it in_flight; reconcile owns it,
                     caller must skip rather than risk a double-send

    The INSERT is the enforcement point: idem_key is the PRIMARY KEY, so a
    second claim for the same logical send cannot be recorded, whatever the
    calling code believes.
    """
    key = idem_key(lead_id, kind)
    now = utc_now_iso()
    send_date = send_date or local_today()
    conn = get_conn(db_path)
    try:
        try:
            conn.execute(
                """INSERT INTO sends (idem_key, lead_id, kind, mode, state,
                                      attempts, send_date, to_addrs, subject,
                                      created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'in_flight', 1, ?, ?, ?, ?, ?)""",
                (key, lead_id, kind, mode, send_date, _dump(to_addrs),
                 subject, now, now),
            )
            conn.commit()
            return "claimed"
        except sqlite3.IntegrityError:
            pass  # already exists — fall through and inspect its state

        row = conn.execute("SELECT * FROM sends WHERE idem_key=?", (key,)).fetchone()
        if row is None:                      # vanished between the two statements
            return "ambiguous"
        if row["state"] == "sent":
            return "duplicate"
        if row["state"] == "dead":
            return "dead"
        if row["state"] == "in_flight":
            return "ambiguous"

        # state == 'failed' -> a genuine retry. Bump the attempt counter on the
        # SAME row; the key identifies the logical send, the row tracks tries.
        if row["attempts"] >= retry_max:
            conn.execute(
                "UPDATE sends SET state='dead', updated_at=? WHERE idem_key=?",
                (now, key),
            )
            conn.commit()
            return "dead"
        conn.execute(
            """UPDATE sends SET state='in_flight', attempts=attempts+1,
                                send_date=?, updated_at=? WHERE idem_key=?""",
            (send_date, now, key),
        )
        conn.commit()
        return "claimed"
    finally:
        conn.close()


def finish_send(lead_id, kind, thread_id, db_path=None):
    """Mark the logical send delivered. Called immediately after Gmail accepts."""
    now = utc_now_iso()
    conn = get_conn(db_path)
    try:
        conn.execute(
            """UPDATE sends SET state='sent', thread_id=?, sent_at=?,
                                updated_at=?, last_error=NULL
               WHERE idem_key=?""",
            (thread_id, now, now, idem_key(lead_id, kind)),
        )
        conn.commit()
    finally:
        conn.close()


def fail_send(lead_id, kind, error, retry_max, db_path=None):
    """Record a failed attempt. Goes 'dead' once attempts hit retry_max, so a
    permanently-bad address can't burn quota forever. Returns the new state."""
    now = utc_now_iso()
    key = idem_key(lead_id, kind)
    conn = get_conn(db_path)
    try:
        row = conn.execute("SELECT attempts FROM sends WHERE idem_key=?",
                           (key,)).fetchone()
        attempts = row["attempts"] if row else 1
        state = "dead" if attempts >= retry_max else "failed"
        conn.execute(
            "UPDATE sends SET state=?, updated_at=?, last_error=? WHERE idem_key=?",
            (state, now, str(error)[:500], key),
        )
        conn.commit()
        return state
    finally:
        conn.close()


def get_in_flight(db_path=None):
    """Ambiguous sends: Gmail may or may not have accepted them. Resolved by
    engine.reconcile() against Gmail itself, never by guessing."""
    conn = get_conn(db_path)
    try:
        return conn.execute(
            "SELECT * FROM sends WHERE state='in_flight' ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()


def count_sends_today(run_date, mode, db_path=None):
    """Sends charged against today's cap. Counts 'in_flight' as well as 'sent':
    an unresolved send is assumed to have gone out, so the cap errs toward
    under-sending rather than over-sending."""
    conn = get_conn(db_path)
    try:
        return conn.execute(
            """SELECT COUNT(*) FROM sends
               WHERE send_date=? AND mode=? AND state IN ('in_flight','sent')""",
            (run_date, mode),
        ).fetchone()[0]
    finally:
        conn.close()


def get_dead_sends(db_path=None):
    conn = get_conn(db_path)
    try:
        return conn.execute(
            "SELECT * FROM sends WHERE state='dead' ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# v2: run_days (persisted burst gap + daily summary)
# ---------------------------------------------------------------------------

def get_or_create_run_day(run_date, mode, db_path=None):
    conn = get_conn(db_path)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO run_days (run_date, mode, started_at)
               VALUES (?, ?, ?)""",
            (run_date, mode, utc_now_iso()),
        )
        conn.commit()
        return conn.execute(
            "SELECT * FROM run_days WHERE run_date=? AND mode=?", (run_date, mode)
        ).fetchone()
    finally:
        conn.close()


def set_next_burst(run_date, mode, next_iso, jitter_min=None, db_path=None):
    """Persist when the next burst may start. THIS is the gap — it lives on
    disk, so a crash or a sleeping PC cannot lose it."""
    conn = get_conn(db_path)
    try:
        if jitter_min is None:
            conn.execute(
                "UPDATE run_days SET next_burst_at=? WHERE run_date=? AND mode=?",
                (next_iso, run_date, mode),
            )
        else:
            conn.execute(
                """UPDATE run_days SET next_burst_at=?, jitter_min=?
                   WHERE run_date=? AND mode=?""",
                (next_iso, jitter_min, run_date, mode),
            )
        conn.commit()
    finally:
        conn.close()


def record_burst(run_date, mode, sent, errors, db_path=None):
    conn = get_conn(db_path)
    try:
        conn.execute(
            """UPDATE run_days
               SET bursts=bursts+1, sent=sent+?, errors=errors+?, last_burst_at=?
               WHERE run_date=? AND mode=?""",
            (sent, errors, utc_now_iso(), run_date, mode),
        )
        conn.commit()
    finally:
        conn.close()


def complete_run_day(run_date, mode, reason, db_path=None):
    conn = get_conn(db_path)
    try:
        conn.execute(
            "UPDATE run_days SET completed=1, reason=? WHERE run_date=? AND mode=?",
            (reason, run_date, mode),
        )
        conn.commit()
    finally:
        conn.close()


def recent_run_days(limit=20, db_path=None):
    """Backing query for the dead-man check: a weekday with no run_days row (or
    completed=0) is a silently-missed run."""
    conn = get_conn(db_path)
    try:
        return conn.execute(
            "SELECT * FROM run_days ORDER BY run_date DESC, mode LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()
