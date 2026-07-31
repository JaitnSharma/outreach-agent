"""
followup.py — F1 / F2 provider for engine.py.

All pacing, windowing, capping, idempotency and logging live in engine.py.
This file owns the selection logic that genuinely differs from cold:

  * STRICT F1 PRIORITY. While ANY F1 is due, no F2 is queued at all. F2s only
    load once the F1 backlog is fully drained. This is stronger than mere
    ordering: a company with one F1-due and one F2-due contact sends only the
    F1 now and defers that colleague's F2 to a later day, so the whole-company
    rule yields to the priority rule.
  * Reply detection is COMPANY-LEVEL. Each contact at a company is its own lead
    row with its own thread; the moment ANY of them replies, the whole company
    is in conversation and every colleague's sequence is killed.
  * Follow-ups render into the SAME thread with a 'Re:' subject.
  * Addresses come straight from leads.db — bounce_sweep owns pruning dead ones
    and runs before this window opens. This pipeline does NOT re-check bounces.

WHY THE REPLY CACHE IS SAFE NOW: `_company_dead` is per-INSTANCE, and the
engine builds one instance per process, and a process is one burst. So the
cache lives ~10 minutes, not the whole 5-hour window. Under the old
run-to-completion model this same cache was computed once and then trusted for
hours, which meant a colleague could be nudged long after someone at their
company had already replied.

Invoked by scheduler.py roughly once a minute between 11:30 and 16:30 Mon-Fri.
Daily cap 100 (engine.MODES). Hard stop at 17:00.

Flags: --dry-run, --db PATH, --force
"""

from outreach import db
from outreach import gmail
from outreach import templates
from outreach.engine import SendJob, run

MIN_HOURS = 48          # minimum age of the previous send before a follow-up


def _group_by_company(rows):
    """[(company, [rows])] preserving first-seen order, so the engine's
    whole-company burst rule works on follow-ups too."""
    groups, index = [], {}
    for r in rows:
        c = r["company"]
        if c not in index:
            index[c] = len(groups)
            groups.append([c, []])
        groups[index[c]][1].append(r)
    return [(c, rs) for c, rs in groups]


class FollowupProvider:
    mode = "followup"

    def __init__(self):
        # Fresh per process == fresh per burst. See module docstring.
        self._company_dead = {}

    def build_queue(self, ctx):
        f1_due = db.get_due_followups("cold", MIN_HOURS, ctx.db_path)
        f2_due = db.get_due_followups("F1", MIN_HOURS, ctx.db_path)

        # Strict priority, not just ordering: F2s are not returned AT ALL while
        # an F1 is outstanding. Concatenating the two lists (the old behaviour)
        # leaked F2s early, because _group_by_company merges a company's rows
        # and a company pulled forward by its F1 dragged its F2 colleagues into
        # the same burst.
        if f1_due:
            ctx.log.info("Queue: %d F1-due (strict priority; %d F2-due held).",
                         len(f1_due), len(f2_due))
            return _group_by_company(list(f1_due))

        if f2_due:
            ctx.log.info("Queue: F1 backlog clear, %d F2-due.", len(f2_due))
            return _group_by_company(list(f2_due))

        return []

    def _company_replied(self, ctx, company):
        """True if anyone at `company` has replied. Cheap DB check first, then a
        live Gmail sweep of every live thread the company has. On a hit, cascade
        so no colleague is ever nudged mid-conversation."""
        if db.company_has_reply(company, ctx.db_path):
            return True
        if ctx.token is None:               # dry-run: trust DB state only
            return False

        for r in db.get_company_threads(company, ctx.db_path):
            if gmail.human_reply_count(ctx.token, r["thread_id"]) > 0:
                if not ctx.dry_run:
                    db.mark_status(r["id"], "replied", ctx.db_path)
                    n = db.mark_company_replied(company, exclude_id=r["id"],
                                                db_path=ctx.db_path)
                    ctx.log.info("REPLIED company=%s (via id=%s) — cascaded to "
                                 "%d colleague(s).", company, r["id"], n)
                else:
                    ctx.log.info("[dry-run] REPLIED company=%s (via id=%s).",
                                 company, r["id"])
                return True
        return False

    def prepare(self, ctx, row):
        company = row["company"]

        if company not in self._company_dead:
            try:
                self._company_dead[company] = self._company_replied(ctx, company)
            except Exception as e:
                ctx.log.error("Reply-check FAILED company=%s: %s — skipping "
                              "this lead, will retry next burst.", company, e)
                return None

        if self._company_dead[company]:
            # 'sibling_replied', not 'replied': this person never personally
            # replied, a colleague did. Keeps the dashboard honest.
            if not ctx.dry_run:
                db.mark_status(row["id"], "sibling_replied", ctx.db_path)
            ctx.log.info("SKIP id=%s %s — company already in conversation.",
                         row["id"], company)
            return None

        to_list = db.load_mails(row)
        if not to_list:
            ctx.log.warning("id=%s %s has no addresses — skipping "
                            "(bounce_sweep owns the failed transition).",
                            row["id"], company)
            return None

        kind = "F1" if row["status"] == "cold" else "F2"
        subject = row["subject"]
        if not subject.startswith("Re:"):
            subject = "Re: " + subject
        ph = db.load_placeholders(row)
        html = templates.render_f1(ph) if kind == "F1" else templates.render_f2(ph)

        return SendJob(
            lead_id=row["id"],
            kind=kind,
            company=company,
            to_list=to_list,
            subject=subject,
            html=html,
            thread_id=row["thread_id"],     # stay in the original thread
        )

    def on_sent(self, ctx, row, job, thread_id):
        db.mark_sent(row["id"], thread_id, job.kind, db_path=ctx.db_path)


def main():
    return run(FollowupProvider())


if __name__ == "__main__":
    main()
