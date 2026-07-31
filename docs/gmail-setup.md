# Gmail setup

You only need this to **send** email. The pipeline is fully explorable without
it — see "Try it in two minutes" in the README.

Two files are involved:

| File | What it is | Where it comes from |
|---|---|---|
| `gcp-oauth.keys.json` | Your OAuth client (client id + secret) | You download it from Google Cloud, once |
| `credentials.json` | Your refresh token | `brace.py setup` writes it for you |

Neither belongs in this repo. Keep them outside the project directory and point
`config.json` at them by path.

---

## 1. Create an OAuth client (about 5 minutes, once)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create
   a project, or pick an existing one.
2. **Enable the Gmail API**: APIs & Services → Library → search "Gmail API" →
   Enable.
3. **Configure the consent screen**: APIs & Services → OAuth consent screen.
   Set User Type to **External** (not Internal), give it any app name, and add
   your Gmail address under **Test users**. Nothing needs verification.
4. **Create the client**: APIs & Services → Credentials → Create Credentials →
   OAuth client ID → Application type **Desktop app** (not Web application).
5. Download the JSON. Save it somewhere outside this repo, e.g.
   `C:/Users/you/.outreach/gcp-oauth.keys.json`.

## 2. Get your refresh token (one command)

```bash
python brace.py setup C:/Users/you/.outreach/gcp-oauth.keys.json
```

It opens your browser, you approve access, and it writes `credentials.json` next
to the keys file. Google will warn that the app is unverified — expected for a
personal OAuth client. Click through via "Advanced".

It then asks Google which mailbox you just authorised and **writes `config.json`
for you**, so there is nothing to type. That is it.

## 3. Verify

```bash
python brace.py doctor
```

`True` proves the whole chain: config resolves, both files parse, and Google
accepts the refresh token.

The generated `config.json` looks like this:

```json
{
  "sender_email": "you@gmail.com",
  "gmail_credentials_path": "C:/Users/you/.outreach/credentials.json",
  "gmail_oauth_keys_path": "C:/Users/you/.outreach/gcp-oauth.keys.json",
  "email_source": "pseudo"
}
```

If you ever edit it by hand, use forward slashes or double the backslashes. A
single backslash is not valid JSON — the loader says so explicitly rather than
pretending the key is missing.

`email_source` decides where prospect addresses come from. It starts at
`pseudo`, which fabricates addresses that always bounce so nothing real can be
contacted. See [../ONBOARD.md](../ONBOARD.md) for how to change it.

---

## Troubleshooting

**`Error 403: org_internal` at sign-in.** The consent screen is set to Internal,
which only admits accounts in the same Workspace organisation. Change User Type
to External. If that option is greyed out, the project belongs to a Workspace
org — make a new one under a personal Google account.

**`Error 403: access_denied` at sign-in.** Your address is not in the Test users
list. OAuth consent screen → Test users → Add users → save, then re-run.

**`invalid_grant` after about a week.** This is the one that will confuse you.
While the consent screen is in **Testing** mode, Google expires refresh tokens
roughly every 7 days. The pipeline goes quiet with no obvious cause.

Fix it permanently: OAuth consent screen → **Publish App**. You do not need
verification for personal use with a small scope set. Or just re-run
`brace.py setup` when it happens.

**"Google did not return a refresh_token."** You have authorised this client
before, and Google only issues a refresh token on first consent. `brace.py setup`
sends `prompt=consent` to force a fresh one, but if it still happens, revoke the
app at [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
and run it again.

**"has no 'installed' key".** You created a Web application client instead of a
Desktop app one. Make a new client of the right type; you can delete the old one.

**Nothing sends and there is no error.** Check for a `PAUSED` file in the project
directory — that is the kill switch, and it makes senders no-op silently by
design. Delete it to resume.

## What this grants

`gmail.send` and `gmail.readonly`. Read access is needed to detect replies and
bounces, which is how sequences stop for people who have already answered. The
token lives only in `credentials.json` on your machine.

To revoke at any time: [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
