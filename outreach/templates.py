"""
templates.py — fixed outreach email HTML. No LLM at send time.

THE HARNESS RULE: the structure of every email lives here, in code. The research
agent never writes an email — it fills four bounded slots that this file drops
into a fixed skeleton. So a bad research run can produce a weak sentence; it can
never produce a malformed email, a broken link, a missing CTA, or a message that
forgets who it is from.

Three layers, and keeping them apart is the point:

    this file            STRUCTURE. Block order, HTML, which slots exist, and
                         the rule that the hook lands first. Never varies.
    context/<tenant>/    COPY. What the company sells, who signs, the CTA.
      copy.py            Plain strings, no markup. Swappable per company.
    the database         PER-LEAD. Four slots the research agent filled.

Only these tokens vary per lead:
  cold:  {first_name} {company} {hook}
  f1:    {first_name} {company}
  f2:    {first_name} {company} {f2_content}

Note the ordering choice in the cold template: the hook comes FIRST, immediately
after the greeting, before we say anything about ourselves. A cold email that
opens with "I'm X from Y" is deleted before the reader reaches the relevant part.
Leading with the thing we found about THEM is the whole point of the pipeline.

The tenant is loaded lazily, per render, rather than at import. Reading config
at import time makes every module that merely imports this one fail on an
unconfigured checkout, which is exactly the thing the rest of the repo works
hard to avoid.
"""

from core import tenant

# Paragraph separator. Defined once so no tenant string ever contains markup.
_P = "<br><br>"


def _signature(c, short=False):
    """Sign-off. Follow-ups use the short form: by then they know who we are."""
    if short:
        return f"Best,<br>{c.SENDER_NAME}"
    return (f"Best,<br><b>{c.SENDER_NAME}</b><br>{c.SENDER_TITLE}<br>"
            f'<a href="{c.SITE_URL}">{c.SITE_LABEL}</a>')


def cold_subject(company):
    """Subject for a cold email. Called at insert time, not at send time."""
    return tenant.copy().COLD_SUBJECT.replace("{company}", company)


def render_cold(placeholders):
    # `why_company` is the DB key; it carries the signal-grounded hook. The key
    # name is inherited from the schema and kept so the persistence layer stays
    # untouched — see the module docstring on bounded slots.
    c = tenant.copy()
    first = placeholders["name"]
    company = placeholders["company"]
    hook = placeholders["why_company"]

    body = _P.join([
        f"Hi {first},",
        hook,                       # the hook lands before any self-introduction
        c.PRODUCT_LINE,
        c.COLD_CTA,
        c.COLD_OPT_OUT,
        _signature(c),
    ])
    return f"<div>{body}</div>"


def render_f1(placeholders):
    c = tenant.copy()
    first = placeholders["name"]
    company = placeholders["company"]

    body = _P.join([
        f"Hi {first},",
        c.F1_OPENER.replace("{company}", company),
        c.F1_CLOSER,
        _signature(c, short=True),
    ])
    return f"<div>{body}</div>"


def render_f2(placeholders):
    # {f2_content} is the middle paragraph, written per-lead and stored in the
    # DB. It is the one place a follow-up carries new, specific reasoning.
    c = tenant.copy()
    first = placeholders["name"]
    company = placeholders["company"]

    body = _P.join([
        f"Hi {first},",
        "Last note from me on this one.",
        placeholders["f2_content"],
        c.F2_CLOSING.replace("{company}", company),
        _signature(c, short=True),
    ])
    return f"<div>{body}</div>"
