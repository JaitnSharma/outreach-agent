---
name: findprospects
description: Find funded startups matching Brace's ICP, identify the finance/ops decision-makers at each, research one real buying signal per contact, and write a signal-grounded outreach hook. Produces data/runs/<today>.csv and pushes it to prospects.db. Use when asked to "find prospects", "fill the pipeline", "run prospecting", or "find accounts".
---

# findprospects — account research → contacts → hooks → CSV → DB

You find the accounts and the people, write the hook, fill the email, and push
to the database. Your job ends when the rows are in `prospects.db`.

**This is the production skill and it is expensive by design** — wide discovery,
one subagent per account, deep research on each. That is correct for a real
batch and wrong for anything else. If you were asked for a demo, a sample, a
smoke test, or "just one or two to see what it looks like", stop and use
`skills/quicklead/SKILL.md` instead.

## The workflow you live inside

```
1. YOU (orchestrator): qualify accounts -> spawn 1 subagent per account
                       -> collect rows -> data/runs/<today>.csv
2. YOU: python brace.py import data/runs/<today>.csv   -> prospects.db (status='new')
3. The send engine (separate, not you): picks up status='new' and runs cold -> F1 -> F2
```

You own steps 1 and 2. **You never send email and never touch Gmail.** The send
engine is a different process on a different schedule.

---

## Division of labour — read this before you do anything

- **Discovery is yours alone.** One brain doing discovery is what guarantees no
  two subagents land on the same account. **Never let a subagent discover its own
  account.**
- **One subagent per account.** The unit of parallelism is the account. Each
  subagent researches one company in isolation, so its hook is written against
  that company's facts and never drifts toward a house template.
- **Subagents write nothing to disk** except throwaway scraper output under
  `data/runs/scrapes/<account-slug>/`. If N subagents write one file, they clobber
  each other. They report; you write, once.
- **No validation pass.** Trust the subagents. Your job is to route context in
  and stitch rows out, not to re-check their titles or rewrite their hooks.

---

## Dedupe — the self-sustaining loop

`data/worked_accounts.csv` (single column, header `accounts`) is the memory of every
account already in the pipeline.

- **Before researching:** read it. Skip any account already listed
  (case-insensitive match on name). Never re-queue a worked account.
- **After the run:** append every NEW account you queued, one per line, using the
  Edit tool. Add rows only. This is what stops the next run rediscovering the
  same companies. **Never query `prospects.db` for this.**

Also read `data/blacklist.txt` — never queue an account or domain matching any line
(case-insensitive substring, matched against both name and domain).

---

## Before you start

1. Read `context/company.md` — who Brace is, the ICP, who to contact, and the
   four buying signals. This is the frame for every judgement below.
2. Read `context/voice.md` — the hook has to sound like this.
3. Read `data/worked_accounts.csv` and `data/blacklist.txt`.

Default batch: qualify ~15 accounts unless given a number. If given a number,
that is the qualified-account target.

---

## Stage 1 — qualify accounts (you, single-threaded)

Goal: **a funded tech startup, 20-200 people, that recently got money or is
visibly growing.** Full criteria are in `context/company.md`.

### Hard filters — DROP if any fail

- **Funding:** raised a seed or Series A/B, roughly within 18 months. A company
  with no external funding has no card spend worth managing.
- **Headcount:** roughly 20-200. Under 20 the pain is not real yet; over 200 they
  have almost certainly already bought.
- **Type:** a tech or product company. Not agencies, not consultancies, not
  local services.

### The one fuzzy call — is there a real signal, or just noise?

| Signal seen | Verdict | Why |
|---|---|---|
| Series A announced 3 months ago, 6 open roles including "Finance Manager" | **PASS** | Fresh money, visible growth, and they are literally hiring the person who would own this. |
| Company website says "we're growing fast!", no funding news, no job posts, no dates | **DROP** | Marketing copy is not a signal. Nothing here is checkable, so no honest hook can be written. |
| Seed 14 months ago, headcount went 25 -> 60 on LinkedIn, opened a second office | **PASS** | The raise is older, but the growth is recent and specific. Two corroborating facts beat one stale one. |

