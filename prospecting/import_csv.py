"""
import_csv.py — push a findprospects CSV into prospects.db.

Step 2 of the prospecting workflow:
    1. findprospects skill -> runs/<date>.csv (Work Email already filled)
    2. THIS script         -> prospects.db as status='new'

Reads the CSV, inserts one lead row per contact via db.insert_lead(). Every row
that survives the gates auto-sends on the next scheduled send_cold.py run, so the
gates are the safety: no email -> skip, already in DB -> skip, blacklisted -> skip.

Expected header (findprospects writes exactly this):
    full_name,first_name,company,designation,linkedin_url,company_domain,
    company_social_url,why_company,f2_content,Work Email

Only `company`, `Work Email`, `first_name`, `designation`, `why_company` and
`f2_content` are used for the DB row — `linkedin_url` and the domain columns are
carried for the email-finder handoff and dropped here.

Usage:
    python brace.py import runs/2026-07-30.csv
    python brace.py import <csv> --dry-run          # show what would happen, write nothing
    python brace.py import <csv> --db PATH           # target an alternate DB
    python brace.py import <csv> --subject "..."     # override the default subject
"""

import csv
import sys
import argparse
from pathlib import Path

from outreach import db
from core.paths import BLACKLIST_PATH

DEFAULT_SUBJECT = "Quick question about expenses at {company}"

REQUIRED_COLUMNS = {"company", "first_name", "why_company", "f2_content", "Work Email"}


def load_blacklist():
    """Lowercased non-empty, non-comment lines from blacklist.txt."""
    if not BLACKLIST_PATH.exists():
        return set()
    out = set()
    for line in BLACKLIST_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip().lower()
        if s and not s.startswith("#"):
            out.add(s)
    return out


def existing_keys(db_path):
    """Return (companies_lower, emails_lower) already in prospects.db, for dedupe."""
    companies, emails = set(), set()
    for r in db.all_leads(db_path=db_path):
        companies.add((r["company"] or "").strip().lower())
        for m in db.load_mails(r):
            emails.add(m.strip().lower())
        for m in db.load_wrongmails(r):
            emails.add(m.strip().lower())
    return companies, emails


def blacklisted(company, email, blacklist):
    c = (company or "").strip().lower()
    e = (email or "").strip().lower()
    domain = e.split("@")[-1] if "@" in e else ""
    for bad in blacklist:
        if bad and (bad in c or (domain and bad in domain)):
            return True
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="Push a findprospects CSV into prospects.db.")
    ap.add_argument("csv_path", help="path to the findprospects CSV")
    ap.add_argument("--db", dest="db_path", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would happen; write nothing")
    ap.add_argument("--subject", default=DEFAULT_SUBJECT)
    args = ap.parse_args(argv)

    path = Path(args.csv_path)
    if not path.exists():
        print(f"No such file: {path}")
        return 2

    # utf-8-sig: spreadsheet exports often prepend a BOM.
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        print("Empty CSV.")
        return 2
    missing = REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing:
        print(f"CSV is missing required columns: {sorted(missing)}")
        print(f"Found: {reader.fieldnames}")
        return 2

    db.init_db(args.db_path)
    blacklist = load_blacklist()
    seen_companies, seen_emails = existing_keys(args.db_path)

    inserted = 0
    skipped = []           # (label, reason)
    batch_emails = set()   # dedupe within this CSV too

    for i, row in enumerate(reader, start=2):   # row 2 = first data row
        company = (row.get("company") or "").strip()
        email = (row.get("Work Email") or "").strip().lower()
        first_name = (row.get("first_name") or "").strip()
        label = f"{first_name or '?'} @ {company or '?'}"

        if not company:
            skipped.append((f"row {i}", "no company"))
            continue
        if not email:
            skipped.append((label, "blank Work Email (prospecting run left it empty)"))
            continue
        if "@" not in email:
            skipped.append((label, f"malformed email: {email!r}"))
            continue
        if email in seen_emails or email in batch_emails:
            skipped.append((label, f"duplicate email already in pipeline: {email}"))
            continue
        if blacklisted(company, email, blacklist):
            skipped.append((label, "blacklisted company/domain"))
            continue

        why = (row.get("why_company") or "").strip()
        f2 = (row.get("f2_content") or "").strip()
        if not why:
            skipped.append((label, "empty why_company (quality gate)"))
            continue

        placeholders = {
            "name": first_name or "there",
            "company": company,
            "why_company": why,
            "f2_content": f2,
        }

        if args.dry_run:
            print(f"[dry-run] would insert  {label:<40} -> {email}")
        else:
            db.insert_lead(
                company=company,
                designation=(row.get("designation") or "").strip() or None,
                mails=[email],
                # Subject may carry a {company} token — the only per-lead value
                # in it. Anything else in the string is left untouched.
                subject=args.subject.replace("{company}", company),
                placeholders=placeholders,
                db_path=args.db_path,
            )
        inserted += 1
        batch_emails.add(email)

    print(f"\n{'[dry-run] ' if args.dry_run else ''}"
          f"Inserted {inserted} lead(s), skipped {len(skipped)}.")
    if skipped:
        print("Skipped:")
        for label, reason in skipped:
            print(f"  - {label}: {reason}")
    if not args.dry_run and inserted:
        print("\nThese are status='new' and will send on the next scheduled cold run.")
        print("Review:  python brace.py leads list --status new")
    return 0


if __name__ == "__main__":
    sys.exit(main())
