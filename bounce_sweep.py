"""
bounce_sweep.py — daily inbox reconciliation. Two passes, one token.

PASS 1 (bounces): scans for recent mailer-daemon messages, extracts each failed
address, and moves it out of the matching lead's `mails` into `wrongMails`. A
lead whose `mails` becomes empty (every variation bounced) is marked 'failed'.
Idempotent — re-running never double-moves an address.

PASS 2 (replies): lists every inbox thread id from the last REPLY_LOOKBACK and
intersects it with the thread ids we already store. A match means someone
replied inside one of our outreach threads.

WHY PASS 2 EXISTS: followup.py only checks for replies on companies that have a
send DUE. Once a company finishes F2, nothing ever looks at it again, so a late
reply would sit undetected forever. This sweep is the backstop, and it is cheap
because its cost scales with INBOX volume, not lead count: one 500-thread list
call covers the whole pipeline no matter how big it grows. The per-lead
alternative would be one API call per finished lead, every day, forever.

Nothing is marked 'ghosted' here. Silence is not an event and needs no API call
— a lead sitting at F2 with no reply already IS the ghosted state, derivable
from the DB whenever you want it.

Runs daily at 11:00 Mon-Fri via scheduler.py, with catch-up if the PC was off.
That is 30 minutes before the follow-up window opens, so follow-ups start with
fresh bounce AND reply data, and followup.py's cheap DB check absorbs most of
what this pass found instead of paying for live Gmail calls.

Flags: --dry-run, --db PATH
"""

import argparse

import db
import gmail
from runlog import get_logger

NEWER_THAN = "3d"          # bounce lookback
REPLY_LOOKBACK = "7d"      # reply lookback. Wider than the daily cadence on
                           # purpose: if the PC is off for a few days, the next
                           # run still catches everything it missed.


def sweep_bounces(token, args, log):
    bad_addrs = gmail.search_daemon_bounces(token, NEWER_THAN)
    log.info("Found %d bounced address(es) in daemon mail (dry_run=%s).",
             len(bad_addrs), args.dry_run)
    if not bad_addrs:
        log.info("No bounces to reconcile.")
        return

    rows = db.get_active_rows_with_threads(args.db_path)
    moved = failed = 0

    for row in rows:
        mails = db.load_mails(row)
        hits = [a for a in mails if a in bad_addrs]
        if not hits:
            continue

        for addr in hits:
            log.info("Bounce: id=%s %s -> moving %s to wrongMails.",
                     row["id"], row["company"], addr)
            if not args.dry_run:
                db.move_to_wrongmails(row["id"], addr, args.db_path)
            moved += 1

        if not args.dry_run:
            db.set_bounce_checked(row["id"], db_path=args.db_path)
            fresh = db.get_lead(row["id"], args.db_path)
            if not db.load_mails(fresh):
                db.mark_status(row["id"], "failed", args.db_path)
                failed += 1
                log.info("id=%s %s — all addresses bounced, marked FAILED.",
                         row["id"], row["company"])
        elif all(a in bad_addrs for a in mails):
            failed += 1
            log.info("[dry-run] id=%s %s would be marked FAILED (all bounced).",
                     row["id"], row["company"])

    log.info("Bounce pass complete: %d addresses moved, %d leads failed.",
             moved, failed)


def sweep_replies(token, args, log):
    rows = db.get_threads_for_reply_check(args.db_path)
    if not rows:
        log.info("Reply pass: no threads to check.")
        return

    by_thread = {}
    for r in rows:
        by_thread.setdefault(r["thread_id"], []).append(r)

    inbox = gmail.list_inbox_thread_ids(token, REPLY_LOOKBACK)
    hits = set(by_thread) & inbox
    log.info("Reply pass: %d inbox thread(s) in last %s, %d tracked thread(s), "
             "%d match.", len(inbox), REPLY_LOOKBACK, len(by_thread), len(hits))

    replied = cascaded = 0
    for tid in sorted(hits):
        # The query already drops daemon mail, but verify per match: this
        # confirms a real human message (not us, not a daemon) and costs one
        # call per MATCH, which is a handful a day, not one per lead.
        try:
            if gmail.human_reply_count(token, tid) < 1:
                log.info("thread=%s in inbox but no human message — skipping.", tid)
                continue
        except Exception as e:
            log.error("Reply verify FAILED thread=%s: %s — leaving unchanged.",
                      tid, e)
            continue

        for r in by_thread[tid]:
            log.info("REPLY id=%s %s (%s -> replied)",
                     r["id"], r["company"], r["status"])
            if not args.dry_run:
                db.mark_status(r["id"], "replied", args.db_path)
                n = db.mark_company_replied(r["company"], exclude_id=r["id"],
                                            db_path=args.db_path)
                if n:
                    log.info("  cascaded 'sibling_replied' to %d colleague(s) "
                             "at %s.", n, r["company"])
                cascaded += n
            replied += 1

    log.info("Reply pass complete: %d lead(s) marked replied, %d colleague(s) "
             "cascaded.", replied, cascaded)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", dest="db_path", default=None)
    args = ap.parse_args()

    log = get_logger("bounce_sweep", args.db_path)
    db.init_db(args.db_path)

    token = gmail.get_access_token()
    sweep_bounces(token, args, log)
    sweep_replies(token, args, log)


if __name__ == "__main__":
    main()
