# Start here

Follow this top to bottom. Every step has one command, what you will see, and
what it means. Takes about 20 minutes, and you can stop after Step 2 and still
understand the whole thing.

---

## What this is

**A lead generation and email outreach agent.** You give it a target count. It
goes and finds companies worth selling to, works out who the decision-maker is,
digs up one real reason to email that specific person, writes the email, and
then sends the follow-up sequence on a schedule that looks like a human wrote it.

It is demonstrated for **Brace**, a made-up company selling corporate cards to
funded startups. Brace is fictional. The companies it goes and researches are
not.

### The one thing to understand before anything else

The system is two halves that **never touch each other**:

| | Research | Sending |
|---|---|---|
| Runs on | an LLM | no LLM at all |
| Speed | slow, minutes per account | fast |
| Behaviour | non-deterministic | completely deterministic |
| Can it send email? | **no** | yes |
| Ends at | a CSV | your outbox |

Between them sits a database. The research half writes rows there and stops. You
look at them. Only then does the sending half pick them up.

That gap is the whole design. Everything else follows from it.

---

## About the email addresses (read this, it matters)

The leads are **real**. Real companies, real people, real funding rounds and job
posts found on the live web.

The email addresses are **fake on purpose**. Every one looks like
`priya@acmeops.pseudoemail.com`. That domain does not exist, so every send
bounces.

This is deliberate, and it is good news for you:

- **You cannot accidentally email a real person with this repo as it ships.** Run
  the demo as recklessly as you like.
- You still get to see the real thing happen: real emails leaving your account,
  correctly formatted, correctly threaded, landing in your Gmail Sent folder.
- Then you watch them bounce, and watch the system notice, prune the dead
  addresses, and mark those leads dead. That is not the demo failing. That is the
  bounce handling working, on live data.

The fake address comes from **one function**, documented in the skill. Swap it
for Clay, Apollo, Hunter, Prospeo or anything else and the same pipeline is
suddenly sending to real inboxes. Nothing else changes. That is the intended
handover point, and it is the only thing standing between this and production.

---

## What it will do

- Find companies matching an ideal customer profile you define in a text file.
- Judge whether there is a real buying signal or just marketing noise.
- Identify who can actually buy, and skip people who cannot.
- Write an opening line grounded in one specific, checkable fact about them.
- Refuse to invent a fact when it cannot find one.
- Send a cold email, then two follow-ups, paced like a person.
- Stop the entire sequence for a company the moment anyone there replies.
- Notice bounces, prune dead addresses, and mark leads that are beyond saving.
- Survive a crash, a reboot, or a laptop lid closing mid-send without double-sending.

## What it will not do

- **Send anything you have not seen.** Research ends at a database row. A human
  step sits between finding someone and emailing them.
- **Find real email addresses.** Not until you wire in a finder. By design.
- **Email a real person as shipped.** Every generated address bounces.
- **Research and send in one go.** Different processes, different schedules, on purpose.
- **Email anyone twice.** Every send is claimed in a write-ahead log first.
- **Send outside working hours.** Hard stop at 17:00, no exceptions, no override.
- **Use an LLM at send time.** The model never writes an email. See Step 2.

---

# Step 1 — Watch it run. No setup, no credentials, 2 minutes.

You need Python 3.9+ and nothing else. No `pip install`, this is stdlib only.

```bash
python import_csv.py runs/sample-for-testing.csv
```

Three sample prospects go into a fresh database. Notice it reports what it
*skipped* too. Every row is checked for a missing or malformed address, a
duplicate already in the pipeline, a blacklisted company, and an empty hook.

```bash
python manage.py list --status new
```

Three leads, two companies, `status='new'`. Nothing has been sent.

```bash
python send_cold.py --dry-run --force
```

**This is the interesting one.** Read the log lines. You will see it:

- pick up 3 leads across 2 companies
- keep both Acme Ops contacts together, because a burst never splits a company
- compute a pacing budget and a per-mail gap with jitter
- print exactly what it *would* send

`--dry-run` means it never calls Gmail. `--force` skips the time-of-day window
so you can run this at midnight.

```bash
python dashboard.py
```

Open http://127.0.0.1:8377. Funnel, today's counts, and a pause switch. Ctrl+C
when done.

**You just ran the entire send pipeline without credentials and without sending
anything.** If you stop reading here, you have seen the core of it.

---

# Step 2 — Read an email, and see who actually wrote it

```bash
python -c "import db, templates, re; h=templates.render_cold(db.load_placeholders(db.get_lead(1))); print(re.sub(r'<[^>]+>','',re.sub(r'<br\s*/?>','\n',h)))"
```

Look at the output. Now open `templates.py` next to it.

Everything you just read — greeting, the product sentence, the call to action,
the sign-off, the HTML — is **hardcoded**. The model wrote exactly one thing: the
opening paragraph.

That is the central constraint of this codebase. The model fills four bounded
slots and never owns the structure:

