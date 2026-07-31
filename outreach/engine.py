"""
engine.py — tick-driven, burst-paced send engine shared by cold and follow-up.

THE RULE: never hold state that matters in a process you cannot guarantee is
alive. This engine is invoked by scheduler.py roughly once a minute during its
window. Each invocation is short-lived and does exactly ONE of:

    * nothing            (mid-gap / capped / outside window / past 5pm)
    * run ONE burst      (<=15 mails, company-rounded, ~n*40s), then persist
                         `next_burst_at = now + rand(20,30)min` and exit

The gap between bursts therefore lives on DISK (run_days.next_burst_at), not in
a sleeping process. Consequences, all free:

    * a crash loses at most one in-flight burst, never the day
    * PC sleeps mid-gap -> wakes -> next tick sees next_burst_at in the past and
      fires immediately, no resume logic anywhere
    * the follow-up reply cache cannot go stale across a multi-hour window,
      because every burst is a brand new process

Bursts are NOT durable objects. Only sends are. There is no "resume burst at
mail 7": the next tick recounts what is already sent today and re-batches
whoever is still due. That is the simplification that makes this tractable.

Idempotency (the "payment went through but the confirmation write failed"
problem) is handled in three layers — see db.claim_send and reconcile() below.

Providers supply only the mode-specific parts (duck-typed, see send_cold.py):
    provider.mode                  -> 'cold' | 'followup'
    provider.build_queue(ctx)      -> [(company, [rows])] in send order
    provider.prepare(ctx, row)     -> SendJob or None (None = skip this lead)
    provider.on_sent(ctx, row, job, thread_id)
"""

import json
import time
import random
import argparse
import datetime
from pathlib import Path

from core import paths
from outreach import db
from outreach import gmail
from core.runlog import get_logger, paused, single_instance

# Today-only pacing override. Contents: "<YYYY-MM-DD> <multiplier>", e.g.
# "2026-07-27 2.0". Deliberately dated: a stale date is IGNORED, so a one-day
# sprint can never quietly become the permanent cadence — which would undo the
# whole reason this engine paces at all.
SPEED_FILE = paths.SPEED_FILE
SPEED_CEILING = 4.0          # a typo in that file must not become a 100x blast

# --- Pacing. Every number here is a deliberate, human-set value. ------------
PER_MAIL_SECONDS = 40        # burst duration = (mails in burst) * 40s
PER_MAIL_JITTER = 20         # +20 / -20 around the adaptive per-mail gap
MAIL_GAP_FLOOR = 5           # never fire two mails closer than this
MAIL_GAP_CEILING = 120       # never stall longer than this inside a burst
GAP_MIN_MINUTES = 20         # dead zone between bursts
GAP_MAX_MINUTES = 30
START_JITTER_MAX = 10        # 0-10 min before the first burst, so the daily
                             # first-mail timestamp never repeats
BURST_MAX = 15               # max mails per burst, company-rounded (overflow
                             # allowed so a company is never split)
BUDGET_JITTER = 0.05         # +/-5% on the burst ENVELOPE. Without this the
                             # burst duration is a perfectly linear function of
                             # mail count: the gaps inside are noisy but always
                             # sum to the same fixed total.
RETRY_MAX = 3                # attempts before a send is marked dead
HARD_STOP = datetime.time(17, 0)   # nothing goes out after 5pm. Ever.

MODES = {
    "cold": {
        "window": (datetime.time(8, 30), datetime.time(11, 0)),
        "cap": 50,
    },
    "followup": {
        "window": (datetime.time(11, 30), datetime.time(16, 30)),
        "cap": 100,
    },
}


class Ctx:
    """Everything a provider needs to build its queue and render a send."""

    def __init__(self, token, db_path, dry_run, log):
        self.token = token
        self.db_path = db_path
        self.dry_run = dry_run
        self.log = log


class SendJob:
    """One rendered, ready-to-send email."""

    __slots__ = ("lead_id", "kind", "company", "to_list", "subject", "html",
                 "thread_id")

    def __init__(self, lead_id, kind, company, to_list, subject, html,
                 thread_id=None):
        self.lead_id = lead_id
        self.kind = kind              # 'cold' | 'F1' | 'F2'
        self.company = company
        self.to_list = to_list
        self.subject = subject
        self.html = html
        self.thread_id = thread_id


def _at(now, t):
    return now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)


