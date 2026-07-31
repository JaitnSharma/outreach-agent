"""
Brace — the example tenant.

Brace is a fictional company selling corporate cards and automated expense
management to funded startups. It is not the pipeline; it is the company this
pipeline has been pointed at.

To sell for someone else, copy this whole folder to `context/<yourname>/`, edit
these strings plus `company.md`, `voice.md` and `blacklist.txt`, and set
`"tenant": "<yourname>"` in config.json. No code changes.

Every value here is a plain string. `outreach/templates.py` owns the structure
of the email - the greeting, the block order, the HTML, and the rule that the
hook lands before any self-introduction. This file only says what the company
is and how it signs off. Keep it that way: putting markup or a second paragraph
in one of these strings is how a harness stops being a harness.

Three of these may contain {company}, substituted per lead: COLD_SUBJECT,
F1_OPENER and F2_CLOSING. Nothing else takes a placeholder.
"""

# --- who is sending -------------------------------------------------------
SENDER_NAME = "Arjun Mehta"
SENDER_TITLE = "Growth, Brace"
SITE_URL = "https://usebrace.com"
SITE_LABEL = "usebrace.com"

# --- what is being sold ---------------------------------------------------
# Identical on every cold email, by design: the personalisation budget is spent
# entirely on the hook, never on restating what we sell.
PRODUCT_LINE = (
    "Brace gives your team corporate cards where the expenses categorise "
    "themselves. No receipt chasing, no month-end spreadsheet."
)

# --- the cold email -------------------------------------------------------
COLD_SUBJECT = "Quick question about expenses at {company}"

COLD_CTA = (
    "Teams around your size usually get a few days a month back for whoever "
    "owns finance. If that sounds useful, I can send over a short walkthrough. "
    "No call needed unless you want one."
)

COLD_OPT_OUT = (
    "And if this is not a priority right now, just say so and I will leave you be."
)

# --- follow-ups -----------------------------------------------------------
# F1 is deliberately tiny. A follow-up that re-pitches reads as a broadcast; one
# that just re-surfaces the thread reads like a person. Two paragraphs, joined
# by templates.py - no markup lives in this file.
F1_OPENER = "Following up on my note about how {company} handles expenses."

F1_CLOSER = (
    "If it is not something you are looking at right now, no problem at all. "
    "If it is, reply here and I will send the walkthrough over."
)

F2_CLOSING = (
    "If the timing is wrong, I will close the loop here and wish you and the "
    "{company} team well. If it is worth a look, reply and I will send the "
    "walkthrough."
)
