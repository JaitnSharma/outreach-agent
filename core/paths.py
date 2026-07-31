"""
paths.py — every filesystem location in one place.

Before this file existed each script resolved its own paths from
`Path(__file__).parent`, which silently meant "wherever this script happens to
live". That works only while every script sits in one flat directory: the
moment anything moves into a subfolder, half the code starts looking for
`prospects.db` in the wrong place and creates an empty one instead of failing.

So paths anchor on the REPO ROOT, computed once, here. Nothing else in the
codebase is allowed to derive a data path from its own `__file__`.

Layout:

    <root>/                 code, docs, config.json, PAUSED
    <root>/data/            everything the agent reads and writes
    <root>/data/runs/       research output, one CSV per run
    <root>/data/logs/       one log file per component
"""

from pathlib import Path

# core/paths.py -> core/ -> <root>
ROOT = Path(__file__).resolve().parent.parent

# --- data ----------------------------------------------------------------
DATA_DIR = ROOT / "data"
RUNS_DIR = DATA_DIR / "runs"
LOGS_DIR = DATA_DIR / "logs"
SCRAPES_DIR = RUNS_DIR / "scrapes"

DB_PATH = DATA_DIR / "prospects.db"
WORKED_ACCOUNTS_PATH = DATA_DIR / "worked_accounts.csv"
# The blacklist is per-tenant (a company's competitors are its own), so it
# lives in the tenant folder: see core.tenant.blacklist_path().
SAMPLE_CSV = RUNS_DIR / "sample-for-testing.csv"

# --- runtime state -------------------------------------------------------
# PAUSED sits at the ROOT, not under data/, on purpose. It is the kill switch,
# and it has to be findable by someone who is not reading source at the time.
PAUSED_FILE = ROOT / "PAUSED"
SPEED_FILE = DATA_DIR / "SPEED_TODAY"
SCHEDULER_STATE = DATA_DIR / "scheduler_state.json"
LOCK_DIR = DATA_DIR

# The scheduler touches this every tick. The dashboard reads its mtime to decide
# whether an engine is alive, rather than inspecting the process table: a
# command line is not reliable evidence (it may be a relative path, and another
# copy of this repo on the same machine looks identical), and a stale timestamp
# is both simpler and honest about what it actually knows.
SCHEDULER_HEARTBEAT = DATA_DIR / "scheduler.heartbeat"
HEARTBEAT_STALE_SECONDS = 180      # scheduler ticks every 60s; 3 misses = down

# --- config --------------------------------------------------------------
CONFIG_PATH = ROOT / "config.json"
CONFIG_EXAMPLE = ROOT / "config.example.json"

# --- code the agent reads -----------------------------------------------
CONTEXT_DIR = ROOT / "context"
SKILLS_DIR = ROOT / "skills"
CLI = ROOT / "agent.py"


def ensure_dirs():
    """Create the write targets. Called by anything that is about to write.

    Cheap and idempotent, so callers do not have to reason about whether a
    fresh clone has these — git does not track empty directories, so on a new
    checkout `data/logs/` genuinely does not exist yet.
    """
    for d in (DATA_DIR, RUNS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
