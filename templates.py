"""
templates.py — fixed outreach email HTML. No LLM at send time.

THE HARNESS RULE: the structure of every email lives here, in code. The research
agent never writes an email — it fills four bounded slots that this file drops
into a fixed skeleton. So a bad research run can produce a weak sentence; it can
never produce a malformed email, a broken link, a missing CTA, or a message that
forgets who it is from.

Only these tokens vary per lead:
  cold:  {first_name} {company} {hook}
  f1:    {first_name} {company}
  f2:    {first_name} {company} {f2_content}

Note the ordering choice in the cold template: the hook comes FIRST, immediately
after the greeting, before we say anything about ourselves. A cold email that
opens with "I'm X from Y" is deleted before the reader reaches the relevant part.
Leading with the thing we found about THEM is the whole point of the pipeline.
"""

# --- Sender identity (single source of truth) -----------------------------
SENDER_NAME = "Arjun Mehta"
SENDER_TITLE = "Growth, Brace"
BRACE_SITE = "https://usebrace.com"
WALKTHROUGH_LINK = "https://usebrace.com/walkthrough"

# --- Static product line. Identical on every cold email, by design: the
# personalisation budget is spent entirely on the hook, never on restating
# what we sell. -------------------------------------------------------------
PRODUCT_LINE = (
    "Brace gives your team corporate cards where the expenses categorise "
    "themselves. No receipt chasing, no month-end spreadsheet."
)

# --- Subject lines --------------------------------------------------------
# {company} is substituted by import_csv.py at insert time, not here.
COLD_SUBJECT = "Quick question about expenses at {company}"


# --- Cold template --------------------------------------------------------
# Hook first, product second, one ask, short signature. Everything except
# {hook} is fixed so tone and structure cannot drift between leads.
_COLD_BODY = (
    '<div>Hi {first_name},<br><br>'
    '{hook}<br><br>'
    + PRODUCT_LINE + '<br><br>'
    'Teams around your size usually get a few days a month back for whoever owns '
    'finance. If that sounds useful, I can send over a short walkthrough. No call '
    'needed unless you want one.<br><br>'
    'And if this is not a priority right now, just say so and I will leave you be.<br><br>'
    'Best,<br><b>' + SENDER_NAME + '</b><br>' + SENDER_TITLE + '<br>'
    '<a href="' + BRACE_SITE + '">usebrace.com</a></div>'
)


# --- F1 (first follow-up) -------------------------------------------------
# Deliberately tiny. A follow-up that re-pitches reads as a broadcast; one that
# just re-surfaces the thread reads like a person.
_F1_BODY = (
    '<div>Hi {first_name},<br><br>'
    'Following up on my note about how {company} handles expenses.<br><br>'
    'If it is not something you are looking at right now, no problem at all. If it '
    'is, reply here and I will send the walkthrough over.<br><br>'
    'Best,<br>' + SENDER_NAME + '</div>'
)


# --- F2 (final follow-up) -------------------------------------------------
# {f2_content} is the middle paragraph, written per-lead and stored in the DB.
# It is the one place a follow-up carries new, specific reasoning.
_F2_BODY = (
    '<div>Hi {first_name},<br><br>'
    'Last note from me on this one.<br><br>'
    '{f2_content}<br><br>'
    'If the timing is wrong, I will close the loop here and wish you and the {company} '
    'team well. If it is worth a look, reply and I will send the walkthrough.<br><br>'
    'Best,<br>' + SENDER_NAME + '</div>'
)


def render_cold(placeholders):
    # `why_company` is the DB key; it carries the signal-grounded hook. The key
    # name is inherited from the schema and kept so the persistence layer stays
    # untouched — see the module docstring on bounded slots.
    return _COLD_BODY.format(
        first_name=placeholders["name"],
        company=placeholders["company"],
        hook=placeholders["why_company"],
    )


def render_f1(placeholders):
    return _F1_BODY.format(
        first_name=placeholders["name"],
        company=placeholders["company"],
    )


def render_f2(placeholders):
    return _F2_BODY.format(
        first_name=placeholders["name"],
        company=placeholders["company"],
        f2_content=placeholders["f2_content"],
    )
