"""Get the Leapsome bearer token from your everyday Chrome.

The Leapsome web app keeps its current token in the browser's localStorage. Chrome stores
localStorage as plain files on disk, so this reads the token from the Local Storage files of
whichever Chrome profile has it. It recognises the token by its contents and ignores JWTs
belonging to other sites. It does not touch cookies or the macOS Keychain, and it never starts a
browser.

The token only changes while a Leapsome tab is open (the page refreshes it about hourly). If the
newest token is about to expire, open https://www.leapsome.com in Chrome and try again.
"""
import glob
import os
import re
import subprocess
import time

from leapsome_api import LeapsomeError, jwt_claims

APP_URL = "https://www.leapsome.com/app/"
CHROME_DIR = os.path.expanduser("~/Library/Application Support/Google/Chrome")
MIN_LIFETIME = 300  # only accept tokens with at least this many seconds left
JWT = re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")


class CaptureError(Exception):
    pass


class NotLoggedIn(CaptureError):
    pass


def seconds_left(token):
    """Seconds until a JWT expires (0 if it can't be read)."""
    try:
        return jwt_claims(token)["exp"] - time.time()
    except (LeapsomeError, KeyError, TypeError):
        return 0


def is_leapsome_token(token):
    """Leapsome access tokens carry the user id and team role; other sites' JWTs don't."""
    try:
        claims = jwt_claims(token)
    except LeapsomeError:
        return False
    return isinstance(claims, dict) and "_id" in claims and isinstance(claims.get("teamRole"), dict)


def tokens_in_file(path):
    """Yield Leapsome access tokens found in one LevelDB file.

    Chrome compacts these files over time and stores keys in a shortened form, so the key name
    isn't always readable next to the value. Identify the token by what it is instead.
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return
    for found in JWT.finditer(data):
        token = found.group().decode()
        if is_leapsome_token(token):
            yield token


def latest_token():
    """Newest (longest-lived) Leapsome token across Chrome profiles, or None."""
    if not os.path.isdir(CHROME_DIR):
        raise CaptureError(f"Couldn't find Chrome's data folder at {CHROME_DIR}.")
    best, best_left = None, float("-inf")  # expired tokens still count, so we can say "expired"
    for path in glob.glob(os.path.join(CHROME_DIR, "*", "Local Storage", "leveldb", "*")):
        if not path.endswith((".log", ".ldb")):
            continue
        for token in tokens_in_file(path):
            left = seconds_left(token)
            if left > best_left:
                best, best_left = token, left
    return best


def get_token():
    """Return a bearer token with some life left (no 'Bearer ' prefix)."""
    token = latest_token()
    if token is None:
        raise NotLoggedIn(
            "No Leapsome token found in Chrome. Open https://www.leapsome.com in Chrome and log in, then try again."
        )
    if seconds_left(token) < MIN_LIFETIME:
        raise NotLoggedIn(
            "The token in Chrome has expired. Open https://www.leapsome.com in Chrome (it refreshes the token "
            "within a few seconds), then try again."
        )
    return token


def open_leapsome():
    """Open Leapsome in your Chrome (in the background) so the page refreshes its token."""
    try:
        subprocess.run(["open", "-g", "-a", "Google Chrome", APP_URL], check=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        raise CaptureError(f"Couldn't open Chrome: {e}")
