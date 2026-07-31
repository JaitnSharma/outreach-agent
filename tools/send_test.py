"""
send_test.py — send ONE email, to an address you name, writing nothing.

Used during onboarding to show what a real send looks like before anyone commits
to a campaign. It touches no database, claims no idempotency key, and counts
against no daily cap, because nothing here is part of a sequence.

Two things you might want to see:

    # watch it bounce, using a placeholder address
    python agent.py test-send --to priya@acmeops.pseudoemail.com \
        --name Priya --company "Acme Ops" --hook "You were hired into ..."

    # watch it arrive, using your own inbox
    python agent.py test-send --to you@gmail.com \
        --name Priya --company "Acme Ops" --hook "You were hired into ..."

Either way the message lands in your Gmail Sent folder, correctly formatted and
identical to what the real engine would send. The only difference is that the
engine records what it did and this does not.

--dry-run renders and prints without sending.
"""

import re
import sys
import argparse

from outreach import gmail
from outreach import templates
from prospecting.email_source import is_pseudo


def to_text(html):
    """Rough HTML to text, for the preview only. Never used for sending."""
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</?(div|p|ol|ul)[^>]*>", "\n", text)
    text = re.sub(r"<li[^>]*>", "  - ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&#39;", "'").replace("&amp;", "&").replace("&nbsp;", " ")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def main():
    ap = argparse.ArgumentParser(description="Send one email. No database writes.")
    ap.add_argument("--to", required=True, help="recipient address")
    ap.add_argument("--name", required=True, help="their first name")
    ap.add_argument("--company", required=True, help="their company")
    ap.add_argument("--hook", required=True,
                    help="the opening line, i.e. the why_company value")
    ap.add_argument("--kind", choices=("cold", "f1", "f2"), default="cold")
    ap.add_argument("--f2-content", default="", help="only used with --kind f2")
    ap.add_argument("--dry-run", action="store_true",
                    help="render and print, send nothing")
    args = ap.parse_args()

    placeholders = {
        "name": args.name,
        "company": args.company,
        "why_company": args.hook,
        "f2_content": args.f2_content,
    }
    render = {"cold": templates.render_cold,
              "f1": templates.render_f1,
              "f2": templates.render_f2}[args.kind]
    html = render(placeholders)
    subject = templates.cold_subject(args.company)
    if args.kind != "cold":
        subject = "Re: " + subject

    print(f"\nTo:      {args.to}")
    print(f"Subject: {subject}")
    print("-" * 62)
    print(to_text(html))
    print("-" * 62)

    if is_pseudo(args.to):
        print("\nThis is a placeholder address. It will bounce, on purpose.")
        print("You should see the send in Sent, then a mailer-daemon reply in Inbox.")

    if args.dry_run:
        print("\n[dry-run] Nothing sent.")
        return 0

    token = gmail.get_access_token()
    result = gmail.send_message(token, [args.to], subject, html)
    print(f"\nSent. Thread {result['threadId']}")
    print("Check your Gmail Sent folder. Nothing was written to the database.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
