# Brace Outreach Agent

A lead generation and email outreach agent.

Give it a target count. It finds companies matching an ideal customer profile,
works out who the decision-maker is, digs up one real reason to email that
specific person, writes the email, and runs the follow-up sequence on a schedule
that looks like a human wrote it. It stops the moment anyone replies, and
reconciles its own bounces.

Demonstrated for **Brace**, a fictional company selling corporate cards to funded
startups. Brace is made up. The companies it researches are not.

```bash
python brace.py demo
```

No credentials, no config, nothing sent. That is the whole first step.

> ### → New here? Read **[ONBOARD.md](ONBOARD.md)**.
>
> Five steps, each one command: see it run with no setup, connect Gmail, find a
> real lead, watch one email send, then turn the engine on. Or open this repo in
> Claude Code and say "walk me through it".

**The leads are real. The email addresses are fake on purpose** — every one
bounces, so you cannot accidentally email a stranger while trying this out. One
config value is where a real email finder drops in.

Nothing sends without the rows sitting reviewable in a database first.

---

## Commands

Everything is a subcommand of `brace.py`. Run it bare to see this list.

| | |
|---|---|
| `demo` | Seed sample leads and render them. No credentials needed. |
| `setup` | Connect a Gmail account (one-time OAuth). |
| `doctor` | Check prerequisites and configuration. Fixes nothing. |
| `find` | Research real accounts and write a CSV. |
| `import` | Push a research CSV into the database. |
| `email-for` | Resolve one contact's address the way the agent must. |
| `scrape` | Fetch pages as clean markdown. |
| `send` | Cold-email pass over new leads. |
| `followup` | Follow-up pass over leads already contacted. |
| `sweep` | Scan Gmail for bounces and replies. |
| `test-send` | Send exactly one email, recording nothing. |
| `engine` | Start the scheduler. |
| `dashboard` | Serve the status page on localhost:8377. |
| `pause` / `resume` | Stop and restart sending. |
| `status` / `leads` | Inspect the pipeline. |

---

## Two systems, deliberately separate

```
  ┌──────────────────────── RESEARCH (LLM) ────────────────────────┐
  │  brace.py find                                                  │
  │    orchestrator: qualify accounts (single-threaded, no dupes)   │
  │         │                                                       │
  │         ├── subagent per account ── scrape → signal → hook      │
  │         ├── subagent per account ── scrape → signal → hook      │
  │         └── subagent per account ── scrape → signal → hook      │
  │                     │                                           │
  │              data/runs/<date>.csv                               │
  └─────────────────────┬───────────────────────────────────────────┘
                        │  brace.py import  (gates: email, dupe, blacklist, hook)
                        v
              data/prospects.db   ← the handoff. Reviewable. Nothing has sent.
                        │
  ┌─────────────────────┴──────── SEND (no LLM) ────────────────────┐
  │  brace.py engine  (always-on, ticks every 60s)                  │
  │      │                                                          │
  │      ├── send      08:30-11:00   cap 50/day                     │
  │      ├── sweep     11:00         bounces + replies              │
  │      └── followup  11:30-16:30   cap 100/day, F1 then F2        │
  │                    │                                            │
  │              engine.py  (pacing, bursts, idempotency, reconcile)│
  │                    │                                            │
  │        templates.py (fixed HTML) │ gmail.py (REST, stdlib only) │
  └────────────────────────────────────────────────────────────────┘
                        │
                  brace.py dashboard → http://127.0.0.1:8377
```

**Why split?** The research half is slow, non-deterministic and expensive. The
send half must be none of those. No LLM runs at send time — every email is a
fixed template plus four stored strings. A bad research run produces a weak
sentence; it can never produce a malformed email or an unintended send.

---

## The harness rule

`outreach/templates.py` owns the structure of every email in code. The research
agent never writes an email. It fills four bounded slots:

| Slot | What it carries |
|---|---|
| `name` | contact first name |
| `company` | their company |
| `why_company` | **the hook** — the signal we found and what it means for them |
| `f2_content` | one-line case, used only in the final follow-up |

