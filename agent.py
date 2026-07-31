#!/usr/bin/env python3
"""
agent.py - the one entry point.

Every operation in this repo is a subcommand here. Run it bare to see the map:

    python agent.py

Why a dispatcher instead of a directory of scripts: the pipeline is about
twenty modules, and a newcomer facing twenty files has to read all of them to
learn which three they actually need. The modules still exist and still do the
work - this file only decides which one runs, so there is exactly one thing to
learn and one place to look things up.

Commands are grouped by what they are for, not by which file implements them.
"""

import os
import sys
import runpy
import argparse
import datetime
from pathlib import Path

# Import-time guarantee: everything below assumes the repo root is importable,
# which is not true when the CLI is invoked by absolute path from elsewhere
# (the scheduler does exactly that).
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import paths                                        # noqa: E402


# --------------------------------------------------------------------------
# command table
# --------------------------------------------------------------------------
# name -> (group, one-line help, handler)
# Handlers take the remaining argv and return an exit code.

GROUPS = [
    ("Getting started", ["demo", "setup", "doctor", "tenant"]),
    ("Find prospects",  ["find", "import", "email-for", "scrape"]),
    ("Send",            ["send", "followup", "sweep", "test-send"]),
    ("Run it",          ["engine", "dashboard", "pause", "resume"]),
    ("Inspect",         ["status", "leads"]),
]

HELP = {
    "demo":      "Seed sample leads and render them, no credentials needed",
    "setup":     "Connect a Gmail account (one-time OAuth)",
    "doctor":    "Check prerequisites and configuration, fix nothing",
    "tenant":    "Show which company this pipeline is selling for",
    "find":      "Research real accounts and write a CSV (needs `claude`)",
    "import":    "Push a research CSV into the database",
    "email-for": "Resolve one contact's address the way the agent must",
    "scrape":    "Fetch pages as clean markdown (needs `defuddle`)",
    "send":      "Cold-email pass over new leads",
    "followup":  "Follow-up pass over leads already contacted",
    "sweep":     "Scan Gmail for bounces and replies",
    "test-send": "Send exactly one email, recording nothing",
    "engine":    "Start the scheduler; runs sends on a human schedule",
    "dashboard": "Serve the daily status page on localhost:8377",
    "pause":     "Stop all sending, leave the scheduler up",
    "resume":    "Undo pause",
    "status":    "One-screen summary of the pipeline",
    "leads":     "Inspect and edit individual leads",
}


def _delegate(module, argv, prog):
    """Run a module's main() with argv, as if it had been invoked directly.

    Rewriting sys.argv rather than threading an argv parameter through every
    module keeps each one runnable on its own and keeps their --help text
    honest, since argparse reads prog from sys.argv[0].
    """
    saved = sys.argv
    sys.argv = [prog] + list(argv)
    try:
        mod = __import__(module, fromlist=["main"])
        rc = mod.main()
        return 0 if rc is None else rc
    finally:
        sys.argv = saved


# --- handlers -------------------------------------------------------------

def cmd_setup(argv):
    return _delegate("tools.setup_gmail", argv, "agent.py setup")


def cmd_find(argv):
    return _delegate("prospecting.research", argv, "agent.py find")


def cmd_import(argv):
    return _delegate("prospecting.import_csv", argv, "agent.py import")


def cmd_email_for(argv):
    return _delegate("prospecting.email_source", argv, "agent.py email-for")


def cmd_scrape(argv):
    return _delegate("prospecting.scrape", argv, "agent.py scrape")


def cmd_send(argv):
    return _delegate("outreach.send_cold", argv, "agent.py send")


def cmd_followup(argv):
    return _delegate("outreach.followup", argv, "agent.py followup")


def cmd_sweep(argv):
    return _delegate("outreach.bounce_sweep", argv, "agent.py sweep")


def cmd_test_send(argv):
    return _delegate("tools.send_test", argv, "agent.py test-send")


def cmd_engine(argv):
    return _delegate("outreach.scheduler", argv, "agent.py engine")


def cmd_dashboard(argv):
    return _delegate("tools.dashboard", argv, "agent.py dashboard")


def cmd_leads(argv):
    return _delegate("tools.manage", argv, "agent.py leads")


def cmd_pause(argv):
    paths.PAUSED_FILE.touch()
    print(f"Paused. Sends will no-op until you run `python agent.py resume`.")
    print(f"  (this is just a file: {paths.PAUSED_FILE})")
    return 0


def cmd_resume(argv):
    if paths.PAUSED_FILE.exists():
        paths.PAUSED_FILE.unlink()
        print("Resumed. Sending is live again.")
    else:
        print("Not paused - nothing to do.")
    return 0


