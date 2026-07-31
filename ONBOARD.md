# Getting started

A lead generation and outreach pipeline. It finds companies worth selling to,
finds one real reason to email the decision-maker, writes the email, and sends
the sequence on a human schedule.

It works for whatever company you point it at. That company is called the
**tenant**, and it is one folder of four files. This repo ships with **Brace**,
a made-up corporate-card company, as the example — so there is something real to
run on day one. Brace is not the pipeline; it is what the pipeline is currently
selling for, and swapping it takes no code changes ([step 6](#6-point-it-at-your-own-company)).

Brace is fictional. The companies it researches are not.

Six steps, each one command. You can stop after any of them.

| | Step | Needs |
|---|---|---|
| 1 | [See it run](#1-see-it-run) | nothing |
| 2 | [Connect Gmail](#2-connect-gmail) | a Google account, ~5 min |
| 3 | [Find a real lead](#3-find-a-real-lead) | the `claude` CLI |
| 4 | [Watch one email send](#4-watch-one-email-send) | steps 2 and 3 |
| 5 | [Turn the engine on](#5-turn-the-engine-on) | real addresses |
| 6 | [Point it at your own company](#6-point-it-at-your-own-company) | nothing |

> The fastest way through this is to ask the agent. Open this repo in Claude
> Code and say "walk me through it" — it will drive these steps with you.

---

## 1. See it run

No credentials, no setup, nothing sent:

```bash
python agent.py demo
```

That loads three sample leads and renders exactly what would be sent.

Two things worth noticing. Both contacts at **Acme Ops** went out in the same
burst — the engine groups by company, so two people at one place never get
emails days apart. And it never called Gmail: `--dry-run` renders and selects
but cannot send.

```bash
python agent.py            # every command, grouped
python agent.py status     # what is in the pipeline
```

**Stop here if you just wanted to see the shape of it.**

---

## 2. Connect Gmail

The only step with clicking in it. You need one file from Google Cloud; the
script does the rest.

Full walkthrough: **[docs/gmail-setup.md](docs/gmail-setup.md)**. Short version:

1. [console.cloud.google.com](https://console.cloud.google.com) → new project
2. APIs & Services → Library → **Gmail API** → Enable
3. OAuth consent screen → User Type **External**, any app name, add your own
   address under **Test users**
4. Credentials → Create Credentials → OAuth client ID → **Desktop app**
5. Download the JSON somewhere outside this repo

Then:

```bash
python agent.py setup C:/Users/you/.outreach/gcp-oauth.keys.json
```

It opens your browser, you approve, and it writes both `credentials.json` and
your `config.json`. Nothing to type.

```bash
python agent.py doctor     # confirms Google accepted the token
```

---

## 3. Find a real lead

Everything so far used canned data. This part is real: it searches the web,
finds a funded company, finds a person who could actually buy, and writes the
opening line against something true about them.

```bash
python agent.py find --profile quick
```

One lead, capped at six searches, about a minute. It writes
`data/runs/sample-lead.csv` and prints the row. **It does not import or send.**

A real batch is the same command without the training wheels:

```bash
python agent.py find --count 15        # the production profile
```

That one takes a while and spawns a subagent per account. Do not run it to look
around — that is what `--profile quick` is for.

### What the model actually wrote

Take the hook from the row you just got and drop it into the finished email:

```bash
python agent.py test-send --dry-run --to someone@example.com \
    --name Priya --company "Acme Ops" --hook "<the hook from your CSV>"
```

Only the opening line came from the model. The greeting, the product line, the
call to action, the signature and every tag around them are fixed in
`outreach/templates.py`. The research agent fills **four** slots and cannot
touch anything else — so a bad research run costs you one weak sentence, not a
broken email.

---

## 4. Watch one email send

Now send one for real. Two options, both fine, and skipping is fine too:

```bash
# watch it bounce - the placeholder address is designed to fail
python agent.py test-send --to priya@acmeops.pseudoemail.com \
    --name Priya --company "Acme Ops" --hook "<your hook>"

# or watch it arrive, in your own inbox
python agent.py test-send --to you@gmail.com \
    --name Priya --company "Acme Ops" --hook "<your hook>"
```

Check your Gmail **Sent** folder. That message is what the engine sends, exactly.
`test-send` writes nothing to the database, claims no idempotency key, and counts
against no cap — it sits outside the pipeline on purpose.

### Why that address bounced

The agent is not allowed to invent email addresses. `firstname@company.com` is
right often enough to feel safe, and it is not: wrong addresses bounce, and a
bounce rate over a few percent gets your sending account classified as spam by
Gmail. That is permanent, and it poisons every future campaign from that mailbox.

So address resolution was taken away from the model and put in code, behind one
config value:

```bash
python agent.py email-for --mode
```

| `email_source` | What happens |
|---|---|
| `pseudo` | Fabricates an address that always bounces. The default. Nobody real can be contacted by accident. |
| `manual` | Leaves the field blank. You supply addresses; rows without one are skipped at import. |
| `finder` | Calls whatever lookup service you configure. |

Change it in `config.json`. **That value is what stops the placeholders** — not
a prompt, and not the agent remembering to behave.

For `finder`, add a command that prints one address on stdout, or nothing:

```json
{
  "email_source": "finder",
  "email_finder_command": "yourfinder --name {first} --domain {domain}"
}
```

Anything that fails, times out, or prints something that is not an address
resolves to blank. Never to a guess.

---

## 5. Turn the engine on

Once real addresses are flowing in:

```bash
python agent.py import data/runs/<your-file>.csv    # rows land as status='new'
python agent.py engine                              # start the scheduler
```

The engine ticks about once a minute and usually does nothing. When it does act:

| | |
|---|---|
| **Cold** | 08:30-11:00, Mon-Fri, up to 50/day |
| **Follow-ups** | 11:30-16:30, F1 then F2, up to 100/day |
| **Bounce sweep** | daily from 11:00, before follow-ups run |
| **Hard stop** | 17:00, enforced per email |
| **Bursts** | max 15 at a time, then a 20-30 minute gap |
| **Spacing** | jittered, never a fixed interval |

It stops for people who answer, and for their colleagues too — a reply from
anyone at a company halts the sequence for everyone there.

Two things make it safe to leave running. Pacing state lives in the database,
not in the process, so sleeping the machine loses nothing. And every send is
written down *before* Gmail is called, under a deterministic key — if the
process dies mid-call, the next run asks Gmail's Sent folder what actually
happened instead of guessing. Guessing "sent" drops a prospect; guessing "not
sent" emails them twice.

### The kill switch

```bash
python agent.py pause      # sends stop, scheduler keeps running
python agent.py resume
```

That is a file called `PAUSED` at the repo root. Create or delete it by hand and
it works the same — deliberately, so it is usable at 2am without reading source.

### Checking on it

```bash
python agent.py dashboard      # localhost:8377
```

This is what you open once a day to see how the mandate is going: how many cold
emails and follow-ups went out today, how many bounced, what is still queued,
anything that needs a human, and a pause switch.

---

## 6. Point it at your own company

Everything so far sold for Brace. Nothing in the engine knows that.

```bash
python agent.py tenant        # who it currently sells for, and where that lives
```

The company is one folder of four files:

```
context/brace/
    company.md      the ICP, the buying signals, who to contact
    voice.md        how the hook must sound
    copy.py         the fixed strings in the emails
    blacklist.txt   never-contact companies and domains
```

To sell for someone else:

```bash
cp -r context/brace context/yourco     # copy the folder
# edit the four files
```

```json
{ "tenant": "yourco" }
```

That is the whole operation. No code changes, and nothing about the send engine,
the pacing, the database or the research skills is aware of which tenant is
active.

**Do not edit `outreach/templates.py` to change what the email says.** That file
owns email *structure* — block order, HTML, and the rule that the hook lands
before any self-introduction. `copy.py` owns the sentences. Keeping those apart
is what stops a copy tweak from quietly breaking the format of every email.

---

## What you now have

```
agent.py            every command lives here
context/<tenant>/   the company being sold for - swappable
skills/             the research agents
prospecting/        research half - ends at a CSV, cannot send
outreach/           send half - reads the database, no model runs
tools/              setup, dashboard, manual inspection
data/               the database, run CSVs, logs
```

The two halves never mix, and that is the main design decision in the repo. The
research half is slow, non-deterministic and expensive; it ends at a CSV. The
send half is fast, deterministic and boring; **no model runs at send time**. The
database sits between them, so rows are reviewable before anything goes out.

Three layers own three different things, and that is the second design decision:

| Layer | Owns | Varies |
|---|---|---|
| `outreach/templates.py` | structure, HTML, block order | never |
| `context/<tenant>/copy.py` | what the company sells, who signs | per company |
| the database | four slots the research agent filled | per lead |

`README.md` has the architecture in full. `CLAUDE.md` is what the agent reads.
