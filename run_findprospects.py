"""
run_findprospects.py — scheduler wrapper that runs the findprospects skill
headless via the Claude Code CLI.

scheduler.py fires this like any other job (subprocess, no args). Unlike the
send/followup scripts, this one has no LLM of its own — it shells out to the
`claude` CLI in print/headless mode, pointed at this agent directory so the
skill and context files resolve. It writes the prospect CSV, pushes the rows to
prospects.db, and updates worked_accounts.csv. It does NOT send any email.

Requires: `claude` on PATH and an authenticated Claude Code login on this machine.
Runs unattended, so it bypasses permission prompts (--dangerously-skip-permissions).

Tune ACCOUNT_TARGET to change how many accounts per run.
"""

import os
import sys
import shutil
import datetime
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE                        # self-contained: skill + context live here
LOG_DIR = HERE / "logs"
ACCOUNT_TARGET = 15
TIMEOUT_SECONDS = 3 * 60 * 60            # 3h hard cap so a hung run can't linger

PROMPT = (
    f"Read skills/findprospects/SKILL.md in this directory and run it end to end "
    f"for {ACCOUNT_TARGET} accounts, without stopping to ask. Read "
    "worked_accounts.csv and blacklist.txt first, qualify the accounts, spawn one "
    "subagent per account, then write the single CSV to runs/<today>.csv with the "
    "Work Email column filled by the pseudo-email rule, push it to prospects.db via "
    "import_csv.py, and append every newly queued account to worked_accounts.csv. "
    "Do NOT send any emails and do NOT touch Gmail. Finish by printing the standard "
    "report-back summary."
)


def log(msg):
    LOG_DIR.mkdir(exist_ok=True)
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} run_findprospects {msg}\n"
    with open(LOG_DIR / "findprospects.log", "a", encoding="utf-8") as f:
        f.write(line)


def main():
    claude = shutil.which("claude")
    if not claude:
        log("ERROR: `claude` not found on PATH — cannot run. Aborting.")
        return 1

    # On Windows `claude` is a .cmd shim; launch it through the command
    # processor so CreateProcess can resolve it regardless of extension.
    comspec = os.environ.get("COMSPEC", "cmd.exe")
    cmd = [comspec, "/c", "claude", "-p", PROMPT, "--dangerously-skip-permissions"]

    log(f"firing findprospects for {ACCOUNT_TARGET} accounts (cwd={AGENT_ROOT})")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(AGENT_ROOT),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        log(f"ERROR: run exceeded {TIMEOUT_SECONDS}s and was killed.")
        return 1
    except Exception as e:
        log(f"ERROR launching claude: {e}")
        return 1

    # Persist the model's final output for later inspection.
    tail = (proc.stdout or "").strip().splitlines()[-40:]
    log(f"exit={proc.returncode}; last output lines:")
    for line in tail:
        log(f"  | {line}")
    if proc.stderr:
        log(f"stderr: {proc.stderr.strip()[:2000]}")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
