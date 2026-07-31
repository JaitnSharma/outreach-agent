# Gmail setup

You only need this to **send** email. The pipeline is fully explorable without
it — see "Try it in two minutes" in the README.

Two files are involved:

| File | What it is | Where it comes from |
|---|---|---|
| `gcp-oauth.keys.json` | Your OAuth client (client id + secret) | You download it from Google Cloud, once |
| `credentials.json` | Your refresh token | `setup_gmail.py` writes it for you |

Neither belongs in this repo. Keep them outside the project directory and point
`config.json` at them by path.

---

## 1. Create an OAuth client (about 5 minutes, once)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create
   a project, or pick an existing one.
2. **Enable the Gmail API**: APIs & Services → Library → search "Gmail API" →
   Enable.
3. **Configure the consent screen**: APIs & Services → OAuth consent screen.
   Choose **External**, give it any app name, and add your own Google account
   under **Test users**. You do not need to submit anything for verification.
4. **Create the client**: APIs & Services → Credentials → Create Credentials →
   OAuth client ID → Application type **Desktop app**.

   This type matters. A "Web application" client produces a JSON file with a
   `web` key instead of `installed`, and this codebase reads `installed`.
   `setup_gmail.py` will catch that and tell you, but it is easier to pick the
   right one now.
5. Download the JSON. Save it somewhere outside this repo, e.g.
   `C:/Users/you/.outreach/gcp-oauth.keys.json`.

## 2. Get your refresh token (one command)

```bash
python setup_gmail.py C:/Users/you/.outreach/gcp-oauth.keys.json
```

It opens your browser, you approve access, and it writes `credentials.json`
next to the keys file. Google will warn that the app is unverified — that is
expected for a personal OAuth client. Click through via "Advanced".

The script prints the exact `config.json` to copy when it finishes.

## 3. Point config at it

```json
{
  "sender_email": "you@yourdomain.com",
  "gmail_credentials_path": "C:/Users/you/.outreach/credentials.json",
  "gmail_oauth_keys_path": "C:/Users/you/.outreach/gcp-oauth.keys.json"
}
```

Use forward slashes, or double the backslashes. A single backslash is not valid
JSON — the loader will tell you so explicitly rather than pretending the key is
missing.

Verify:

```bash
python -c "import gmail; print(gmail.sender_email())"
python -c "import gmail; print(bool(gmail.get_access_token()))"
```

The second one proves the whole chain works: config resolves, both files parse,
and Google accepts the refresh token.

---

## Troubleshooting

**`invalid_grant` after about a week.** This is the one that will confuse you.
While the consent screen is in **Testing** mode, Google expires refresh tokens
roughly every 7 days. The pipeline goes quiet with no obvious cause.

Fix it permanently: OAuth consent screen → **Publish App**. You do not need
verification for personal use with a small scope set. Or just re-run
`setup_gmail.py` when it happens.

**"Google did not return a refresh_token."** You have authorised this client
before, and Google only issues a refresh token on first consent. `setup_gmail.py`
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
