"""
Thin wrapper around the Gmail API: OAuth flow per account, sending
messages, and listing/reading messages for reply-tracking.

Tokens are stored in Supabase (accounts.token_json), not local files —
Render/Vercel wipe the local filesystem on every deploy/restart, so a
file-based token would silently disconnect every account on your next
deploy. client_secret.json (the one shared OAuth *app* credential, not
per-account) can still be a file — see DEPLOY.md for how to get that onto
Render via a Secret File.
"""
import json
import base64
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

import config
import db


def build_flow(state=None):
    return Flow.from_client_secrets_file(
        config.CLIENT_SECRET_FILE,
        scopes=config.GMAIL_SCOPES,
        state=state,
        redirect_uri=config.OAUTH_REDIRECT_URI,
    )


def get_authorization_url():
    flow = build_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # forces refresh_token to be issued every time
    )
    return auth_url, state


def exchange_code_for_token(state, authorization_response_url):
    flow = build_flow(state=state)
    flow.fetch_token(authorization_response=authorization_response_url)
    return flow.credentials


def save_credentials(creds, email):
    """Returns the token JSON string — caller (app.py) hands this straight
    to db.add_or_update_account, which stores it in Supabase."""
    return creds.to_json()


def _load_credentials_from_json(token_json):
    return Credentials.from_authorized_user_info(json.loads(token_json), config.GMAIL_SCOPES)


def get_service(account):
    """account: full account dict from db.list_accounts()/get_account_with_capacity()
    (needs 'id' and 'token_json'). Refreshes the token if expired and
    writes the refreshed token straight back to Supabase."""
    token_json = account.get("token_json")
    if not token_json:
        raise RuntimeError(f"No stored credentials for {account.get('email')}. Reconnect this account.")

    creds = _load_credentials_from_json(token_json)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        db.update_account_token(account["id"], creds.to_json())

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def get_profile_email(creds):
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    return profile["emailAddress"]


def _looks_like_html(text):
    """True if the body is already HTML (from the template builder) rather
    than plain typed text. If so we must send it as text/html or the
    recipient sees raw <html> source instead of a formatted email."""
    if not text:
        return False
    lowered = text.lstrip()[:200].lower()
    return lowered.startswith("<!doctype") or lowered.startswith("<html") or "<body" in text.lower()


def _html_to_plain(html):
    """Rough plain-text fallback for HTML emails, shown by clients that
    block HTML. Strips tags; not pretty, just readable."""
    import re as _re
    import html as _html
    # drop style/script blocks entirely
    text = _re.sub(r"<(style|script)[^>]*>.*?</\1>", "", html, flags=_re.DOTALL | _re.IGNORECASE)
    text = _re.sub(r"<br\s*/?>", "\n", text, flags=_re.IGNORECASE)
    text = _re.sub(r"</(p|div|tr|h[1-6])>", "\n", text, flags=_re.IGNORECASE)
    text = _re.sub(r"<[^>]+>", "", text)          # remaining tags
    text = _html.unescape(text)
    text = _re.sub(r"\n\s*\n\s*\n+", "\n\n", text)  # collapse blank lines
    return text.strip()


def _make_body_part(body_text):
    """Return a MIME part for the body — text/html if it's HTML,
    otherwise text/plain. For HTML, wraps in a multipart/alternative
    with a plain-text fallback."""
    if _looks_like_html(body_text):
        from email.mime.multipart import MIMEMultipart
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(_html_to_plain(body_text), "plain", "utf-8"))
        alt.attach(MIMEText(body_text, "html", "utf-8"))
        return alt
    return MIMEText(body_text, "plain", "utf-8")


