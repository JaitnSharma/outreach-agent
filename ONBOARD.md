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

- **You cannot accidentally email a real person with this repo as it ships.** Try
  it as recklessly as you like.
- You still see the real thing happen: real emails leaving your account,
  correctly formatted and threaded, landing in your Gmail Sent folder.
- Then you watch them bounce, and watch the system notice, prune the dead
  addresses, and mark those leads dead. That is not the demo failing. That is
  bounce handling working, on live data.

Addresses come from **one file**, `email_source.py`, behind one config value.
Point it at a real lookup service and the same pipeline sends to real inboxes.
Nothing else changes. Step 6 covers it.

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
- **Guess an email address.** Ever. Step 6 explains why that refusal matters more
  than it sounds.
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
walks through it. Two settings there cause almost every failure, and both are
called out: the consent screen must be **External**, not Internal, and your own
Gmail address must be added under **Test users**.

It ends with you downloading one file. Then one command does the rest:

```bash
python setup_gmail.py path/to/gcp-oauth.keys.json
```

Your browser opens, you approve, and it writes `credentials.json`, asks Google
which mailbox you just authorised, and writes `config.json` for you. Nothing to
type.

```bash
python -c "import gmail; print(bool(gmail.get_access_token()))"
```

`True` means you are connected.

> If it goes quiet a week later with `invalid_grant`, that is a known Google
> behaviour with unpublished consent screens. Fix is in the troubleshooting
> section of `docs/gmail-setup.md`.

---

# Step 4 — Find three real leads

**The pipeline is complete.** It just needs your go-ahead to go and find people
who might actually buy.

Say the word and it researches **three real companies** that fit Brace's customer
profile, finds the person at each who could sign off on a purchase, and digs out
one genuine, checkable reason to email them.

Needs the `claude` CLI signed in, plus the scraper:

```bash
npm install -g defuddle-cli
```

Then:

```bash
python run_findprospects.py
```

A few minutes of real work: live searches, real pages, real companies. Watch
`logs/findprospects.log`.

### Read what came back

Open the CSV in `runs/`. For each lead, three columns matter:

- **`why_company`** — the hook. Every one traces to something a person actually
  published: a funding round, a job posting, a headcount jump.
- **`f2_content`** — the single line the final follow-up will carry.
- **`Work Email`** — a placeholder. Step 6.

Now see how a hook becomes an email:

```bash
python send_test.py --dry-run --to someone@example.com \
  --name "<first_name from the CSV>" \
  --company "<company from the CSV>" \
  --hook "<why_company from the CSV>"
```

That prints the exact message that would go out. Your researched hook sits at the
top; everything around it came from `templates.py` and is identical on every send.

Watch for rows flagged `[LOW-SIGNAL]`, `[COMPETITOR]` or `[STALE]`. Those are the
interesting ones — what the agent does when the happy path does not apply:

| Situation | What it does |
|---|---|
| No real signal found | Says so and flags it. Does not invent one. |
| Two companies share a name | Stops and reports it rather than guessing |
| They already use a competitor | Acknowledges it instead of pitching blind |
| Only news is a year old | Flags it rather than congratulating a stale raise |

Nothing has been written to the database. These are candidates, not a campaign.

---

# Step 5 — Watch one send, your choice

Pick one. Either way the message appears in your Gmail Sent folder, and nothing
touches the database.

**Option A — watch it bounce.** Use the placeholder address straight from the CSV:

```bash
python send_test.py --to "<Work Email from the CSV>" \
  --name "<first_name>" --company "<company>" --hook "<why_company>"
```

It sends, lands in Sent, and a minute later mailer-daemon replies in your Inbox.
That is the bounce path working on live data — the same path that keeps a real
list clean instead of quietly burning your sending reputation.

**Option B — watch it arrive.** Use your own address and read it as a prospect
would:

```bash
python send_test.py --to you@gmail.com \
  --name "<first_name>" --company "<company>" --hook "<why_company>"
```

Open it on your phone. That is exactly what a real recipient sees.

Skip this step entirely if you like. Nothing downstream depends on it.

---

# Step 6 — Turn the engine on

One thing stands between you and a running campaign: **real email addresses.**

### Why the agent will not find them for you

It could guess. `firstname@company.com` is right often enough to be tempting.

It will not, and that is a deliberate refusal rather than a missing feature.
Guessed addresses bounce. A bounce rate above a few percent is how a Gmail sender
gets classified as spam, and that reputation damage is not undone by fixing the
prompt afterwards. Every future campaign from that address suffers.