**Never drop an account for being unglamorous.** Only the hard filters
disqualify. A boring B2B SaaS with 80 people and a fresh Series A is a better
prospect than an exciting 8-person AI startup.

### Discovery — scrape wide, read narrow

Scraping costs no tokens. Reading costs everything. Pull many source pages in
one batched call:

```bash
python brace.py scrape <funding-roundup-url> <vc-portfolio-url> ... --format json --out-dir data/runs/scrapes
```

Funding roundups, VC portfolio pages and accelerator batch lists are dense — one
page is often dozens of candidates. Scrape a wide set at once, then **grep the
saved files** for names and signals rather than reading each into context. Open
a file only when it holds an account you are about to qualify.

Free scraping buys you **more accounts**, not more pages per account.

Sources: funding roundups (TechCrunch, Entrackr, Inc42, YourStory, EU-Startups),
VC portfolio pages, YC/accelerator batch lists, Crunchbase news.

### The handoff packet

For each account you keep, capture exactly five fields. This is all a subagent
gets about the company, and it is enough:

- account name
- primary domain
- one line on what they build
- funding stage + amount + roughly when
- headcount estimate + how you got it

---

## Stage 2 — the subagent brief

Spawn one subagent per qualified account, in parallel where the tooling allows.
Give each one exactly this, with the packet filled in:

````
You are researching ONE account for Brace's outbound pipeline. You have no other
context — everything you need is here or in the two files named below.

ACCOUNT PACKET (from orchestrator):
  name:        <name>
  domain:      <domain>
  what:        <one line>
  funding:     <stage, amount, when>
  headcount:   <estimate + source>

FIRST: read context/company.md and context/voice.md in this directory. They tell
you who Brace sells to, who to contact, the four buying signals, and how the
hook must sound. Do not skip this.

YOUR JOB: find the right contacts at this account, find ONE real buying signal
per contact, and write the outreach copy. Write NO data to disk. Return one
fenced block, described at the end.

--- STEP 0 — scrape, once, bounded ---
One batched call, exactly these four page types:
  * the homepage (what they build)
  * the careers/jobs page (the hiring signal, and often the finance role)
  * about / team / leadership (who to contact, size read)
  * one recent funding or news post, if one exists

```bash
python brace.py scrape <url1> <url2> <url3> <url4> --format json --out-dir data/runs/scrapes/<slug>
```

Four page types is the BUDGET, not a floor to build on. Going deeper into docs,
pricing or blog archives makes the hook WORSE, not better: more material dilutes
the one verifiable fact the specificity test depends on.

Check `schemaOrgData` in the JSON before reading prose — careers pages carry
`JobPosting` (title, location, date) and company pages carry `Organization`.
That is structured and free.

The scraper exits 0 even on a 404 or a block, so judge success on the content
that came back, never the exit code. LinkedIn will not scrape (auth wall). Never
open a browser tool.

--- STEP 1 — size the company ---
No headcount rule. Use what you find: team page, LinkedIn company page in search
results, job post volume. Decide SMALL (under ~50) or SCALED (~50-200). This
decides who you contact.

--- STEP 2 — pick contacts ---
SMALL  -> 2-3 contacts: Founder/CEO, COO or Head of Ops, whoever holds finance.
SCALED -> 3-4 contacts: Head of Finance / Controller / VP Finance, Head of Ops,
          Chief of Staff.

SENIORITY FLOOR — HARD FILTER. Every contact must be able to BUY, or to walk it
to the person who can. Never queue an accountant, AP/AR clerk, bookkeeper,
junior analyst, or an unqualified "Finance" IC. They live inside the problem and
cannot fix it, and emailing them asks a stranger to escalate for us.

If an account yields nobody above the floor, RETURN FEWER ROWS. Two solid
contacts beat four padded ones. Never pad to hit a count.