Everything else — greeting, product line, CTA, signature, links, HTML — is fixed.
This is the single most important design decision in the system. It bounds what
can go wrong to "one mediocre sentence", which is reviewable, instead of "the
whole email", which is not.

The hook is placed **first**, before any self-introduction. An email that opens
with "I'm X from Y" is deleted before the relevant part is reached.

---

## Lead lifecycle

```
new ──cold sent──> cold ──F1 sent──> F1 ──F2 sent──> F2   (sequence complete)
  │                  │                │
  │                  └── anyone at the company replies ──> replied / sibling_replied
  │
  └── (any stage) every address bounces ──> failed
```

`sibling_replied` is distinct from `replied` on purpose: this person never
answered, a colleague did. Both stop the sequence; only one means they engaged.
Collapsing them would quietly overstate the reply rate.

---

## What is real and what is mocked

| Piece | Status |
|---|---|
| Account discovery + qualification | **Real.** Live web search and scraping. |
| Signal research | **Real.** Actual funding news, job posts, team pages. |
| Hook writing | **Real.** Written per contact against that account's facts. |
| Contact identification | **Real.** Names, titles, LinkedIn URLs where findable. |
| **Email address** | **Mocked by default.** `<first>@<company-slug>.pseudoemail.com` |
| Sending, threading, follow-ups, bounce/reply detection | **Real.** Live Gmail API. |

The address is the only mock, and it is a config value rather than a prompt
instruction — see `prospecting/email_source.py`:

```bash
python brace.py email-for --mode
```

| `email_source` | Behaviour |
|---|---|
| `pseudo` | Placeholder that always bounces. The default. |
| `manual` | Blank; a human supplies addresses. Blank rows are skipped at import. |
| `finder` | Shells out to your lookup service (Clay, Apollo, Hunter, Prospeo). |

Everything downstream is already production-shaped: pseudo addresses bounce on
send, and `brace.py sweep` moves them to `wrongMails` and marks the lead
`failed` — exactly what a real bad address gets.

**The research agent is never allowed to write an address itself.** A guessed
address bounces, and a bounce rate over a few percent gets the sending mailbox
classified as spam by Gmail, permanently. That is not a prompt rule; the model
has to shell out to `brace.py email-for` and use whatever it prints.

---

## Prerequisites