So address resolution was taken away from the model entirely and put in code:
**`email_source.py`**, behind one config value.

```bash
python email_source.py --mode
```

Three modes:

| `email_source` | Behaviour |
|---|---|
| `pseudo` *(default)* | Fabricates addresses that always bounce. Nothing real is reachable. |
| `manual` | Leaves addresses blank. You supply them. |
| `finder` | Calls whatever lookup service you configure. |

**This is what "it will stop filling placeholders" actually means.** Change one
value and every future row changes. No prompt edit, no model behaviour to trust.

### Option A — give it real addresses yourself

Set `"email_source": "manual"` in `config.json`. Rows now come out with the
address blank, and the importer skips blank rows on purpose, so a half-filled
batch can never half-send.

Add the leads you do have addresses for:

```bash
python manage.py add --company "Acme Ops" --designation "Head of Finance" \
  --mails priya@acmeops.com --name Priya \
  --why "<the hook from the CSV>" --f2 "<the f2_content from the CSV>"
```

### Option B — connect a finder

Set `"email_source": "finder"` and give it a command:

```json
{
  "email_source": "finder",
  "email_finder_command": "myfinder --name {first} --domain {domain}"
}
```

`{first}` and `{domain}` are substituted per contact. Print one address on
stdout, or nothing. Clay, Apollo, Hunter, Prospeo, an MCP server, a shell script,
anything that satisfies that contract works.

A lookup returning nothing leaves the field blank rather than guessing. That is
the entire point.

### Then start it

```bash
python manage.py list --status new     # confirm what is queued
pythonw scheduler.py                   # start the engine
```

---

## What the engine does once it is running

It wakes every 60 seconds and mostly does nothing. The full behaviour:

**Cold emails, 08:30 to 11:00, Mon-Fri, up to 50 a day.** Sends in bursts of at
most 15, never splitting one company across a burst, then goes quiet for a random
20 to 30 minutes. Spacing inside a burst is jittered and recomputed as it goes, so
a slow API call tightens the rest instead of letting the burst drift late.

**Bounce and reply sweep, 11:00.** Finds mailer-daemon messages, moves dead
addresses out of the lead, and marks a lead `failed` once it has nowhere left to
write. Then catches replies that landed on finished sequences, which the
follow-up path would never revisit.

**Follow-ups, 11:30 to 16:30, up to 100 a day.** F1 goes 48 hours after the cold
email, F2 48 hours after F1, both in the original thread. Every F1 that is due
goes before any F2, so more distinct people get at least one nudge.

**Hard stop at 17:00.** Checked before every individual send, not just per burst.

**Anyone replies, that company stops.** Not just that person, every colleague in
the sequence. They are marked `sibling_replied`, kept distinct from `replied`, so
you can always tell a real engagement from a cascaded one.

**It never sends twice.** Every send is claimed in a write-ahead log first, keyed
on lead and stage. If the process dies between calling Gmail and recording the
result, that row is found later and reconciled against your actual Sent folder.
It never guesses: guessing "sent" drops a prospect, guessing "not sent" emails
them twice.

**It survives interruption.** The gap between bursts lives on disk, not in memory.
Crash it, reboot, close the laptop mid-burst, and the next tick reads where it was
and carries on. At most one burst is lost, never a day.

**Watch it:** `python dashboard.py` → http://127.0.0.1:8377

**Stop it instantly:** create an empty file named `PAUSED` in this directory.
Sends stop, the scheduler keeps running. Delete it to resume. A file, so it works
at 2am without reading any code.

---

# You are done

You have watched it research real companies, write a grounded email, send for
real, and handle a bounce. You know where addresses come from and how to change
that.

To make it yours, three files:

- **`context/company.md`** — what you sell, who buys it, what signals mean they
  are ready. The research agent reads this cold on every run.
- **`context/voice.md`** — how your emails should sound.
- **`templates.py`** — the email itself. Keep the four slots, replace the copy.

Then set your rails: `blacklist.txt` for competitors, customers and anyone who
asked to be left alone. Caps and pacing at the top of `engine.py`.

Nothing in the engine knows anything about expense management. Swap those files
and the same machine runs your outbound instead.

## Where things live

| Read this | For |
|---|---|
| `README.md` | Architecture, lifecycle, design notes |
| `CLAUDE.md` | Operating rules, if you work on this with an AI agent |
| `context/company.md` | Who we are and who we sell to |
| `skills/findprospects/SKILL.md` | The research agent itself |
| `email_source.py` | Where addresses come from, and how to change it |
| `docs/gmail-setup.md` | Credentials, and the `invalid_grant` trap |
