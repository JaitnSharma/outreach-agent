"""
setup_gmail.py — one-shot OAuth setup. Run this once, then never again.

Turns the manual Google Cloud consent dance into a single command. You download
ONE file by hand (the OAuth client keys); this script does the rest and writes
the `credentials.json` that gmail.py reads.

    python setup_gmail.py path/to/gcp-oauth.keys.json

It opens your browser, catches the redirect on localhost, exchanges the code,
and saves the refresh token. See docs/gmail-setup.md for how to get the keys
file in the first place.

Stdlib only, like the rest of this repo. No google-auth, no oauthlib.
"""

import os
import sys
import json
import time
import socket
import argparse
import threading
import webbrowser
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

# Send-only. We never read the user's mailbox beyond our own threads, and
# gmail.readonly is implied by gmail.modify. Keep this list minimal: a broader
# scope makes the consent screen scarier and the token more dangerous if leaked.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
FALLBACK_TOKEN_URI = "https://oauth2.googleapis.com/token"
PROFILE_URI = "https://gmail.googleapis.com/gmail/v1/users/me/profile"

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"

_result = {}          # filled by the callback handler thread


class _CallbackHandler(BaseHTTPRequestHandler):
    """Catches Google's redirect so the user never copy-pastes a code."""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _result["code"] = (params.get("code") or [None])[0]
        _result["error"] = (params.get("error") or [None])[0]

        if _result["code"]:
            body = ("<h2>Authorised.</h2>"
                    "<p>You can close this tab and go back to the terminal.</p>")
        else:
            body = (f"<h2>Authorisation failed.</h2>"
                    f"<p>{_result.get('error') or 'No code returned.'}</p>")

        payload = f"<html><body style='font-family:sans-serif'>{body}</body></html>"
        payload = payload.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass          # keep the console clean


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _load_keys(path):
    with open(path, encoding="utf-8") as f:
        blob = json.load(f)
    # Desktop-app clients nest under "installed"; web clients under "web".
    # gmail.py only ever reads ["installed"], so refuse anything else here
    # rather than writing credentials that will fail later at send time.
    if "installed" not in blob:
        found = ", ".join(blob.keys()) or "nothing"
        raise SystemExit(
            f"{path} has no 'installed' key (found: {found}).\n"
            "  This must be an OAuth client of type DESKTOP APP.\n"
            "  A Web application client will not work here.\n"
            "  See docs/gmail-setup.md."
        )
    return blob["installed"]


def main():
    ap = argparse.ArgumentParser(
        description="One-shot Gmail OAuth setup. Writes credentials.json."
    )
    ap.add_argument("keys_path",
                    help="path to gcp-oauth.keys.json downloaded from Google Cloud")
    ap.add_argument("--out", default=None,
                    help="where to write credentials.json "
                         "(default: beside the keys file)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing credentials.json")
    args = ap.parse_args()

    keys_path = Path(args.keys_path).expanduser().resolve()
    if not keys_path.exists():
        raise SystemExit(f"No such file: {keys_path}\nSee docs/gmail-setup.md.")

    oauth = _load_keys(keys_path)
    out_path = Path(args.out).expanduser().resolve() if args.out \
        else keys_path.parent / "credentials.json"

    # A refresh token is long-lived and grants ongoing mailbox access. Silently
    # clobbering one that still works is not a mistake worth allowing by default.
    if out_path.exists() and not args.force:
        raise SystemExit(
            f"{out_path} already exists.\n"
            "  Pass --force to overwrite it, or --out to write elsewhere."
        )

    port = _free_port()
    redirect_uri = f"http://localhost:{port}"

    params = {
        "client_id": oauth["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        # BOTH of these matter. access_type=offline asks for a refresh token;
        # prompt=consent forces one to be re-issued even if this account has
        # authorised before. Without the pair, a repeat authorisation returns
        # only an access token and we would happily write a credentials.json
        # with no refresh_token in it, which fails hours later at send time.
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"{AUTH_URI}?{urllib.parse.urlencode(params)}"

    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    print("Opening your browser to authorise Gmail access.")
    print("If it does not open, paste this URL manually:\n")
    print(f"  {auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print(f"Waiting for the redirect on {redirect_uri} ...")
    deadline = time.time() + 300
    while not _result and time.time() < deadline:
        time.sleep(0.3)
    server.server_close()

    if not _result:
        raise SystemExit("Timed out after 5 minutes with no response.")
    if _result.get("error"):
        raise SystemExit(f"Google returned an error: {_result['error']}")
    code = _result.get("code")
    if not code:
        raise SystemExit("No authorisation code came back. Try again.")

    token_uri = oauth.get("token_uri", FALLBACK_TOKEN_URI)
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": oauth["client_id"],
        "client_secret": oauth["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()

    print("Exchanging the code for tokens ...")
    req = urllib.request.Request(token_uri, data=data, method="POST")
    try:
        payload = json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"Token exchange failed ({e.code}):\n  {e.read().decode()[:400]}"
        )

    if "refresh_token" not in payload:
        raise SystemExit(
            "Google did not return a refresh_token.\n"
            "  Revoke this app at https://myaccount.google.com/permissions\n"
            "  and run this script again."
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(out_path, 0o600)      # best-effort; a no-op on some filesystems
    except OSError:
        pass
    print(f"Wrote {out_path}")

    # Ask Google which mailbox was just authorised, rather than asking the human.
    # They picked the account in the consent screen thirty seconds ago; making
    # them type it again is a question with only one possible right answer.
    sender = _whoami(payload.get("access_token"))

    cfg = {
        "sender_email": sender or "PUT_YOUR_ADDRESS_HERE",
        "gmail_credentials_path": str(out_path).replace("\\", "/"),
        "gmail_oauth_keys_path": str(keys_path).replace("\\", "/"),
        # Placeholder addresses that always bounce. Nothing real gets contacted
        # until this is changed. See email_source.py.
        "email_source": "pseudo",
    }

    if CONFIG_PATH.exists() and not args.force:
        print(f"\n{CONFIG_PATH} already exists, leaving it alone.")
        print("Merge this in yourself, or re-run with --force:\n")
        print(json.dumps(cfg, indent=2))
    else:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {CONFIG_PATH}")
        if sender:
            print(f"\nSending as: {sender}")
        else:
            print("\nCould not read the address from Google. Open config.json "
                  "and set 'sender_email' by hand.")

    print("\nVerify:  python -c \"import gmail; print(bool(gmail.get_access_token()))\"")
    return 0


def _whoami(access_token):
    """The address that just authorised. None if the call fails — not fatal,
    the user can fill it in, and we say so rather than writing a wrong value."""
    if not access_token:
        return None
    req = urllib.request.Request(
        PROFILE_URI, headers={"Authorization": f"Bearer {access_token}"})
    try:
        return json.loads(urllib.request.urlopen(req).read()).get("emailAddress")
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