| What | Needed for | Install |
|---|---|---|
| **Python 3.9+** | everything | Already have it. There are no pip dependencies — this is stdlib only. |
| `claude` CLI | the research agent | [Claude Code](https://claude.com/claude-code), signed in |
| `defuddle` | page scraping during research | `npm install -g defuddle-cli` |
| Gmail OAuth | sending email | [docs/gmail-setup.md](docs/gmail-setup.md), one command |

Only Python is needed to explore the pipeline. The rest unlock one feature each.

```bash
python brace.py doctor      # tells you which of these you have
```

---

## Layout

```
brace.py            every command lives here
core/               paths, config, logging, kill switch
  paths.py            every filesystem location, in one place
  config.py           env var -> config.json -> loud error
  runlog.py           file logging, PAUSED sentinel, single-instance locks
prospecting/        research half - ends at a CSV, cannot send
  research.py         invokes the skill headless via the `claude` CLI
  scrape.py           batch page scraper (wraps `defuddle`)
  email_source.py     the ONLY place an address is decided
  import_csv.py       CSV -> DB, with every safety gate
outreach/           send half - reads the DB, no model runs
  engine.py           pacing, bursts, caps, idempotency, reconciliation
  db.py               SQLite: leads + sends (write-ahead log) + run_days
  gmail.py            Gmail REST, stdlib only, no SDK
  templates.py        fixed email HTML - the harness
  send_cold.py        thin provider: which leads, what they say
  followup.py         same, for F1 and F2
  bounce_sweep.py     daily inbox reconciliation
  scheduler.py        the always-on ticker
tools/              human-facing utilities
  setup_gmail.py      one-shot OAuth flow
  dashboard.py        local read-only dashboard + dashboard.html
  manage.py           manual inspection and repair
  send_test.py        one email, outside the pipeline
context/            company.md (ICP, signals), voice.md (how the hook sounds)
skills/             quicklead (one lead, fast), findprospects (production)
data/               prospects.db, runs/, logs/, blacklist.txt, worked_accounts.csv
docs/               gmail-setup.md
```

Every filesystem path comes from `core/paths.py`. Nothing derives a data path
from its own `__file__`.

---

## Configuration

Needed only once you want real email to go out.
**[docs/gmail-setup.md](docs/gmail-setup.md)** walks through getting the
credentials; `brace.py setup` does the OAuth flow and writes `config.json` for
you.

```json
{
  "sender_email": "sdr@yourdomain.com",
  "gmail_credentials_path": "C:/path/to/credentials.json",
  "gmail_oauth_keys_path": "C:/path/to/gcp-oauth.keys.json",
  "email_source": "pseudo"
}
```

Environment variables override the file: `BRACE_SENDER_EMAIL`,
`BRACE_GMAIL_CREDENTIALS`, `BRACE_GMAIL_OAUTH_KEYS`.

`config.json` is gitignored and must never be committed. It holds no secrets —
only the sending address and two paths. The OAuth client secret and refresh
token stay in those referenced files, outside this directory.

Use forward slashes in JSON paths (or double the backslashes). A single
backslash is not valid JSON, and the loader says so explicitly rather than
pretending the key is missing.

An unconfigured checkout imports and runs fine right up until it tries to send,
then fails naming the exact missing key. That is deliberate: a silent default
would be worse than a crash, because an empty sender address makes
reply-detection match every message and quietly nudge people who already
answered.

---

## Running it for real

```bash
# 1. research + queue (needs `claude` on PATH)
python brace.py find --count 15

# 2. inspect before anything sends
python brace.py leads list --status new
python brace.py leads show 3

# 3. see what would go out, without sending
python brace.py send --dry-run --force

# 4. send for real
python brace.py send --force        # or let the engine fire it in-window

# 5. watch it
python brace.py dashboard           # http://127.0.0.1:8377
```

**Always-on mode:** `python brace.py engine` (or `pythonw`, or a shortcut in the
Windows Startup folder). It ticks every 60 seconds and fires each job inside its
window.

**Stop sends instantly:** `python brace.py pause`. That creates an empty `PAUSED`
file at the repo root; the senders no-op and the scheduler keeps running. Delete
the file or run `resume` to continue. The dashboard's toggle does the same thing.

---

## Design notes worth knowing

**State that matters never lives in a running process.** The gap between send
bursts is persisted to `run_days.next_burst_at` on disk. Crash the process, sleep
the machine, restart — the next tick reads the gap and continues. There is no
resume logic anywhere because there is nothing to resume.

**Intent is written before the side effect.** `db.claim_send()` records "about to
send" *before* calling Gmail, keyed on a deterministic `<lead_id>:<kind>`. If the
process dies mid-call, that row is found as `in_flight` and `engine.reconcile()`
asks Gmail's own Sent folder what actually happened. It never guesses — guessing
"sent" silently drops a prospect, guessing "not sent" emails them twice.

**Expensive checks scale with hits, not volume.** The daily reply sweep lists
inbox threads in one call, intersects with tracked threads, and only pays the
per-thread verification on the intersection. Cost tracks replies received, not
leads in the database.

**A blank field is correct; a plausible guess is not.** The research agent is
forbidden from constructing a LinkedIn URL. Missing data propagates as missing,
because nothing downstream re-verifies it before we act on it.

**Research profiles are chosen in code, not by the model.** `find --profile
quick` runs a one-account, six-search skill; the default runs the production
batch. Asking a production skill nicely for a small run does not work — it
optimises for quality and spends accordingly.
