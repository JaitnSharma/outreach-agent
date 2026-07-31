"""
email_source.py — the single place an email address is decided.

THE POINT OF THIS FILE: the research agent must never invent an address. A
hallucinated mailbox bounces, and a bounce rate above a few percent is how a
Gmail sender lands in spam filters permanently. That damage is not recoverable
by fixing the prompt afterwards.

So address resolution is taken away from the model entirely and put here, in
code, behind one config value.

    "email_source": "pseudo"    default. Generates a guaranteed-bounce address.
                                Nothing real is ever contacted.
    "email_source": "manual"    Returns nothing. Rows are written with a blank
                                address and a human supplies real ones.
    "email_source": "finder"    Shells out to whatever finder you configure.

This is what "I will stop filling pseudo-emails" actually means: flip one value
and every downstream row changes, with no prompt edit and no model behaviour to
trust. The skill calls this script per contact and writes whatever it returns.

Usage (the research agent calls it exactly like this):

    python agent.py email-for --first priya --domain acmeops.com

Prints the address on stdout, or nothing at all if the mode says there is no
address to give. Exit 0 either way — an empty result is a valid, expected
answer, not an error. Exit 2 means the configuration is broken.

    python agent.py email-for --mode        prints the active mode and what it does
"""

import re
import sys
import shlex
import argparse
import subprocess

from core import config

VALID_MODES = ("pseudo", "manual", "finder")
DEFAULT_MODE = "pseudo"

PSEUDO_DOMAIN = "pseudoemail.com"
FINDER_TIMEOUT = 60

_EMAIL_RE = re.compile(r"^[\w.+\-]+@[\w\-]+(\.[\w\-]+)+$")

MODE_HELP = {
    "pseudo": (
        "Generating placeholder addresses that are GUARANTEED to bounce.\n"
        "  Real leads, fake mailboxes. Nobody can be contacted by accident.\n"
        "  Switch to 'manual' or 'finder' when you want real delivery."
    ),
    "manual": (
        "Leaving addresses BLANK for a human to fill in.\n"
        "  Rows without an address are skipped at import, by design, so a\n"
        "  half-filled batch can never send to nobody."
    ),
    "finder": (
        "Calling your configured email finder.\n"
        "  A lookup that returns nothing leaves the address blank rather than\n"
        "  guessing, which is the entire reason this file exists."
    ),
}


def active_mode():
    """The configured mode. An unknown value is a hard error, not a fallback —
    silently defaulting to 'pseudo' when someone typed 'finder' wrong would send
    a whole batch to nowhere and look like it worked."""
    mode = (config.get("email_source") or DEFAULT_MODE).strip().lower()
    if mode not in VALID_MODES:
        raise SystemExit(
            f"Unknown email_source {mode!r} in config.\n"
            f"  Valid values: {', '.join(VALID_MODES)}"
        )
    return mode


def company_slug(domain):
    """acmeops.com -> acmeops   |   getdesk.co.uk -> getdesk

    Used only to keep pseudo-addresses unique per company. Two prospects called
    'john' at different companies must not collapse to one address, because the
    importer dedupes on address and would silently drop the second person.
    """
    d = (domain or "").strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0]
    d = re.sub(r"^www\.", "", d)
    parts = [p for p in d.split(".") if p]
    return re.sub(r"[^a-z0-9]", "", parts[0]) if parts else "unknown"


def pseudo_address(first_name, domain):
    first = re.sub(r"[^a-z0-9]", "", (first_name or "").strip().lower()) or "contact"
    return f"{first}@{company_slug(domain)}.{PSEUDO_DOMAIN}"


def is_pseudo(address):
    """True for an address this module fabricated. Lets the rest of the system
    tell 'placeholder' apart from 'a real address that happens to be wrong'."""
    return (address or "").strip().lower().endswith("." + PSEUDO_DOMAIN)


def find_via_command(first_name, domain):
    """Run the configured finder. Returns an address or None.

    Contract, kept deliberately dumb so anything can satisfy it: we substitute
    {first} and {domain} into your command, run it, and read stdout. One address,
    or empty. Any failure, timeout, or unparseable output means None — never a
    guess, because a wrong address costs more than a missing one.
    """
    template = config.get("email_finder_command")
    if not template:
        raise SystemExit(
            "email_source is 'finder' but 'email_finder_command' is not set.\n"
            "  Add it to config.json, e.g.\n"
            '    "email_finder_command": "myfinder --name {first} --domain {domain}"\n'
            "  It must print one email address on stdout, or nothing."
        )
    cmd = template.replace("{first}", first_name or "").replace("{domain}", domain or "")
    try:
        proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True,
                              timeout=FINDER_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    out = (proc.stdout or "").strip().splitlines()
    candidate = out[0].strip().lower() if out else ""
    # Validate before returning. A finder that prints an error message to stdout
    # must not become someone's email address.
    return candidate if _EMAIL_RE.match(candidate) else None


def resolve(first_name, domain):
    """(address, mode). address is '' when there is deliberately none."""
    mode = active_mode()
    if mode == "pseudo":
        return pseudo_address(first_name, domain), mode
    if mode == "manual":
        return "", mode
    return (find_via_command(first_name, domain) or ""), mode


def main():
    ap = argparse.ArgumentParser(
        description="Resolve one contact's email address according to config.")
    ap.add_argument("--first", default="", help="contact first name")
    ap.add_argument("--domain", default="", help="company domain, e.g. acmeops.com")
    ap.add_argument("--mode", action="store_true",
                    help="print the active mode and exit")
    args = ap.parse_args()

    if args.mode:
        mode = active_mode()
        print(f"email_source = {mode}")
        print("  " + MODE_HELP[mode].replace("\n", "\n  ").strip())
        return 0

    if not args.first and not args.domain:
        ap.error("give --first and --domain, or --mode")

    address, _mode = resolve(args.first, args.domain)
    if address:
        print(address)
    return 0


if __name__ == "__main__":
    sys.exit(main())
