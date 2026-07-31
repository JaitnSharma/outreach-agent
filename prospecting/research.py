"""
research.py — run the prospecting skill headless via the Claude Code CLI.

This is the only place a model is invoked. It shells out to `claude` in
print/headless mode with the repo root as the working directory, so the skill
and context files resolve. The model writes a CSV, pushes the rows to
prospects.db, and updates worked_accounts.csv. It does NOT send any email.

Two profiles, and the difference between them matters:

    full   skills/findprospects/SKILL.md — the production skill. Discovery,
           one subagent per account, deep per-account research. Minutes and a
           lot of tokens per account, which is correct for a real batch.

    quick  skills/quicklead/SKILL.md — a single account, inline, with a hard
           search budget. For demos and smoke tests. Same output columns, so
           it is a faithful sample of the real thing, just not a substitute
           for it.

Picking the profile is NOT left to the model. Onboarding used to invoke the
full skill and ask nicely for a small batch, and got a 15-account production
run: 50+ searches and a seven-minute wait to show someone three example rows.
A demo asks for `quick` and gets `quick`.

Requires: `claude` on PATH and an authenticated Claude Code login.
Runs unattended, so it bypasses permission prompts.
"""

import os
import sys
import shutil
import argparse
import datetime
import subprocess

from core import paths

DEFAULT_ACCOUNTS = 15
FULL_TIMEOUT = 3 * 60 * 60       # 3h hard cap so a hung batch cannot linger
QUICK_TIMEOUT = 6 * 60           # a demo that takes longer than this has failed

PROFILES = ("full", "quick")


def _tenant_line():
    """Name the active tenant in the prompt.

    The skill is written to be tenant-agnostic - it says "the tenant's
    company.md", not "Brace". Telling the model which one is active up front
    saves it a discovery step and makes the run reproducible.
    """
    from core import tenant
    return (f"You are prospecting for the tenant '{tenant.name()}'. Its files "
            f"are in {tenant.directory()} - read company.md and voice.md there "
            f"before anything else. ")


def _full_prompt(count):
    return (
        _tenant_line() +
        f"Read skills/findprospects/SKILL.md and run it end to end for {count} "
        "accounts, without stopping to ask. Read data/worked_accounts.csv and "
        "the tenant's blacklist.txt first, qualify the accounts, spawn one subagent per "
        "account, then write the single CSV to data/runs/<today>.csv with the "
        "Work Email column filled by `python agent.py email-for`, push it with "
        "`python agent.py import data/runs/<today>.csv`, and append every newly "
        "queued account to data/worked_accounts.csv. Do NOT send any emails and "
        "do NOT touch Gmail. Finish by printing the standard report-back summary."
    )


def _quick_prompt(count):
    return (
        _tenant_line() +
        f"Read skills/quicklead/SKILL.md and run it end to end for {count} "
        "contact(s), without stopping to ask. Obey the search budget in that "
        "file exactly — it is a hard cap, not a guideline. Do NOT spawn "
        "subagents. Do NOT read skills/findprospects/SKILL.md. Write the CSV to "
        "the path that skill names and print the report block it specifies. Do "
        "NOT import to the database, do NOT send email, do NOT touch Gmail."
    )


def log(msg):
    paths.ensure_dirs()
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} research {msg}\n"
    with open(paths.LOGS_DIR / "research.log", "a", encoding="utf-8") as f:
        f.write(line)


def run(profile="full", count=None, echo=False):
    """Invoke the skill. Returns the CLI's exit code."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {PROFILES}")

    if count is None:
        count = 1 if profile == "quick" else DEFAULT_ACCOUNTS
    prompt = _quick_prompt(count) if profile == "quick" else _full_prompt(count)
    timeout = QUICK_TIMEOUT if profile == "quick" else FULL_TIMEOUT

    claude = shutil.which("claude")
    if not claude:
        msg = ("`claude` is not on PATH. The research half needs the Claude Code "
               "CLI — see https://claude.com/claude-code. Everything else in this "
               "repo works without it.")
        log(f"ERROR: {msg}")
        print(msg, file=sys.stderr)
        return 1

    # On Windows `claude` is a .cmd shim; launch it through the command
    # processor so CreateProcess can resolve it regardless of extension.
    comspec = os.environ.get("COMSPEC", "cmd.exe")
    cmd = [comspec, "/c", "claude", "-p", prompt, "--dangerously-skip-permissions"]

    log(f"firing {profile} profile for {count} account(s) (cwd={paths.ROOT})")
    if echo:
        print(f"Running the {profile} research profile for {count} account(s). "
              f"Timeout {timeout // 60} min.", file=sys.stderr)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(paths.ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log(f"ERROR: {profile} run exceeded {timeout}s and was killed.")
        print(f"Research run exceeded {timeout // 60} minutes and was killed.",
              file=sys.stderr)
        return 1
    except Exception as e:
        log(f"ERROR launching claude: {e}")
        print(f"Could not launch claude: {e}", file=sys.stderr)
        return 1

    out = (proc.stdout or "").strip()
    if echo and out:
        print(out)

    # Persist the model's final output for later inspection.
    log(f"exit={proc.returncode}; last output lines:")
    for line in out.splitlines()[-40:]:
        log(f"  | {line}")
    if proc.stderr:
        log(f"stderr: {proc.stderr.strip()[:2000]}")
    return proc.returncode


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Run the prospecting skill headless via the Claude Code CLI.")
    ap.add_argument("--count", type=int, default=None,
                    help=f"how many accounts to research "
                         f"(default: {DEFAULT_ACCOUNTS} full, 1 quick)")
    ap.add_argument("--profile", choices=PROFILES, default="full",
                    help="'full' for a real batch, 'quick' for a bounded demo")
    ap.add_argument("--quiet", action="store_true",
                    help="log only; do not echo the model's output")
    args = ap.parse_args(argv)

    if args.count is not None and args.count < 1:
        ap.error("--count must be at least 1")

    return run(profile=args.profile, count=args.count, echo=not args.quiet)


if __name__ == "__main__":
    sys.exit(main())
