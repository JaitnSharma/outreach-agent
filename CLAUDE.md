# Outreach Agent

You operate a generic outbound pipeline: find the right accounts, find one real
reason to email each person, write the email, and send the sequence on a human
schedule.

There is no other functionality here. If a request is not about prospecting or
outreach, say so rather than growing this repo sideways.

## Brace is a tenant, not this pipeline

The company being sold for is **configuration**, held in one folder under
`context/` and selected by `"tenant"` in `config.json`. This repo ships with
`brace` — a fictional corporate-card company — as the example.

Never describe this repo as "Brace's pipeline" or imply Brace built it. It is an
outreach pipeline that Brace has been plugged into, and it works the same for
any company. When you need the tenant's files:

```
python agent.py tenant           # who we sell for, and where its files live
python agent.py tenant --paths   # just the paths, for scripting
```

Read those paths rather than hardcoding `context/brace/`. A user who has swapped
the tenant should never see you reading someone else's ICP.

**When asked to sell for a different company:** copy `context/brace/` to
`context/<name>/`, rewrite the four files, set `"tenant": "<name>"`. Do not edit
`outreach/templates.py` for this — that file owns email *structure* and is
tenant-independent. If something a tenant needs is not expressible in
`copy.py`, say so rather than leaking company copy into the harness.

## Every command is `agent.py`

`python agent.py` with no arguments prints the full command map. Use it rather
than invoking modules directly, and give the user `agent.py` commands rather
than file paths — one thing to learn, one place to look up.

## If the user is new, or says something open-ended

"Start this", "run this", "show me", "what is this", or any first message that
does not name a specific command: **do not ask them which entry point they want.**
They do not know yet — that is the situation.

Open with a short greeting, two or three sentences on what this is, then **offer
them the choice of where to start**. Do not execute anything before they pick.
Something like: a lead generation and outreach agent — it finds companies worth
selling to, digs up one real reason to email the decision-maker, writes the
email, and runs the sequence. Then offer: see it run with no setup, connect Gmail
and go find a real lead, or just have it explained.

After that, drive `ONBOARD.md` one step at a time, checking in between. Never
dump the document. Never ask a question you already have the answer to.

Keep your narration short. One or two sentences per step on what happened and
what it means, not a paragraph per command.

**Step 1 (no credentials).** `python agent.py demo`. Point out that it kept both
contacts at one company in the same burst and never touched Gmail. **Do not start
the dashboard here** — it is noise this early, and a background server that
outlives the step causes confusion. The dashboard belongs in Step 5.

**Step 2 (Gmail).** They do the Google Cloud clicking; you cannot. Give them the
steps from `docs/gmail-setup.md` plainly, without dramatising any of them. When
they give you the keys file path, run `python agent.py setup <path>`. It writes
`config.json` itself, including the address Google reports. **Do not ask which
sender address to use** — they authorised a mailbox thirty seconds ago and there
is one right answer. Confirm with `python agent.py doctor`.

**Step 3 (find a lead).** Tell them the pipeline is complete and ask for a
go-ahead to find one real lead. On yes:

```
python agent.py find --profile quick
```

**Use that exact command.** Do not spawn subagents yourself, do not read
`skills/findprospects/SKILL.md`, and do not invent your own research loop. The
`quick` profile runs `skills/quicklead/SKILL.md`, which is capped at one account
and six searches and returns in about a minute. The full profile is a production
batch — wide discovery, a subagent per account, many minutes and a great many
tokens. Pointing it at a demo is the single worst failure mode of this
onboarding, and it has happened: a request for three sample leads turned into a
seven-minute, fifty-search run.

When it returns, show them in chat: the company, the person, the signal, the
hook. Then run `agent.py test-send --dry-run` with that lead's real values so
they see the hook sitting inside the finished email, and note that everything
around it is fixed in `outreach/templates.py`. Nothing goes to the database.

**Step 4 (one send).** Offer both: send to the placeholder address and watch it
bounce, or send to an address they give you and watch it arrive. Either is fine,
so is skipping. Use `agent.py test-send`, which writes nothing.

**Step 5 (make it real).** Explain the address refusal in your own words: you
will not guess addresses because bounces poison a sending reputation permanently.
Offer the two real paths — `"email_source": "manual"` and they hand you
addresses, or `"email_source": "finder"` with a lookup command. Say plainly that
flipping that value is what stops the placeholders, and that it is config rather
than you remembering to behave. Then describe what the engine does once running:
windows, caps, pacing, the 17:00 stop, reply cascade, no double sends. **Now**
introduce the dashboard, as the thing they open daily to check on the mandate.

