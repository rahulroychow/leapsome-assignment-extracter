"""Thin client for the Leapsome endpoints behind the "responses to review" screen.

Every call takes a bearer token; get one with capture_token.get_token().
"""
import base64
import json
import re
import urllib.error
import urllib.request
from html import unescape

DOWNLOAD_URL = "https://www.leapsome.com/api/learning/storage/s3/download/open-ended-question-response"
APPROVAL_URL = "https://www.leapsome.com/api/learning/responses/openEndedQuestion/approval"
RESPONSES_URL = "https://www.leapsome.com/api/learning/responses/openEndedQuestion"


class LeapsomeError(Exception):
    pass


def html_to_text(html):
    return unescape(re.sub(r"<[^>]+>", "", html or "")).strip()


def jwt_claims(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        raise LeapsomeError("The token doesn't look like a valid JWT.")


def build_headers(token):
    # The API also expects user/tenant id headers; both are claims in the JWT.
    claims = jwt_claims(token)
    try:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Referer": "https://www.leapsome.com/app/",
            "User-Agent": "Mozilla/5.0",
            "x-leapsome-user-id": claims["_id"],
            "x-leapsome-tenant-id": claims["teamRole"]["team"],
        }
    except KeyError as e:
        raise LeapsomeError(f"Token is missing the {e} claim.")


def send(req):
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise LeapsomeError(f"HTTP {e.code}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        raise LeapsomeError(f"Request failed: {e.reason}")
    # Some endpoints (e.g. approval) succeed with an empty body.
    return json.loads(body) if body.strip() else None


def fetch_open_ended_responses(token, filters=None):
    """POST /learning/responses/openEndedQuestion; returns the parsed JSON body."""
    body = json.dumps({"filters": filters or {}}).encode()
    headers = {**build_headers(token), "Content-Type": "application/json"}
    return send(urllib.request.Request(RESPONSES_URL, data=body, headers=headers, method="POST"))


def approve_responses(token, response_ids):
    """POST .../approval: approve open-ended responses. Changes data in Leapsome. Returns None (empty body) on success."""
    body = json.dumps({"responsesIds": list(response_ids), "isApproved": True}).encode()
    headers = {**build_headers(token), "Content-Type": "application/json"}
    return send(urllib.request.Request(APPROVAL_URL, data=body, headers=headers, method="POST"))


def download_attachment(token, response_id, file):
    """Resolve a response attachment to a signed S3 URL, then download it. Returns bytes."""
    body = json.dumps(
        {
            "httpMethodType": "post",
            "learningOpenEndedQuestionResponseId": response_id,
            "key": file["key"],
            "mimeType": file.get("mimeType"),
        }
    ).encode()
    headers = {**build_headers(token), "Content-Type": "application/json"}
    url = send(urllib.request.Request(DOWNLOAD_URL, data=body, headers=headers, method="POST"))["data"]["url"]
    # The signed URL carries its own credentials; don't send the bearer token to S3.
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise LeapsomeError(f"Attachment download failed: HTTP {e.code}")
    except urllib.error.URLError as e:
        raise LeapsomeError(f"Attachment download failed: {e.reason}")
