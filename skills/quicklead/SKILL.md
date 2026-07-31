---
name: quicklead
description: Find ONE real prospect fast, under a hard research budget, to demonstrate what the pipeline produces. Writes a sample CSV and prints the row. Use for onboarding, demos and smoke tests. NOT for filling the pipeline — that is findprospects.
---

# quicklead — one real lead, under budget, in about a minute

This is the demo skill. Someone has just cloned the repo and wants to see a
real row come out of the machine before they invest anything in it.

**Your entire job:** find ONE real person at ONE real company, write the hook,
print the row. Then stop.

## The budget is the point

| Limit | Value |
|---|---|
| Accounts | 1 |
| Contacts | 1 |
| Web searches | **6 total, hard cap** |
| Scrape calls | 1 batched call, max 2 URLs |
| Subagents | **zero — you do this yourself, inline** |
| Wall clock | aim for under 2 minutes |

Going over the budget is a failure of this skill even if the lead is excellent.

**Why this exists as a separate skill:** `findprospects` is the production
skill. It discovers a wide candidate pool, spawns a subagent per account, and
researches each one deeply — correct for a batch of 15, catastrophic for a
demo. Asked to "just do 3", it ran 50+ searches for seven minutes to produce
three example rows. Nobody evaluating a repo waits that long to see a sample.

So this skill is not "findprospects with a smaller number". It is a different
shape: no discovery pool, no delegation, no depth. One account, straight
through.

**Do not read `skills/findprospects/SKILL.md`.** It will pull you back toward
the wide path. Everything you need is here.

---

## Step 0 — read the frame (2 files, no searches)

1. `context/company.md` — who Brace sells to and the buying signals.
2. `context/voice.md` — how the hook must sound.

Do not read anything else. Do not read `data/worked_accounts.csv`; this is a
demo and dedupe does not matter.

## Step 1 — pick one account (1-2 searches)

You need a funded tech startup, roughly 20-200 people, that raised or visibly
grew recently. One search is usually enough:

    "seed funding" OR "Series A" startup announced <current month> <current year>

Take the **first credible hit** that clears the bar. Do not build a candidate
list. Do not compare options. The demo does not get better because you picked
the third-best company instead of the first.

Skip anything in `data/blacklist.txt` if it happens to come up. Do not read the
file preemptively.

## Step 2 — one scrape, two pages max (1 call)

    python brace.py scrape <homepage> <careers-or-about> --format json

Check `schemaOrgData` first — it carries `Organization` and `JobPosting` as
structured fields, free. Read the prose only if that comes up empty.

The scraper exits 0 even on a 404 or a block, so judge success on the content
that came back, not the exit code.

## Step 3 — one contact (2-3 searches)

Find one person who could actually buy: founder, COO, Head of Finance, Head of
Ops. Never an accountant, AP/AR clerk, bookkeeper or junior analyst.

    "<company> linkedin"                    -> usually surfaces leadership
    "<full name> <company> linkedin"        -> their profile

**Never construct a LinkedIn URL.** Not from a name pattern, not by adapting
one that looks close. Two plausible matches means EMPTY. Nothing found means
EMPTY. An empty field is correct here; a fabricated one is a lie that nothing
downstream catches.

Same rule for every field. If sources disagree on a title, write the safe
subset ("Co-Founder", not a guess between CTO and COO).

## Step 4 — the address (do not think about this one)

Run this once and use exactly what it prints:

    python brace.py email-for --first <first_name> --domain <company_domain>

If it prints an address, that is the address. If it prints nothing, leave the
field empty. You never write an email address yourself — a guessed address
bounces, and a bounce rate over a few percent gets the sending mailbox
classified as spam by Gmail, permanently.

## Step 5 — write the hook

`why_company` — the opening line of the cold email, landing before the reader
knows who we are:

- 2-3 sentences, under 55 words.
- Sentence 1: the signal, specific and checkable (a real number, date, role or
  quote).
- Sentence 2: ONE inference about what that means for **them**, not for us.
- Never mention Brace, cards, or expense management. The template says that in
  the next paragraph.
- No em-dashes. Banned: "excited", "reached out", "hope this finds you well",
  "game-changing", "revolutionary", "following your journey", "leveraging".

**Specificity test.** Cover the company name and reread it. If it could have
been sent to any other funded startup, it fails. Rewrite it.

`f2_content` — one sentence compressing the case, for the final follow-up.

If you genuinely found no real signal, say so and prefix the hook with
`[LOW-SIGNAL] `. Do not invent one to make the demo look better. A demo that
shows the honest failure mode is more convincing than a fabricated success.

## Step 6 — write the CSV

Write to `data/runs/sample-lead.csv`, overwriting it. Exactly this header:

```
full_name,first_name,company,designation,linkedin_url,company_domain,company_social_url,why_company,f2_content,Work Email
```

Quote any field containing a comma. UTF-8.

**Do not import to the database.** Do not run `brace.py import`. Whoever is
being onboarded decides that, not you.

## Step 7 — report

Print exactly this, filled in:

```
Found 1 lead in <N> searches.

  Company    <name> - <what they do>, <funding stage + when>, ~<headcount> people
  Contact    <full name>, <title>
  Signal     <the one fact you found, in a few words>
  Address    <address>   (<pseudo / real / blank + why>)

  Hook:
  <the why_company text, as it will appear in the email>

Written to data/runs/sample-lead.csv. Nothing imported, nothing sent.

See it inside the finished email:
  python brace.py test-send --dry-run --to <address> \
      --name <first_name> --company "<company>" --hook "<hook>"
```

Then stop. Do not offer to find more. Do not import. Do not send.