def speed_multiplier(log=None):
    """Read the today-only pacing override. Returns 1.0 (normal) unless
    SPEED_TODAY exists AND is dated today. Clamped to SPEED_CEILING."""
    if not SPEED_FILE.exists():
        return 1.0
    try:
        parts = SPEED_FILE.read_text(encoding="utf-8").split()
        date_s, mult = parts[0], float(parts[1])
    except Exception as e:
        if log:
            log.warning("SPEED_TODAY unreadable (%s) — using normal pacing.", e)
        return 1.0
    if date_s != db.local_today():
        if log:
            log.warning("SPEED_TODAY is dated %s, not today — EXPIRED, using "
                        "normal pacing.", date_s)
        return 1.0
    mult = max(1.0, min(SPEED_CEILING, mult))
    if log:
        log.warning("SPEED_TODAY active: pacing %.1fx for %s only.", mult, date_s)
    return mult


# ---------------------------------------------------------------------------
# Reconciliation — resolving ambiguous sends
# ---------------------------------------------------------------------------

def reconcile(args, log):
    """Resolve every 'in_flight' send against Gmail's own record.

    An 'in_flight' row means a previous process wrote the intent, called Gmail,
    and died before recording the outcome. We do NOT guess: guessing 'sent'
    silently drops a person, guessing 'not sent' emails a founder twice. We ask
    Gmail whether the message is in Sent, exactly as you would read the payment
    provider's records when your own confirmation write failed.

    Returns a Gmail token if one was fetched, so the caller can reuse it.
    """
    if args.dry_run:
        return None
    pending = db.get_in_flight(args.db_path)
    if not pending:
        return None

    token = gmail.get_access_token()
    log.warning("RECONCILE start — %d ambiguous send(s) from a previous run",
                len(pending))
    for r in pending:
        addrs = json.loads(r["to_addrs"]) if r["to_addrs"] else []
        try:
            thread_id = gmail.find_sent_message(token, addrs, r["subject"])
        except Exception as e:
            log.error("RECONCILE key=%s probe failed: %s — leaving in_flight",
                      r["idem_key"], e)
            continue

        if thread_id:
            db.finish_send(r["lead_id"], r["kind"], thread_id, args.db_path)
            # kind maps 1:1 onto the lead status ('cold'/'F1'/'F2').
            db.mark_sent(r["lead_id"], thread_id, r["kind"], db_path=args.db_path)
            log.warning("RECONCILE key=%s DID send (thread %s) — duplicate avoided",
                        r["idem_key"], thread_id)
        else:
            state = db.fail_send(r["lead_id"], r["kind"],
                                 "reconciled: not found in Sent",
                                 RETRY_MAX, args.db_path)
            log.warning("RECONCILE key=%s did NOT send — returned to queue (%s)",
                        r["idem_key"], state)
    return token


# ---------------------------------------------------------------------------
# Batching + sending
# ---------------------------------------------------------------------------

def batch_by_company(groups, limit=BURST_MAX):
    """Take WHOLE companies until the running count reaches `limit`, including
    the company that crosses it. Never splits a company across bursts."""
    out = []
    for company, rows in groups:
        if len(out) >= limit:
            break
        out.extend((company, r) for r in rows)
    return out


def _send_one(provider, ctx, row, mode, today, args, log):
    """Returns 'sent' | 'error' | 'skip'."""
    job = provider.prepare(ctx, row)
    if job is None:
        return "skip"

    if args.dry_run:
        log.info("[dry-run] would send %s id=%s %s -> %s",
                 job.kind, job.lead_id, job.company, job.to_list)
        return "sent"

    # Layer 1+2: write the INTENT before calling Gmail. The PRIMARY KEY on
    # idem_key makes a second claim for the same logical send impossible.
    claim = db.claim_send(job.lead_id, job.kind, mode, job.to_list, job.subject,
                          RETRY_MAX, today, args.db_path)
    if claim == "duplicate":
        log.warning("SKIP-DUP %s id=%s %s — already recorded as sent",
                    job.kind, job.lead_id, job.company)
        return "skip"
    if claim == "dead":
        log.error("SKIP-DEAD %s id=%s %s — %d attempts exhausted, needs a human",
                  job.kind, job.lead_id, job.company, RETRY_MAX)
        return "skip"
    if claim == "ambiguous":
        log.warning("SKIP-AMBIGUOUS %s id=%s %s — in_flight, reconcile owns it",
                    job.kind, job.lead_id, job.company)
        return "skip"

    # Claimed. The intent is durable; the Gmail call is now the only unknown,
    # and if we die here the row stays 'in_flight' for reconcile() to resolve.
    try:
        result = gmail.send_message(ctx.token, job.to_list, job.subject,
                                    job.html, thread_id=job.thread_id)
        thread_id = result["threadId"]
        db.finish_send(job.lead_id, job.kind, thread_id, args.db_path)
        provider.on_sent(ctx, row, job, thread_id)
        log.info("SENT %s id=%s %s -> %s (thread %s)",
                 job.kind, job.lead_id, job.company, job.to_list, thread_id)
        return "sent"
    except Exception as e:
        state = db.fail_send(job.lead_id, job.kind, e, RETRY_MAX, args.db_path)
        log.error("FAILED %s id=%s %s -> %s: %s (now %s)",
                  job.kind, job.lead_id, job.company, job.to_list, e, state)
        return "error"


