"""
scheduler.py (v2) — single lightweight always-on ticker.

Difference from v1: v1 fired each send script at a few FIXED times and each run
blasted its whole batch. v2 ticks the senders roughly once a minute for the
whole window and lets engine.py decide what to do on each tick — usually
nothing. All burst/gap state lives in the DB (run_days), not in this process
and not in a sleeping sender, so a restart here loses nothing.

Windows (local IST wall-clock, Mon-Fri):
    cold      08:30 - 11:00   -> send_cold.py   (cap 50/day)
    followup  11:30 - 16:30   -> followup.py    (cap 100/day)
    hard stop 17:00 enforced inside engine.py, per mail.

Other jobs:
    bounce_sweep  daily at/after 11:00, CATCH-UP (runs as soon as the PC is on
                  if 11:00 was missed) — it must land before the follow-up
                  window so dead addresses are pruned first.
    run_findprospects  weekly, normally Friday from 04:00, with catch-up. See
                  _prospects_due: the v1 rule (04:00 Friday, 45-min grace) meant
                  the job never fired once, because the PC is rarely on at 4am,
                  which is what starved the lead pipeline.

Stop: end this pythonw process (Task Manager / Task Scheduler -> End).
Pause sends without stopping the scheduler: create a PAUSED file next to the
scripts (the senders honor it; bounce_sweep is read-only anyway).
"""

import sys
import json
import time
import datetime
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "scheduler_state.json"
LOG_DIR = HERE / "logs"
PYTHON = sys.executable

POLL_SECONDS = 60
BOUNCE_WAIT_SECONDS = 600      # cap on how long followup waits for the sweep

COLD_WINDOW = (datetime.time(8, 30), datetime.time(11, 0))
FOLLOWUP_WINDOW = (datetime.time(11, 30), datetime.time(16, 30))
BOUNCE_AT = datetime.time(11, 0)

PROSPECT_WEEKDAY = 4                       # Friday
PROSPECT_AT = datetime.time(4, 0)
PROSPECT_STALE_DAYS = 8                    # safety net if a Friday is missed


def log(msg):
    LOG_DIR.mkdir(exist_ok=True)
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} scheduler {msg}\n"
    with open(LOG_DIR / "scheduler.log", "a", encoding="utf-8") as f:
        f.write(line)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def in_window(now, window):
    start, end = window
    return start <= now.time() < end


def run_script(script, wait=False):
    """Launch a job. Sender ticks are launched silently — most are sub-second
    no-ops and logging each one would bury the real events."""
    path = HERE / script
    try:
        proc = subprocess.Popen([PYTHON, str(path)], cwd=str(HERE))
    except Exception as e:
        log(f"ERROR launching {script}: {e}")
        return None
    if wait:
        try:
            proc.wait(timeout=BOUNCE_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            log(f"ERROR {script} still running after {BOUNCE_WAIT_SECONDS}s")
    return proc


def _prospects_due(now, state):
    """Weekly, preferring Friday, but self-healing.

    Fires when either:
      * it has not run this ISO week and we are at/past Fri 04:00, or
      * it has not run in PROSPECT_STALE_DAYS (covers a Friday the PC was off,
        so the lead pipeline still gets fed early the following week).
    """
    last = state.get("prospects_last_date")
    week = "%d-W%02d" % now.isocalendar()[:2]

    if last:
        try:
            last_dt = datetime.datetime.strptime(last, "%Y-%m-%d")
            if (now - last_dt).days >= PROSPECT_STALE_DAYS:
                return True, week
        except ValueError:
            pass

    if state.get("prospects_week") == week:
        return False, week
    if now.weekday() > PROSPECT_WEEKDAY:
        return True, week
    if now.weekday() == PROSPECT_WEEKDAY and now.time() >= PROSPECT_AT:
        return True, week
    return False, week


def check(now, state):
    today = now.strftime("%Y-%m-%d")
    changed = False

    # --- findprospects: any day, so a missed Friday still gets caught up ----------
    due, week = _prospects_due(now, state)
    if due:
        log("firing run_findprospects.py (weekly lead refill)")
        run_script("run_findprospects.py")
        state["prospects_week"] = week
        state["prospects_last_date"] = today
        changed = True

    # Everything below is Mon-Fri only.
    if now.weekday() > 4:
        if changed:
            save_state(state)
        return

    # --- bounce sweep: daily, catch-up, must precede the follow-up window ----
    bounce_proc = None
    if state.get("bounce_date") != today and now.time() >= BOUNCE_AT:
        log("firing bounce_sweep.py")
        bounce_proc = run_script("bounce_sweep.py")
        state["bounce_date"] = today
        changed = True

    # --- sender ticks -------------------------------------------------------
    for mode, script, window in (
        ("cold", "send_cold.py", COLD_WINDOW),
        ("followup", "followup.py", FOLLOWUP_WINDOW),
    ):
        # Tick from the window OPEN onward, not only inside it.
        #
        # Bug this fixes (seen live 2026-07-29): the PC slept from 10:33 to
        # 12:01, spanning the 11:00 cold close. On wake, `now` was outside the
        # window, so send_cold.py was never invoked again — which meant the
        # engine never reached its `now >= end_dt -> _finish()` branch. The day
        # was never finalized, no SUMMARY was written, and a completely missed
        # cold run left no trace beyond a run_days row nobody reads. A
        # dead-man switch that only fires when the process runs is not a
        # dead-man switch.
        #
        # Post-close ticks are ~free: once run_days.completed=1 the engine
        # returns after a single indexed read.
        if now.time() < window[0]:
            continue

        # Log the window opening once a day; the per-minute ticks stay silent.
        key = f"{mode}_window_logged"
        if state.get(key) != today:
            log(f"{mode} window open ({window[0]:%H:%M}-{window[1]:%H:%M}) — "
                f"ticking {script} every {POLL_SECONDS}s")
            state[key] = today
            changed = True

        # A sweep launched THIS tick must finish before follow-ups read
        # addresses it has not pruned yet.
        if mode == "followup" and bounce_proc is not None \
                and bounce_proc.poll() is None:
            log("waiting for bounce_sweep before follow-up tick")
            try:
                bounce_proc.wait(timeout=BOUNCE_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                log("ERROR bounce_sweep still running — proceeding anyway")

        run_script(script)

    if changed:
        save_state(state)


def main():
    log("scheduler v2 started")
    state = load_state()
    while True:
        try:
            check(datetime.datetime.now(), state)
        except Exception as e:
            log(f"loop error: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
