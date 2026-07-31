"""
send_cold.py — cold-outreach provider for engine.py.

All pacing, windowing, capping, idempotency and logging live in engine.py.
This file owns exactly one thing: WHICH leads go out and what they say.

Selection: status='new', grouped by company in first-seen order. The engine
takes whole companies until a burst reaches 15, including the company that
crosses it, so a company is never split within a burst.

Invoked by scheduler.py roughly once a minute between 08:30 and 11:00 Mon-Fri.
Daily cap 50 (engine.MODES). Most invocations are cheap no-ops — see
engine._tick for the decision order.

Flags:
  --dry-run   select + render, never call Gmail or write state
  --db PATH   operate on an alternate DB (testing)
  --force     ignore window/gap gating (testing only)
"""

from outreach import db
from outreach import templates
from outreach.engine import SendJob, run


class ColdProvider:
    mode = "cold"

    def build_queue(self, ctx):
        groups = db.get_new_leads_grouped(ctx.db_path)
        if groups:
            total = sum(len(rows) for _c, rows in groups)
            ctx.log.info("Queue: %d new lead(s) across %d company(ies).",
                         total, len(groups))
        return groups

    def prepare(self, ctx, row):
        to_list = db.load_mails(row)
        if not to_list:
            ctx.log.warning("id=%s %s has no addresses — skipping.",
                            row["id"], row["company"])
            return None
        ph = db.load_placeholders(row)
        return SendJob(
            lead_id=row["id"],
            kind="cold",
            company=row["company"],
            to_list=to_list,
            subject=row["subject"],
            html=templates.render_cold(ph),
            thread_id=None,             # cold starts a new thread
        )

    def on_sent(self, ctx, row, job, thread_id):
        db.mark_sent(row["id"], thread_id, "cold", db_path=ctx.db_path)


def main():
    return run(ColdProvider())


if __name__ == "__main__":
    main()