def cmd_demo(argv):
    """The zero-credential path, as one command.

    This is the first thing anyone should run. It proves the pipeline works
    end to end without asking them to create a Google Cloud project first.
    """
    ap = argparse.ArgumentParser(prog="agent.py demo",
                                 description="Seed sample leads and render them. Sends nothing.")
    ap.add_argument("--db", dest="db_path", default=None)
    args = ap.parse_args(argv)

    # The delegated modules log to stderr, which is unbuffered, while these
    # prints go to block-buffered stdout when piped. Without the flushes the
    # whole demo comes out with the log output stacked above its own headings.
    def say(*lines):
        for line in lines:
            print(line)
        sys.stdout.flush()

    say("=" * 70,
        "STEP 1 of 2  Loading sample leads into the database",
        "=" * 70)
    rc = _delegate("prospecting.import_csv",
                   [str(paths.SAMPLE_CSV)] + (["--db", args.db_path] if args.db_path else []),
                   "agent.py import")
    if rc:
        return rc

    say("",
        "=" * 70,
        "STEP 2 of 2  Rendering what would be sent - Gmail is never called",
        "=" * 70)
    rc = _delegate("outreach.send_cold",
                   ["--dry-run", "--force"] + (["--db", args.db_path] if args.db_path else []),
                   "agent.py send")
    if rc:
        return rc

    say("",
        "Nothing was sent and no credentials were used.",
        "Both contacts at the same company went out in one burst - that is",
        "deliberate, and it is why the engine groups by company.",
        "",
        "Next:  python agent.py status     what is in the pipeline now",
        "       python agent.py setup      connect Gmail, to send for real")
    return 0


def cmd_tenant(argv):
    """Which company is this pipeline selling for, and where its files live.

    The research skills call this rather than hardcoding a path, because the
    tenant is configurable and `context/brace/` is only the default.
    """
    from core import tenant as t

    ap = argparse.ArgumentParser(
        prog="agent.py tenant",
        description="Show the active tenant: the company this pipeline sells for.")
    ap.add_argument("--paths", action="store_true",
                    help="print only the file paths, one per line, for scripting")
    args = ap.parse_args(argv)

    active = t.name()
    files = [t.company_md(), t.voice_md(), t.blacklist_path(),
             t.directory() / "copy.py"]

    if args.paths:
        for f in files:
            print(f)
        return 0

    print(f"Selling for:  {active}")
    print(f"Defined in:   {t.directory()}")
    print()
    for f, what in zip(files, ("the ICP, buying signals, who to contact",
                               "how the hook must sound",
                               "never-contact companies and domains",
                               "the fixed strings in every email")):
        mark = "ok  " if f.exists() else "MISSING"
        print(f"  {mark} {f.name:<14} {what}")

    others = [n for n in t.available() if n != active]
    if others:
        print(f"\nAlso available: {', '.join(others)}")
    print("\nThis pipeline is not Brace. Brace is an example tenant it has been")
    print("pointed at. To sell for someone else, copy the folder above, edit the")
    print('four files, and set "tenant" in config.json.')
    return 0


def cmd_doctor(argv):
    """Report what is present and what is missing. Changes nothing."""
    import shutil
    from core import config

    ok = True
    print("Python")
    print(f"  {sys.version.split()[0]} at {sys.executable}")
    if sys.version_info < (3, 9):
        print("  ! needs 3.9 or newer")
        ok = False

    print("\nOptional tools")
    for tool, unlocks in (("claude", "`agent.py find` - research"),
                          ("defuddle", "`agent.py scrape` - page fetching")):
        found = shutil.which(tool)
        print(f"  {'ok  ' if found else 'MISSING'} {tool:<10} {unlocks}")

    print("\nSelling for")
    try:
        from core import tenant as t
        active = t.name()
        t.copy()          # raises if the folder is missing or incomplete
        print(f"  ok   {active}  ({t.directory()})")
    except RuntimeError as e:
        print(f"  !    {e}")
        ok = False

    print("\nConfiguration")
    if paths.CONFIG_PATH.exists():
        print(f"  ok   {paths.CONFIG_PATH}")
        try:
            sender = config.get("sender_email")
            print(f"  {'ok  ' if sender else 'MISSING'} sender_email: {sender or '(unset)'}")
            if not sender:
                ok = False
            for key in ("gmail_credentials_path", "gmail_oauth_keys_path"):
                val = config.get(key)
                exists = val and Path(val).expanduser().exists()
                print(f"  {'ok  ' if exists else 'MISSING'} {key}: {val or '(unset)'}")
                if not exists:
                    ok = False
            print(f"  ok   email_source: {config.get('email_source') or 'pseudo'}")
        except RuntimeError as e:
            print(f"  ! {e}")
            ok = False
    else:
        print(f"  none  {paths.CONFIG_PATH}")
        print("        Sending is not configured. Everything else still works:")
        print("        run `python agent.py demo`, or `python agent.py setup`.")

    if paths.CONFIG_PATH.exists() and ok:
        print("\nGmail")
        try:
            from outreach import gmail
            token = gmail.get_access_token()
            print(f"  ok   Google accepted the refresh token")
        except Exception as e:
            print(f"  !    {type(e).__name__}: {e}")
            print("       See docs/gmail-setup.md - most often an expired test-mode token.")
            ok = False

    print("\nPaused" if paths.PAUSED_FILE.exists() else "\nNot paused")
    if paths.PAUSED_FILE.exists():
        print("  A PAUSED file exists, so sends will silently no-op.")
        print("  Run `python agent.py resume` to clear it.")

    return 0 if ok else 1


