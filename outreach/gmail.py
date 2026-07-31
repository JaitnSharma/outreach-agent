"""
gmail.py — shared Gmail API helpers for the outreach pipeline.

Direct REST via urllib. Stdlib only, no SDK, no MCP. Covers the OAuth
refresh-token flow, message sending, bounce detection and human-reply detection.

The sending identity and the credential file paths are NOT hardcoded here —
they come from config.py (env var, then config.json). Nothing in this file or
anywhere else in the repo identifies a real mailbox.
"""

import re
import json
import base64
import urllib.request
import urllib.parse
import urllib.error

from core import config


def sender_email():
    """The configured sending address. A FUNCTION, not a module constant, and
    it raises rather than defaulting.

    Why this matters: a module-level `OUR_EMAIL = config.get(..., "")` would
    make an unconfigured checkout import cleanly and then behave catastrophically
    at runtime, because `"" in sender` is True for EVERY sender. Reply detection
    would classify every human reply as our own message, return 0, and keep
    nudging people who had already answered. Failing loudly is the only safe
    behaviour here.
    """
    return config.require("sender_email")

API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me/"

_EMAIL_RE = r"[\w.+\-]+@[\w.\-]+"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def get_access_token():
    """Exchange the stored refresh token for a fresh access token.

    Credential paths come from config at call time, not import time, so an
    unconfigured checkout imports fine and only fails when it actually tries
    to send. Raises urllib.error.HTTPError on invalid_grant (see README).
    """
    with open(config.require("gmail_credentials_path")) as f:
        creds = json.load(f)
    with open(config.require("gmail_oauth_keys_path")) as f:
        oauth = json.load(f)["installed"]

    data = urllib.parse.urlencode({
        "client_id": oauth["client_id"],
        "client_secret": oauth["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(oauth["token_uri"], data=data, method="POST")
    return json.loads(urllib.request.urlopen(req).read())["access_token"]


# ---------------------------------------------------------------------------
# Low-level API
# ---------------------------------------------------------------------------

def api_get(token, path):
    req = urllib.request.Request(
        API_BASE + path, headers={"Authorization": f"Bearer {token}"}
    )
    return json.loads(urllib.request.urlopen(req).read())


def api_post(token, path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        API_BASE + path, data=data, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req).read())


def header(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def parse_emails(text):
    return [e.strip().lower() for e in re.findall(_EMAIL_RE, text)]


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def build_raw_message(to_list, subject, html_body):
    """multipart/alternative MIME (text + html), base64url-encoded.
    Same structure the existing skills use for drafts."""
    boundary = "alt_boundary_brace"
    raw = (
        f"From: {sender_email()}\r\n"
        f"To: {', '.join(to_list)}\r\n"
        f"Subject: {subject}\r\n"
        f"MIME-Version: 1.0\r\n"
        f'Content-Type: multipart/alternative; boundary="{boundary}"\r\n'
        f"\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: text/plain; charset=UTF-8\r\n"
        f"\r\n"
        f"Please view this email in an HTML-capable email client.\r\n"
        f"\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: text/html; charset=UTF-8\r\n"
        f"\r\n"
        f"{html_body}\r\n"
        f"\r\n"
        f"--{boundary}--\r\n"
    )
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def send_message(token, to_list, subject, html_body, thread_id=None):
    """Send via messages.send. NOTE: the Message resource is passed DIRECTLY
    ({"raw":..., "threadId":...}) — no outer "message" wrapper (that is only
    for drafts.create). Returns the sent Message resource (has id, threadId)."""
    message = {"raw": build_raw_message(to_list, subject, html_body)}
    if thread_id:
        message["threadId"] = thread_id
    return api_post(token, "messages/send", message)


# ---------------------------------------------------------------------------
# Thread inspection: replies and bounces
# ---------------------------------------------------------------------------

def is_daemon(sender):
    s = sender.lower()
    return "mailer-daemon" in s or "postmaster@" in s


def is_noreply(sender):
    """Senders no human ever replies from. Deliberately narrow: role addresses
    like hiring@ / careers@ are NOT here, because a real recruiter does reply
    from those."""
    return bool(re.search(r"(no[-_.]?reply|do[-_.]?not[-_.]?reply)@", sender.lower()))


def is_auto_reply(headers):
    """Machine-generated per RFC 3834 and the common de-facto headers.

    NOTE: this catches well-behaved autoresponders (Gmail vacation responder,
    most ATS and ticketing systems). It does NOT catch a plain message sent by
    a custom script, which is indistinguishable from a human reply at the
    header level. See README for the residual gap.
    """
    auto = header(headers, "Auto-Submitted").split(";")[0].strip().lower()
    if auto and auto != "no":
        return True
    if header(headers, "Precedence").strip().lower() in ("bulk", "auto_reply", "junk"):
        return True
    return any(header(headers, h).strip()
               for h in ("X-Autoreply", "X-Autorespond", "X-Auto-Response-Suppress"))


_REPLY_HEADERS = ("From", "Auto-Submitted", "Precedence", "X-Autoreply",
                  "X-Autorespond", "X-Auto-Response-Suppress")


def human_reply_count(token, thread_id):
    """Count messages in the thread from a real human (not us, not the
    mailer-daemon, not an autoresponder). >0 means someone replied and the
    sequence should stop."""
    qs = "&".join("metadataHeaders=" + h for h in _REPLY_HEADERS)
    thread = api_get(token, f"threads/{thread_id}?format=metadata&{qs}")
    ours = sender_email()          # raises if unconfigured; never matches "" here
    count = 0
    for m in thread.get("messages", []):
        headers = m.get("payload", {}).get("headers", [])
        sender = header(headers, "From")
        if ours in sender:
            continue
        if is_daemon(sender) or is_noreply(sender):
            continue
        if is_auto_reply(headers):
            continue
        count += 1
    return count


def _extract_body(part):
    body = ""
    data = part.get("body", {}).get("data")
    if data:
        try:
            body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        except Exception:
            body = ""
    for sub in part.get("parts", []):
        body += _extract_body(sub)
    return body


def get_bounced_addresses(token, thread_id):
    """Return the set of addresses that bounced within a thread. Checks the
    X-Failed-Recipients header, then falls back to Final-Recipient / plain
    'wasn't delivered to X' patterns in the daemon message body."""
    bounced = set()
    thread = api_get(token, f"threads/{thread_id}?format=full")
    for m in thread.get("messages", []):
        headers = m.get("payload", {}).get("headers", [])
        sender = header(headers, "From")
        if not is_daemon(sender):
            continue
        xfail = header(headers, "X-Failed-Recipients")
        if xfail:
            for addr in xfail.split(","):
                bounced.add(addr.strip().lower())
            continue
        body = _extract_body(m.get("payload", {}))
        for pattern in (
            r"Final-Recipient:\s*rfc822;\s*(" + _EMAIL_RE + r")",
            r"X-Failed-Recipients:\s*(" + _EMAIL_RE + r")",
            r"wasn't delivered to\s+(" + _EMAIL_RE + r")",
            r"couldn't be delivered to\s+(" + _EMAIL_RE + r")",
        ):
            for match in re.finditer(pattern, body, re.IGNORECASE):
                bounced.add(match.group(1).strip().lower())
    return bounced


def find_sent_message(token, to_addrs, subject, newer_than="2d"):
    """Reconciliation probe: did this message ACTUALLY go out?

    Called for sends left 'in_flight' by a process that died between the Gmail
    call and the DB write. Rather than guessing (which either duplicates the
    email or silently drops the person), we go and read Gmail's own record —
    the same move as reading the payment provider's records when your
    confirmation write fails.

    Returns the threadId if a matching message exists in Sent, else None.
    """
    want = (subject or "").strip().lower()
    want_bare = want[4:].strip() if want.startswith("re: ") else want
    for addr in to_addrs:
        q = urllib.parse.urlencode({
            "q": f"in:sent to:{addr} newer_than:{newer_than}",
            "maxResults": 25,
        })
        try:
            listing = api_get(token, f"messages?{q}")
        except Exception:
            continue
        for stub in listing.get("messages", []):
            try:
                msg = api_get(
                    token,
                    f"messages/{stub['id']}?format=metadata&metadataHeaders=Subject",
                )
            except Exception:
                continue
            subj = header(msg.get("payload", {}).get("headers", []),
                          "Subject").strip().lower()
            subj_bare = subj[4:].strip() if subj.startswith("re: ") else subj
            if subj_bare and subj_bare == want_bare:
                return msg.get("threadId")
    return None


def list_inbox_thread_ids(token, newer_than="7d", max_pages=10):
    """Every thread id that has INCOMING mail in the window.

    This is the cheap half of reply detection: cost scales with inbox volume,
    not with lead count. One list call covers 500 threads (10 quota units), so
    a 5,000-lead pipeline costs the same as a 100-lead one. The expensive
    alternative — asking Gmail about each lead's thread — grows linearly.

    mailer-daemon and postmaster are excluded at the query level: a BOUNCE also
    lands in the inbox on the original thread, so without this filter every
    bounced lead would look like it replied.
    """
    ids = set()
    page = None
    for _ in range(max_pages):
        params = {
            "q": (f"in:inbox newer_than:{newer_than} "
                  f"-from:mailer-daemon -from:postmaster"),
            "maxResults": 500,
        }
        if page:
            params["pageToken"] = page
        data = api_get(token, "threads?" + urllib.parse.urlencode(params))
        for t in data.get("threads", []):
            ids.add(t["id"])
        page = data.get("nextPageToken")
        if not page:
            break
    return ids


def search_daemon_bounces(token, newer_than="3d"):
    """Search the inbox for recent mailer-daemon messages and extract, per
    message, the failed recipient address(es). Returns a set of addresses.
    Each daemon mail typically names one address, so N bad addresses across a
    send arrive as N separate messages — this collects them all."""
    q = urllib.parse.urlencode({
        "q": f"from:mailer-daemon newer_than:{newer_than}",
        "maxResults": 200,
    })
    listing = api_get(token, f"messages?{q}")
    bad = set()
    for stub in listing.get("messages", []):
        msg = api_get(token, f"messages/{stub['id']}?format=full")
        headers = msg.get("payload", {}).get("headers", [])
        xfail = header(headers, "X-Failed-Recipients")
        if xfail:
            for addr in xfail.split(","):
                bad.add(addr.strip().lower())
            continue
        body = _extract_body(msg.get("payload", {}))
        for pattern in (
            r"Final-Recipient:\s*rfc822;\s*(" + _EMAIL_RE + r")",
            r"wasn't delivered to\s+(" + _EMAIL_RE + r")",
            r"couldn't be delivered to\s+(" + _EMAIL_RE + r")",
        ):
            for match in re.finditer(pattern, body, re.IGNORECASE):
                bad.add(match.group(1).strip().lower())
    return bad