--- STEP 3 — find the signal (this is the actual job) ---
For each contact, find ONE real, recent, checkable buying signal. The four that
matter are in context/company.md: recent funding, hiring surge, expansion,
stated pain.

Rank what you find and use the single best one. A specific fact with a date
beats three vague ones. Prefer a signal that connects to the person you are
writing to: a Finance lead cares that they were just hired into a mess; a
founder cares that headcount doubled.

If two contacts at the same account get the same signal, that is fine — but the
INFERENCE must differ by role. Do not send two people the same sentence.

--- STEP 4 — identity fields ---
`linkedin_url` and `company_domain` are what a real email-finder consumes, so
get them right.

1. Company page first: search "<account name> linkedin". One search, and it
   usually surfaces two or three leadership profiles for free.
2. Person profiles: one search each, shape "<full name> <account> linkedin".
   A combined "<account> leadership team linkedin" search does NOT work —
   aggregators outrank linkedin.com/in and you get nothing usable.
3. A `linkedin.com/posts/<slug>_...` result gives you `linkedin.com/in/<slug>`
   ONLY when the result title shows that person as the post's author.

NEVER CONSTRUCT A LINKEDIN URL. Not from a name pattern, not by adapting one
that looks close. Two plausible matches -> EMPTY. Nothing found -> EMPTY.
An empty field is a correct and expected value here. A fabricated one points the
downstream email finder at a stranger and nothing catches it before we send.

Same discipline everywhere: if sources disagree on a title, write the safe
subset ("Co-Founder", not a guess between CTO and COO).

--- STEP 5 — the email address (DO NOT think about this one) ---
You do not decide the address and you never write one yourself. Run this once
per contact and use exactly what it prints:

    python brace.py email-for --first <first_name> --domain <company_domain>

If it prints an address, that is the address. If it prints NOTHING, leave the
Work Email field EMPTY. Empty is a correct answer here, not a failure to try
harder.

WHY YOU ARE NOT ALLOWED TO GUESS: firstname@company.com is right often enough
to feel safe. It is not. Wrong addresses bounce, and a bounce rate over a few
percent gets the sending account classified as spam by Gmail. That is permanent
and it poisons every future campaign from that mailbox. One guessed address is
not worth that, ever.

The mode is configured, not chosen by you. It may be generating placeholders
that always bounce, leaving the field blank for a human, or calling a real
lookup service. All three are correct behaviour and none of them are your call.
`python brace.py email-for --mode` will tell you which is active if you want to
report it accurately.

--- STEP 6 — write the copy ---
Two fields, both in the register of context/voice.md.

`why_company` — THE HOOK. This is the opening line of the cold email, and it
lands before the reader knows who we are. Rules:
  * 2-3 sentences. Under 55 words.
  * Sentence 1 states the signal, specifically and checkably (a real number, a
    real date, a real role, a real quote).
  * Sentence 2 makes ONE inference about what that means for THEM. Not for us.
  * Never mention Brace, cards, or expense management. The template says that
    in the next paragraph. If the hook sells, the email reads like a broadcast.
  * No em-dashes. Banned: "excited", "reached out", "hope this finds you well",
    "game-changing", "revolutionary", "following your journey", "leveraging".

  SPECIFICITY TEST — apply it before you return. Cover the company name and read
  the hook. If it could have been sent to any other funded startup, it FAILS.
  Rewrite it. One verifiable fact from your research must survive the cover-up.

`f2_content` — the middle paragraph of the final follow-up. One or two
sentences compressing the whole case. Example shape: "My case in one line: you
raised in March, headcount roughly doubled since, and nobody has been hired to
own finance yet. That gap is the entire reason Brace exists."

--- EDGE CASES — handle these deliberately, do not ignore them ---

1. NO USABLE SIGNAL. Nothing recent, specific or checkable exists.
   -> Do NOT fabricate one. Do NOT stretch a vague fact into a fake insight.
      Either return the row with an honest, non-specific opener and prefix the
      hook with "[LOW-SIGNAL] ", or drop the contact and say why.
      A flagged weak row a human can catch beats an invented fact that ships.

