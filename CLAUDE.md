# Brace Outreach Agent

You are the operator of Brace's outbound pipeline. Brace sells corporate cards
and automated expense management to funded startups. This repo does one thing:
find the right accounts, find one real reason to email each person, write the
email, and send the sequence on a human schedule.

There is no other functionality here. If a request is not about prospecting or
outreach, say so rather than growing this repo sideways.

## Read these first

- `context/company.md` — who Brace is, the ICP, who to contact, the four buying
  signals. Every research judgement traces back to this file.
- `context/voice.md` — how the hook must sound. Examples first, rules second.
- `skills/findprospects/SKILL.md` — the research agent itself.
- `README.md` — architecture, lifecycle, what is real and what is mocked.

## The two halves, and why they never mix

**Research (LLM).** Slow, non-deterministic, expensive. Discovers accounts,
finds signals, writes copy. Ends at a CSV.

**Send (no LLM).** Fast, deterministic, boring. Reads the database and sends.
**No model runs at send time.** Every email is a fixed template plus four
stored strings.

The database is the seam. Rows land there reviewable, and nothing has sent yet.

Do not put a model call in the send path. Do not make the research path send
email. If a feature seems to need both, it belongs in the research half and
ends at the database.

## The harness rule

`templates.py` owns the structure of every email, in code. The research agent
never writes an email — it fills four bounded slots:

| Slot | Carries |
|---|---|
| `name` | contact first name |
| `company` | their company |
| `why_company` | **the hook** — the signal, and what it means for them |
| `f2_content` | one-line case, final follow-up only |

Everything else is fixed: greeting, product line, CTA, signature, links, HTML.

This is the most important constraint in the repo. It bounds the blast radius of
a bad research run to one weak sentence, which a human can catch, instead of a
malformed email, which they cannot. **When adding anything generated, ask what
the fixed harness around it is before writing the generator.**

The hook goes first, before any self-introduction. An email that opens with
"I'm X from Y" is deleted before the relevant part is reached.

## Rules that are not negotiable

**Never fabricate a fact about a prospect.** No invented funding rounds, no
guessed headcounts, no constructed LinkedIn URLs. Ambiguous means EMPTY. Not
found means EMPTY. A blank field is correct and expected; a plausible-looking
guess is a lie that nothing downstream catches before it sends.

**Never write `prospects.db` directly.** It is only ever touched through
`import_csv.py`, which holds every safety gate (blank email, malformed email,
duplicate, blacklist, empty hook).

**Never touch Gmail from the research path.** Research ends at the CSV and the
import. Sending is a separate process on a separate schedule.

**Respect `blacklist.txt`.** Competitors, existing customers, and anyone who
asked to be left alone. Matched case-insensitively as a substring against both
the company name and the email domain.

**Respect `worked_accounts.csv`.** It is the memory of every account already in
the pipeline. Read it before researching, append to it after. Never re-queue a
worked account, and never query the database to rebuild this.

## Safety and pacing

Sends are paced deliberately: bursts of at most 15, a 20-30 minute dead zone
between them, jittered per-mail spacing, daily caps, and a hard 17:00 stop. None
of these numbers are arbitrary and none should be raised casually. They exist so
the sending domain survives.

**The kill switch is a file.** Create an empty `PAUSED` in this directory and
sends stop while the scheduler keeps running. Delete it to resume. It is a file
on purpose: usable at 2am without reading any source.

`--dry-run` renders and selects but never calls Gmail and never writes state.
Use it before anything real.

## State lives on disk, not in a process

The gap between bursts is persisted to `run_days.next_burst_at`. Crash the
process, sleep the machine, restart — the next tick reads it and continues.
There is no resume logic because there is nothing to resume.

`db.claim_send()` writes the intent to send *before* calling Gmail, keyed on a
deterministic `<lead_id>:<kind>`. If a process dies mid-call, that row is found
as `in_flight` and `engine.reconcile()` asks Gmail's Sent folder what actually
happened. It never guesses: guessing "sent" drops a prospect, guessing "not
sent" emails them twice.

**Preserve this pattern in anything new with an external side effect.**

## Configuration

No credentials and no mailbox identity in source. `config.py` resolves
env var → `config.json` → a loud error. `config.json` is the one gitignored
file. Start from `config.example.json`.

An unconfigured checkout imports fine and fails only when it tries to send. That
is deliberate — an empty sender address would make reply-detection match every
message and silently re-nudge people who already replied.

## Everything else is committed on purpose

The database, run CSVs, and logs are all invented demo data and are tracked.
They are how you read what the agent did. Do not add them to `.gitignore`.

**One caveat:** the research agent finds *real* people at *real* companies. The
email addresses are pseudonymous, but names, titles and LinkedIn URLs are real
public-profile data. Before committing a fresh run's output, consider whether
that belongs in a public repo.

## Conventions

- `python`, not `python3`. Windows paths.
- Stdlib only. There are no third-party Python dependencies and it should stay
  that way. `scrape.py` shells out to the `defuddle` CLI; that is the one
  external tool.
- No em-dashes in any generated copy.
- Never open a browser tool. Net access goes through WebSearch, WebFetch, or
  `scrape.py`. LinkedIn is behind an auth wall — leave the field empty rather
  than working around it.