def send_email(account, to_addr, subject, body_text, thread_id=None,
                in_reply_to=None, references=None,
                image_bytes=None, image_filename=None, image_mime=None, image_placement="attachment"):
    """Send an email via Gmail API. Returns (message_id, thread_id).

    The body is auto-detected: if it's HTML (from the template builder)
    it's sent as text/html with a plain-text fallback; otherwise as
    plain text. This is what makes template emails render as a formatted
    email instead of showing raw <html> source.

    If image_bytes is given:
      - image_placement='inline'     -> shown in the email body itself
      - image_placement='attachment' (default) -> image as a file attachment
    """
    service = get_service(account)

    if image_bytes and image_placement == "inline":
        mime_msg = _build_inline_image_message(to_addr, subject, body_text,
                                                image_bytes, image_filename, image_mime)
    elif image_bytes:
        mime_msg = _build_attachment_message(to_addr, subject, body_text,
                                              image_bytes, image_filename, image_mime)
    else:
        body_part = _make_body_part(body_text)
        if body_part.get_content_maintype() == "multipart":
            # already a multipart/alternative; use it directly as the message
            mime_msg = body_part
        else:
            mime_msg = body_part
        mime_msg["to"] = to_addr
        mime_msg["subject"] = subject

    if in_reply_to:
        mime_msg["In-Reply-To"] = in_reply_to
        mime_msg["References"] = references or in_reply_to

    raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
    body = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id

    sent = service.users().messages().send(userId="me", body=body).execute()
    return sent["id"], sent.get("threadId")


def _text_to_html(text):
    import html as _html
    escaped = _html.escape(text)
    return "<div style='white-space:pre-wrap;font-family:sans-serif'>" + escaped.replace("\n", "<br>") + "</div>"


def _build_inline_image_message(to_addr, subject, body_text, image_bytes, image_filename, image_mime):
    from email.mime.multipart import MIMEMultipart
    from email.mime.image import MIMEImage

    msg = MIMEMultipart("related")
    msg["to"] = to_addr
    msg["subject"] = subject

    alt = MIMEMultipart("alternative")
    msg.attach(alt)

    img_tag = '<br><img src="cid:campaign_image" style="max-width:100%">'
    if _looks_like_html(body_text):
        # Body is already HTML from the template builder — inject the
        # image before </body> (or append) instead of escaping it.
        plain_fallback = _html_to_plain(body_text)
        if "</body>" in body_text.lower():
            idx = body_text.lower().rindex("</body>")
            html_body = body_text[:idx] + img_tag + body_text[idx:]
        else:
            html_body = body_text + img_tag
    else:
        plain_fallback = body_text
        html_body = _text_to_html(body_text) + img_tag

    alt.attach(MIMEText(plain_fallback, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))

    subtype = (image_mime or "image/png").split("/")[-1]
    img_part = MIMEImage(image_bytes, _subtype=subtype)
    img_part.add_header("Content-ID", "<campaign_image>")
    img_part.add_header("Content-Disposition", "inline", filename=image_filename or "image")
    msg.attach(img_part)

    return msg


def _build_attachment_message(to_addr, subject, body_text, image_bytes, image_filename, image_mime):
    from email.mime.multipart import MIMEMultipart
    from email.mime.image import MIMEImage

    msg = MIMEMultipart("mixed")
    msg["to"] = to_addr
    msg["subject"] = subject
    # Send HTML as text/html (with plain fallback) when the body is HTML,
    # otherwise plain text — same auto-detection as the no-image path.
    msg.attach(_make_body_part(body_text))

    subtype = (image_mime or "image/png").split("/")[-1]
    img_part = MIMEImage(image_bytes, _subtype=subtype)
    img_part.add_header("Content-Disposition", "attachment", filename=image_filename or "image.png")
    msg.attach(img_part)

    return msg


def list_recent_message_ids(account, query="in:inbox newer_than:7d", max_results=50):
    service = get_service(account)
    result = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    return [m["id"] for m in result.get("messages", [])]


def get_message(account, message_id):
    service = get_service(account)
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    return _parse_message(msg)


def _parse_message(msg):
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    body_text = _extract_body(msg["payload"])
    return {
        "id": msg["id"],
        "thread_id": msg["threadId"],
        "subject": headers.get("subject", ""),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "snippet": msg.get("snippet", ""),
        "body": body_text,
        "internal_date": msg.get("internalDate"),
    }


def _extract_body(payload):
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
    for part in payload.get("parts", []) or []:
        text = _extract_body(part)
        if text:
            return text
    return ""