2. AMBIGUOUS ACCOUNT. Two or more real companies share this name and you cannot
   tell which one the packet means.
   -> STOP researching. Return zero rows and report
      "AMBIGUOUS: <name> matches <A> and <B>, could not disambiguate."
      Guessing here means researching one company and emailing another.

3. ALREADY ON A COMPETITOR. You find Ramp/Brex/Navan/Pleo/Razorpay etc. in their
   stack, a job post, or a blog.
   -> Do NOT pitch blind, and do NOT drop them. The hook must ACKNOWLEDGE it and
      narrow to one angle where we might genuinely differ (multi-entity
      reconciliation, regional card issuing, pricing at their size). Prefix the
      hook with "[COMPETITOR] " so the human reviewer sees it before sending.

4. STALE SIGNAL. The only signal you can find is more than ~12 months old and
   nothing corroborates it.
   -> Do NOT present it as current. Either find a second, recent fact that makes
      it live again (headcount growth, a new office), or treat it as case 1 and
      flag "[STALE] ". Never write "congrats on the raise" about a raise from
      two years ago.

--- RETURN FORMAT ---
Output ONE fenced block. One line per contact, pipe-delimited, exactly this
field order:

full_name | first_name | company | designation | linkedin_url | company_domain | company_social_url | why_company | f2_content | Work Email

Return only that block. Do not write files. Do not add commentary outside it.
If you returned zero rows, say why in one line instead of the block.
````

---

## Stage 3 — collect and write (you)

Buffer every subagent's returned block in memory. When all have reported:

1. **Write ONE CSV** to `data/runs/<today>.csv`. Do not append per-account as
   subagents finish. Header, exactly this order:

```
full_name,first_name,company,designation,linkedin_url,company_domain,company_social_url,why_company,f2_content,Work Email
```

- One row per contact. Quote any field containing a comma. UTF-8.
- Same `company` string across an account's rows — the send engine batches by
  company and must group them.
- Skip accounts that returned nothing usable, but note them for the report.

2. **Push to the DB.** Dry-run first, then for real:

```bash
python brace.py import data/runs/<today>.csv --dry-run
python brace.py import data/runs/<today>.csv
```

`brace.py import` gates every row (blank email, malformed email, duplicate,
blacklist, empty hook). Do not re-validate by hand — run it and relay the
summary it prints.

3. **Update the memory.** Append every newly queued account to
   `data/worked_accounts.csv`, one per line, using the Edit tool.

---

## Report back

```
Qualified N accounts, spawned N subagents. Wrote M rows across C accounts to data/runs/<date>.csv.
Imported: X inserted, Y skipped.

Queued (by account):
- Acme Ops (SaaS, Series A $12M, ~70 people, SCALED) — Priya (Head of Finance) · Dev (COO)
- Bolt Labs (fintech, seed $3M, ~25 people, SMALL) — Anish (Founder)

Flagged for review:
- Nova AI — [COMPETITOR] already on Ramp, hook acknowledges it
- Quiet Co — [LOW-SIGNAL] nothing recent found, generic opener

Dropped:
- Zeta — ambiguous name, two real companies
- Mega Corp — ~900 people, over the ICP ceiling
- Old Startup — only signal is a 2024 raise, nothing since

Next: rows are status='new'. The send engine picks them up on its next cold run.
Review first:  python brace.py leads list --status new
```

---

## Notes

- Run `python` (not `python3`). Windows paths.
- **Never open a browser tool.** All net access goes through WebSearch, WebFetch,
  or `brace.py scrape`. LinkedIn is behind an auth wall — when a profile cannot
  be found via search, leave the field EMPTY per the no-fabrication rule.
- Page reads go through `brace.py scrape`, not WebFetch. Reserve WebFetch for
  pages the scraper fails on.
- The DB is only ever touched through `brace.py import`. Never write
  `prospects.db` directly. Never touch Gmail.