def cmd_status(argv):
    """One screen: what is queued, what went out, what needs a human."""
    from outreach import db

    ap = argparse.ArgumentParser(prog="agent.py status")
    ap.add_argument("--db", dest="db_path", default=None)
    args = ap.parse_args(argv)

    if not (Path(args.db_path) if args.db_path else paths.DB_PATH).exists():
        print("No database yet. Run `python agent.py demo` to create one.")
        return 0

    db.init_db(args.db_path)
    conn = db.get_conn(args.db_path)
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM leads GROUP BY status"
        ).fetchall()
        counts = {r["status"]: r["n"] for r in rows}
        today = datetime.date.today().isoformat()
        sent = conn.execute(
            "SELECT kind, COUNT(*) AS n FROM sends "
            "WHERE send_date=? AND state='sent' GROUP BY kind", (today,)
        ).fetchall()
        dead = conn.execute(
            "SELECT COUNT(*) AS n FROM sends WHERE state='dead'"
        ).fetchone()["n"]
    finally:
        conn.close()

    total = sum(counts.values())
    print(f"Pipeline ({total} lead{'s' if total != 1 else ''})")
    if not total:
        print("  empty - run `python agent.py demo` or `python agent.py find`")
    for status in ("new", "cold", "F1", "F2", "replied", "sibling_replied", "failed"):
        if counts.get(status):
            print(f"  {counts[status]:>4}  {status}")

    print(f"\nSent today ({today})")
    if sent:
        for r in sent:
            print(f"  {r['n']:>4}  {r['kind']}")
    else:
        print("     0  nothing yet")

    if dead:
        print(f"\n{dead} send(s) gave up after retries - `python agent.py leads list --status failed`")
    if paths.PAUSED_FILE.exists():
        print("\nPAUSED - sending is off. `python agent.py resume` to clear.")
    return 0


HANDLERS = {
    "demo": cmd_demo,
    "setup": cmd_setup,
    "doctor": cmd_doctor,
    "tenant": cmd_tenant,
    "find": cmd_find,
    "import": cmd_import,
    "email-for": cmd_email_for,
    "scrape": cmd_scrape,
    "send": cmd_send,
    "followup": cmd_followup,
    "sweep": cmd_sweep,
    "test-send": cmd_test_send,
    "engine": cmd_engine,
    "dashboard": cmd_dashboard,
    "pause": cmd_pause,
    "resume": cmd_resume,
    "status": cmd_status,
    "leads": cmd_leads,
}


def usage():
    print("Outreach agent - find prospects, write the email, send the sequence.")
    try:
        from core import tenant as t
        print(f"Currently selling for: {t.name()}   (python agent.py tenant)")
    except Exception:
        pass
    print("\n  python agent.py <command> [options]")
    print("  python agent.py <command> --help     options for one command")
    for title, names in GROUPS:
        print(f"\n{title}")
        for name in names:
            print(f"  {name:<12} {HELP[name]}")
    print("\nNew here? Run `python agent.py demo` - it needs no setup and sends nothing.")
    print("Then read ONBOARD.md, or just ask the agent to walk you through it.")


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        usage()
        return 0

    command, rest = argv[0], argv[1:]
    handler = HANDLERS.get(command)
    if not handler:
        print(f"Unknown command: {command}\n", file=sys.stderr)
        usage()
        return 2

    try:
        return handler(rest)
    except RuntimeError as e:
        # config.require() raises this when the mailbox is not set up. It is by
        # far the most likely first mistake (running `send` before `setup`), and
        # the message already says exactly what is missing - a traceback on top
        # of it just buries the useful part.
        print(f"\n{e}\n", file=sys.stderr)
        if not paths.CONFIG_PATH.exists():
            print("Run `python agent.py setup` to connect a mailbox, or "
                  "`python agent.py demo`\nto explore the pipeline without one.",
                  file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