def _run_burst(provider, ctx, batch, mode, today, end_dt, args, log, speed=1.0):
    """One burst: send every mail in `batch`, paced to land in ~n*40s total.

    Per-mail spacing is 40s +/-20s, ADAPTIVELY RECOMPUTED after each send from
    the time actually left in the budget, so a slow Gmail call or a skipped
    lead tightens the rest instead of letting the burst drift long.

    `speed` compresses the whole burst (2.0 = half the spacing). See
    speed_multiplier — it is a dated, self-expiring override.
    """
    n = len(batch)
    per_mail = PER_MAIL_SECONDS / speed
    jitter = PER_MAIL_JITTER / speed
    # Jitter the envelope, not just the gaps inside it, so burst duration stops
    # being a deterministic function of mail count.
    scale = random.uniform(1 - BUDGET_JITTER, 1 + BUDGET_JITTER)
    budget = n * per_mail * scale
    companies = len({c for c, _ in batch})
    t0 = time.monotonic()
    log.info("BURST-START mode=%s mails=%d companies=%d budget=%.1fmin "
             "(%.0f%% of nominal) speed=%.1fx",
             mode, n, companies, budget / 60.0, scale * 100, speed)

    sent = errors = skipped = 0
    for i, (_company, row) in enumerate(batch):
        # The 5pm wall is checked per-mail, not just per-burst: a burst that
        # starts at 16:52 must stop AT 17:00, mid-burst.
        #
        # --force skips it. Without this, a manual/demo run outside the window
        # computes an end_dt already in the past and cuts on the FIRST mail, so
        # --force silently sends nothing. Scheduled runs never pass --force, so
        # the wall still holds everywhere it matters.
        if not args.force and datetime.datetime.now() >= end_dt:
            log.warning("BURST-CUT mode=%s stopped at mail %d/%d — window edge",
                        mode, i + 1, n)
            break

        outcome = _send_one(provider, ctx, row, mode, today, args, log)
        if outcome == "sent":
            sent += 1
        elif outcome == "error":
            errors += 1
        else:
            skipped += 1

        gaps_left = n - 1 - i
        if gaps_left <= 0:
            break
        elapsed = time.monotonic() - t0
        base = (budget - elapsed) / (gaps_left + 1)     # adaptive recompute
        gap = base + random.uniform(-jitter, jitter)
        gap = max(MAIL_GAP_FLOOR, min(MAIL_GAP_CEILING, gap))
        if args.dry_run:
            # Report the pacing without living through it, so a dry-run of a
            # 15-mail burst takes a second instead of ten minutes.
            log.info("[dry-run] would wait %.0fs before the next mail", gap)
            continue
        time.sleep(gap)

    actual = (time.monotonic() - t0) / 60.0
    db.record_burst(today, mode, sent, errors, args.db_path)
    log.info("BURST-END mode=%s sent=%d errors=%d skipped=%d "
             "actual=%.1fmin budget=%.1fmin", mode, sent, errors, skipped,
             actual, budget / 60.0)
    return sent


def _finish(today, mode, reason, args, log):
    """Mark the day done and emit the ONE greppable line that answers
    'did today work?' without reading the rest of the log."""
    day = db.get_or_create_run_day(today, mode, args.db_path)
    db.complete_run_day(today, mode, reason, args.db_path)
    sent = db.count_sends_today(today, mode, args.db_path)
    log.info("SUMMARY mode=%s date=%s sent=%d/%d bursts=%d errors=%d "
             "jitter=%sm completed=yes reason=%s",
             mode, today, sent, MODES[mode]["cap"], day["bursts"],
             day["errors"], day["jitter_min"], reason)


# ---------------------------------------------------------------------------
# The tick
# ---------------------------------------------------------------------------