| Slot | What it carries |
|---|---|
| `name` | first name |
| `company` | their company |
| `why_company` | **the hook** — the one AI-written part |
| `f2_content` | one line, final follow-up only |

So a bad research run costs you one weak sentence, which a human notices. It can
never cost you a malformed email, a broken link, a wrong sign-off, or a message
that forgets which company sent it.

Notice also that the hook comes **first**, before any self-introduction. An email
opening with "I'm X from Y" is deleted before the reader reaches the point.

---

# Step 3 — Connect your Gmail (5 minutes, once)

Now let us make it real.

You need a Google Cloud OAuth client. **[docs/gmail-setup.md](docs/gmail-setup.md)**
walks through it — about 5 minutes of clicking, once. It ends with you
downloading one file.

Then one command does the rest:

```bash
python setup_gmail.py path/to/gcp-oauth.keys.json
```

Your browser opens, you approve, and it writes `credentials.json` for you. It
prints the exact `config.json` to copy.

```bash
cp config.example.json config.json      # then paste in what the script printed
python -c "import gmail; print(bool(gmail.get_access_token()))"
```

`True` means the whole chain works.

> If it goes quiet a week later with an `invalid_grant`, that is a known Google
> behaviour with unpublished consent screens. The fix is in the troubleshooting
> section of `docs/gmail-setup.md`.

---

# Step 4 — Send for real, and watch it bounce

Reset and reseed so you are sending fresh:

```bash
rm prospects.db
python import_csv.py runs/sample-for-testing.csv
python send_cold.py --force
```

Three emails just left your account, for real.

**Go and look at your Gmail Sent folder.** They are there. Properly formatted,
properly addressed, each one its own thread. This is exactly what a prospect
would receive. Read one on your phone if you want to see how it lands.

Now wait a minute or two and **check your inbox**. Three bounce notifications
from mailer-daemon, because `pseudoemail.com` does not exist.

Then let the system deal with it:

```bash
python bounce_sweep.py
python manage.py list --status failed
```

It found the bounces, moved each dead address out of `mails` into `wrongMails`,
and marked every lead `failed` because it has nowhere left to write.

**Nothing went wrong here.** You just watched bounce reconciliation work
correctly against live data, which is the part most outreach tooling gets wrong.
Point a real email finder at it and this same path silently keeps your list clean
instead of burning your sending reputation.

---

# Step 5 — Find real leads

This one needs the `claude` CLI on your PATH and signed in, plus a scraper:

```bash
npm install -g defuddle-cli
```

Then:

```bash
python run_findprospects.py
```

This takes a few minutes and does real work: real web searches, real page reads,
real companies. Watch `logs/findprospects.log`.

When it finishes, open the CSV it wrote in `runs/`. Look at the `why_company`
column. Every one of those hooks traces to something a person actually published
— a funding round, a job posting, a headcount change.

Then look for rows flagged `[LOW-SIGNAL]`, `[COMPETITOR]` or `[STALE]`. Those are
the interesting ones. They are what the agent does when the happy path does not
apply:

| Situation | What it does |
|---|---|
| It cannot find a real signal | Says so and flags it. Does not invent one. |
| Two companies share the name | Stops and reports the ambiguity rather than guessing |
| They already use a competitor | Acknowledges it instead of pitching blind |
| The only news is a year old | Flags it rather than congratulating a stale raise |

The email addresses are still fake. The leads are real.

---

# Step 6 — Make it yours

Three changes turn this from a demo into your pipeline.

**1. Change who you are.** Edit `context/company.md` — what you sell, your ideal
customer, who to contact, and the signals that mean someone is ready to buy. Then
`context/voice.md` for how your emails should sound. The research agent reads
both cold on every run. Nothing in the engine knows anything about expense
management.

**2. Change the email.** `templates.py`. Keep the four slots, replace the copy.
Because the persistence layer never learns what the words mean, nothing else
needs touching.

**3. Wire in real email addresses.** Open `skills/findprospects/SKILL.md` and find
Step 5, the pseudo-email rule. Replace it with a call to your finder. Everything
downstream already handles the result correctly, including the addresses that
turn out to be wrong — you saw that in Step 4.

Then set your safety rails: `blacklist.txt` for competitors, customers and
anyone who asked to be left alone. Sending caps and pacing live at the top of
`engine.py`. The 17:00 hard stop is there on purpose.

---

## Where things live

| Read this | For |
|---|---|
| `README.md` | Architecture, lifecycle, design notes |
| `CLAUDE.md` | The operating rules, if you work on this with an AI agent |
| `context/company.md` | Who we are and who we sell to |
| `skills/findprospects/SKILL.md` | The research agent itself |
| `docs/gmail-setup.md` | Credentials, and the `invalid_grant` trap |

## Two things to remember

**The kill switch is a file.** Create an empty file called `PAUSED` in this
directory and every send stops while the scheduler keeps running. Delete it to
resume. It is a file so it works at 2am without reading any code.

**`--dry-run` never sends.** Use it freely. `--force` only bypasses the
time-of-day window, never the safety gates or the duplicate protection.
