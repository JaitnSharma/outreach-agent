"""
runlog.py — shared logging + kill-switch helpers.

Task Scheduler / pythonw discard stdout, so every script logs to a file under
logs/. A PAUSED sentinel file next to the scripts stops all real sends
without stopping the scheduler process.
"""

import os
import time
import logging
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG_DIR = HERE / "logs"
PAUSED_FILE = HERE / "PAUSED"
LOCK_STALE_SECONDS = 1800   # a lock older than this is considered abandoned


def get_logger(name, db_path=None):
    LOG_DIR.mkdir(exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")

    fh = logging.FileHandler(LOG_DIR / f"{name}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Also echo to console for manual/interactive runs.
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    if db_path:
        logger.info("Using DB override: %s", db_path)
    return logger


def paused():
    """True when the PAUSED sentinel exists — send scripts should no-op."""
    return PAUSED_FILE.exists()


class single_instance:
    """Context manager guarding against two copies of a send script running at
    once (which would race on status='new' and double-send). Usage:

        with single_instance("send_cold") as ok:
            if not ok:
                return
            ... do work ...

    A lock older than LOCK_STALE_SECONDS is treated as abandoned and stolen,
    so a crash that leaves the file behind can't wedge the pipeline forever.
    """

    def __init__(self, name):
        self.path = HERE / f".{name}.lock"
        self.acquired = False

    def __enter__(self):
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            self.acquired = True
            return True
        except FileExistsError:
            # Steal if stale.
            try:
                age = time.time() - self.path.stat().st_mtime
            except OSError:
                age = 0
            if age > LOCK_STALE_SECONDS:
                try:
                    self.path.unlink()
                    fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, str(os.getpid()).encode())
                    os.close(fd)
                    self.acquired = True
                    return True
                except OSError:
                    return False
            return False

    def __exit__(self, *exc):
        if self.acquired:
            try:
                self.path.unlink()
            except OSError:
                pass
        return False