def _tick(provider, args, log):
    mode = provider.mode
    cfg = MODES[mode]
    db.init_db(args.db_path)

    now = datetime.datetime.now()
    today = db.local_today()

    if now.weekday() > 4 and not args.force:
        return                                  # Mon-Fri only

    # Ambiguous sends are resolved BEFORE any new send decision, so the daily
    # cap and the queue both see accurate state.
    token = reconcile(args, log)

    day = db.get_or_create_run_day(today, mode, args.db_path)
    if day["completed"] and not args.force:
        return

    win_start, win_end = cfg["window"]
    start_dt = _at(now, win_start)
    end_dt = min(_at(now, win_end), _at(now, HARD_STOP))

    if not args.force:
        if now < start_dt:
            return                              # window hasn't opened
        if now >= end_dt:
            _finish(today, mode, "window closed", args, log)
            return

    # First tick of the day: choose the 0-10 min start jitter. If we are joining
    # LATE (PC was off at window start), jitter from now instead of back-dating,
    # so a missed morning does not fire an instant burst at an odd time.
    if day["next_burst_at"] is None:
        jitter = random.randint(0, START_JITTER_MAX * 60)
        first = start_dt + datetime.timedelta(seconds=jitter)
        if first < now:
            first = now + datetime.timedelta(
                seconds=random.randint(0, START_JITTER_MAX * 60))
        db.set_next_burst(today, mode, first.isoformat(timespec="seconds"),
                          jitter // 60, args.db_path)
        log.info("DAY-START mode=%s jitter=%dm first_burst=%s",
                 mode, jitter // 60, first.strftime("%H:%M:%S"))
        day = db.get_or_create_run_day(today, mode, args.db_path)

    if not args.force:
        next_at = datetime.datetime.fromisoformat(day["next_burst_at"])
        if now < next_at:
            return                              # mid-gap. The gap is on disk.

    sent_today = db.count_sends_today(today, mode, args.db_path)
    if sent_today >= cfg["cap"]:
        _finish(today, mode, f"cap reached ({sent_today}/{cfg['cap']})", args, log)
        return

    if token is None and not args.dry_run:
        token = gmail.get_access_token()
    ctx = Ctx(token, args.db_path, args.dry_run, log)

    groups = provider.build_queue(ctx)
    if not groups:
        _finish(today, mode, "queue empty", args, log)
        return

    batch = batch_by_company(groups, BURST_MAX)
    if not batch:
        _finish(today, mode, "queue empty after batching", args, log)
        return

    # Read the override only here, right before it matters — so the per-minute
    # no-op ticks never touch the file or spam the log.
    speed = speed_multiplier(log)
    _run_burst(provider, ctx, batch, mode, today, end_dt, args, log, speed)

    if args.dry_run or args.force:
        log.info("(%s) not scheduling a real gap.",
                 "dry-run" if args.dry_run else "force")
        return

    # Persist the dead zone before this process exits.
    gap = random.randint(int(GAP_MIN_MINUTES * 60 / speed),
                         int(GAP_MAX_MINUTES * 60 / speed))
    nxt = datetime.datetime.now() + datetime.timedelta(seconds=gap)
    if nxt >= end_dt:
        _finish(today, mode, "next burst would fall outside the window", args, log)
        return
    if db.count_sends_today(today, mode, args.db_path) >= cfg["cap"]:
        _finish(today, mode, "cap reached", args, log)
        return
    db.set_next_burst(today, mode, nxt.isoformat(timespec="seconds"),
                      None, args.db_path)
    log.info("GAP mode=%s %.1fmin next_burst=%s",
             mode, gap / 60.0, nxt.strftime("%H:%M:%S"))


def tick(provider, args, log):
    if paused():
        log.debug("PAUSED sentinel present — no-op.")
        return
    # A burst runs for ~10 minutes while the scheduler keeps ticking every 60s.
    # This lock is what makes those overlapping ticks cheap no-ops.
    with single_instance(f"v2_{provider.mode}") as ok:
        if not ok:
            log.debug("Another %s tick is mid-burst — no-op.", provider.mode)
            return
        _tick(provider, args, log)


def run(provider):
    """Standard entry point for send_cold.py / followup.py."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="select + render, but never call Gmail or write state")
    ap.add_argument("--db", dest="db_path", default=None)
    ap.add_argument("--force", action="store_true",
                    help="ignore window/gap/weekday gating (testing only)")
    args = ap.parse_args()
    log = get_logger(provider.mode, args.db_path)
    if args.force:
        log.warning("--force: window/gap gating bypassed. Cap and idempotency "
                    "still enforced.")
    tick(provider, args, log)
