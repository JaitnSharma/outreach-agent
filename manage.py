"""
manage.py — manual DB operations and repair CLI.

Until the updateDB skill is built, this is how leads get into the DB and how
'failed' rows get repaired. Stdlib only.

Examples:
  python manage.py add --company Acme --designation Founder \\
      --mails a@acme.com,a.founder@gmail.com \\
      --name Aisha --why "Acme builds ..." --f2 "I understand your time ..."
  python manage.py list
  python manage.py list --status failed
  python manage.py show 3
  python manage.py set-status 3 cold
  python manage.py readd-address 3 a@acme.com     # move back from wrongMails
  python manage.py backdate 3 --hours 72          # for testing follow-ups

All commands accept --db PATH to target a test database.
"""

import json
import argparse
import datetime

import db


def cmd_add(args):
    mails = [m.strip() for m in args.mails.split(",") if m.strip()]
    placeholders = {
        "name": args.name,
        "company": args.company,
        "why_company": args.why or "",
        "f2_content": args.f2 or "",
    }
    subject = args.subject or f"Quick question about expenses at {args.company}"
    lead_id = db.insert_lead(args.company, args.designation, mails, subject,
                             placeholders, db_path=args.db_path)
    print(f"Inserted lead id={lead_id} ({args.company}) -> {mails}")


def _print_row(r):
    mails = db.load_mails(r)
    wrong = db.load_wrongmails(r)
    print(f"[{r['id']:>4}] {r['status']:<7} {r['company']} "
          f"({r['designation'] or '-'})")
    print(f"        mails: {mails}")
    if wrong:
        print(f"        wrongMails: {wrong}")
    print(f"        sent_at: {r['sent_at']}  thread: {r['thread_id']}")


def cmd_list(args):
    rows = db.all_leads(args.status, args.db_path)
    if not rows:
        print("(no rows)")
        return
    for r in rows:
        _print_row(r)
    print(f"\n{len(rows)} row(s).")


def cmd_show(args):
    r = db.get_lead(args.id, args.db_path)
    if not r:
        print(f"No lead id={args.id}")
        return
    _print_row(r)
    print("        placeholders:")
    print("        " + json.dumps(db.load_placeholders(r), indent=2,
                                  ensure_ascii=False).replace("\n", "\n        "))


def cmd_set_status(args):
    if args.status not in db.STATUSES:
        print(f"Invalid status. Must be one of {sorted(db.STATUSES)}")
        return
    db.mark_status(args.id, args.status, args.db_path)
    print(f"Lead id={args.id} status -> {args.status}")


def cmd_readd(args):
    """Move an address from wrongMails back to mails (after fixing a typo)."""
    r = db.get_lead(args.id, args.db_path)
    if not r:
        print(f"No lead id={args.id}")
        return
    mails = db.load_mails(r)
    wrong = db.load_wrongmails(r)
    addr = args.address.strip().lower()
    if addr in wrong:
        wrong.remove(addr)
    if addr not in mails:
        mails.append(addr)
    db.update_mails(args.id, mails, wrong, args.db_path)
    print(f"Lead id={args.id}: {addr} moved back to mails -> {mails}")


def cmd_backdate(args):
    """Set sent_at to N hours ago (testing follow-up eligibility)."""
    ts = (datetime.datetime.now(datetime.timezone.utc)
          - datetime.timedelta(hours=args.hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = db.get_conn(args.db_path)
    try:
        conn.execute("UPDATE leads SET sent_at=? WHERE id=?", (ts, args.id))
        conn.commit()
    finally:
        conn.close()
    print(f"Lead id={args.id} sent_at -> {ts} ({args.hours}h ago)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", dest="db_path", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument("--company", required=True)
    a.add_argument("--designation", default=None)
    a.add_argument("--mails", required=True, help="comma-separated addresses")
    a.add_argument("--name", required=True, help="contact first name")
    a.add_argument("--why", default=None, help="why-company section (cold)")
    a.add_argument("--f2", default=None, help="F2 middle paragraph")
    a.add_argument("--subject", default=None)
    a.set_defaults(func=cmd_add)

    a = sub.add_parser("list")
    a.add_argument("--status", default=None)
    a.set_defaults(func=cmd_list)

    a = sub.add_parser("show")
    a.add_argument("id", type=int)
    a.set_defaults(func=cmd_show)

    a = sub.add_parser("set-status")
    a.add_argument("id", type=int)
    a.add_argument("status")
    a.set_defaults(func=cmd_set_status)

    a = sub.add_parser("readd-address")
    a.add_argument("id", type=int)
    a.add_argument("address")
    a.set_defaults(func=cmd_readd)

    a = sub.add_parser("backdate")
    a.add_argument("id", type=int)
    a.add_argument("--hours", type=int, default=72)
    a.set_defaults(func=cmd_backdate)

    args = ap.parse_args()
    db.init_db(args.db_path)
    args.func(args)


if __name__ == "__main__":
    main()