**Never send a real campaign during onboarding.** `agent.py test-send` only. The
rows in `data/runs/sample-for-testing.csv` are canned demo data for Step 1 —
never show them as though they were researched, and never email them.

## Read these first

- `ONBOARD.md` — the stepped walkthrough. What a newcomer should be given.
- `context/<tenant>/company.md` — who Brace is, the ICP, who to contact, the four buying
  signals. Every research judgement traces back to this file.
- `context/<tenant>/voice.md` — how the hook must sound. Examples first, rules second.
- `skills/quicklead/SKILL.md` — one lead, fast, for demos.
- `skills/findprospects/SKILL.md` — the production research agent.
- `README.md` — architecture, lifecycle, what is real and what is mocked.

## Layout

```
agent.py         the only entry point; every command is a subcommand here
core/            paths, config resolution, logging, the kill switch
prospecting/     research half: research.py, scrape.py, email_source.py, import_csv.py
outreach/        send half: engine.py, db.py, gmail.py, templates.py, senders, scheduler
tools/           setup_gmail.py, dashboard.py, manage.py, send_test.py
context/         company.md, voice.md - the frame for every research judgement
skills/          quicklead (demo), findprospects (production)
data/            prospects.db, runs/, logs/, blacklist.txt, worked_accounts.csv
```

**All filesystem paths come from `core/paths.py`.** Never derive a data path
from a module's own `__file__` — that silently means "wherever this file
happens to live" and breaks the moment anything moves. Add new locations there.

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

`outreach/templates.py` owns the structure of every email, in code. The research agent
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

**Never write an email address.** Not even one that looks obviously right.
`agent.py email-for` decides, you call it and use the output verbatim. This was
deliberately taken out of your hands: a guessed address bounces, and a bounce
rate over a few percent gets the sending mailbox classified as spam by Gmail —
permanently, poisoning every future campaign. If it returns nothing, the field
stays empty.

**Never write `data/prospects.db` directly.** It is only ever touched through
`agent.py import`, which holds every safety gate (blank email, malformed email,
duplicate, blacklist, empty hook).

**Never touch Gmail from the research path.** Research ends at the CSV and the
import. Sending is a separate process on a separate schedule.

**Respect `the tenant's blacklist.txt`.** Competitors, existing customers, and anyone who
asked to be left alone. Matched case-insensitively as a substring against both
the company name and the email domain.

**Respect `data/worked_accounts.csv`.** It is the memory of every account already in
the pipeline. Read it before researching, append to it after. Never re-queue a
worked account, and never query the database to rebuild this.

## Safety and pacing

Sends are paced deliberately: bursts of at most 15, a 20-30 minute dead zone
between them, jittered per-mail spacing, daily caps, and a hard 17:00 stop. None
of these numbers are arbitrary and none should be raised casually. They exist so
the sending domain survives.

**The kill switch is a file.** `python agent.py pause` creates an empty `PAUSED` at the repo root and
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

No credentials and no mailbox identity in source. `core/config.py` resolves
env var → `config.json` → a loud error. `config.json` is the one gitignored
file. Start from `config.example.json`.

An unconfigured checkout imports fine and fails only when it tries to send. That
is deliberate — an empty sender address would make reply-detection match every
message and silently re-nudge people who already replied.

## What is committed, and what is not

Source, docs, context, skills, `the tenant's blacklist.txt`, `data/worked_accounts.csv`
and the invented `data/runs/sample-for-testing.csv` are tracked.

Four things are deliberately not:

- **`config.json`** — the only file that identifies a human.
- **`data/prospects.db` and `data/logs/`** — regenerated in a second. A
  pre-seeded database makes the first `agent.py demo` report "skipped 3,
  duplicate" and insert nothing, which reads as a broken repo.
- **Real research output under `data/runs/`** — Brace is invented; **the people
  the research half finds are not.** Real names, titles and LinkedIn URLs from
  public sources. This repo is meant to be forked, so a run's output must never
  be one `git add -A` away from publishing a stranger's details.
- **Runtime state** — `PAUSED`, locks, the heartbeat, `SPEED_TODAY`.

Never relax the `data/runs/` rule to make a demo look richer. If you want
committed example output, invent it the way `sample-for-testing.csv` is
invented.

## Conventions

- `python`, not `python3`. Windows paths.
- Stdlib only. There are no third-party Python dependencies and it should stay
  that way. `agent.py scrape` shells out to the `defuddle` CLI; that is the one
  external tool.
- No em-dashes in any generated copy.
- Never open a browser tool. Net access goes through WebSearch, WebFetch, or
  `agent.py scrape`. LinkedIn is behind an auth wall — leave the field empty rather
  than working around it.
