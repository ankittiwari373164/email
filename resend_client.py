"""
Resend email client — sends via the Resend HTTP API over HTTPS.

Why this instead of SMTP: Render's free tier blocks outbound SMTP ports
(465/587), so smtp.hostinger.com is unreachable there. Resend sends over
HTTPS (port 443), which Render allows. Same practical result — mail from
your authenticated manofox.com domain — just over an API instead of SMTP.

Configuration (set in Render's Environment tab):
  RESEND_API_KEY   your Resend API key (starts with 're_')
  RESEND_FROM      verified sender, e.g. "Manofox <info@manofox.com>"
                   (the domain must be verified in Resend first)

Exposes send_email(...) with the SAME signature the app calls on
gmail_client / smtp_client, so sender.py doesn't care which backend runs.
"""
import os
import base64
import requests

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM = os.environ.get("RESEND_FROM", "")
RESEND_ENDPOINT = "https://api.resend.com/emails"


def _looks_like_html(text):
    if not text:
        return False
    lowered = text.lstrip()[:200].lower()
    return lowered.startswith("<!doctype") or lowered.startswith("<html") or "<body" in text.lower()


def _html_to_plain(html):
    import re as _re
    import html as _html
    text = _re.sub(r"<(style|script)[^>]*>.*?</\1>", "", html, flags=_re.DOTALL | _re.IGNORECASE)
    text = _re.sub(r"<br\s*/?>", "\n", text, flags=_re.IGNORECASE)
    text = _re.sub(r"</(p|div|tr|h[1-6])>", "\n", text, flags=_re.IGNORECASE)
    text = _re.sub(r"<[^>]+>", "", text)
    text = _html.unescape(text)
    text = _re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def send_email(account, to_addr, subject, body_text, thread_id=None,
                in_reply_to=None, references=None,
                image_bytes=None, image_filename=None, image_mime=None,
                image_placement="attachment"):
    """Send via Resend's HTTP API. Returns (message_id, thread_id).

    thread_id is not meaningful for Resend, so None is returned for it.
    The `account` arg is accepted for interface compatibility; the actual
    sender identity comes from RESEND_FROM (your verified domain address).

    Images:
      - inline: embedded in the HTML via a data: URI
      - attachment (default): sent as a Resend attachment
    """
    if not RESEND_API_KEY or not RESEND_FROM:
        raise RuntimeError(
            "Resend not configured. Set RESEND_API_KEY and RESEND_FROM "
            "(e.g. 'Manofox <info@manofox.com>') in the environment, and "
            "verify your domain in the Resend dashboard first."
        )

    # Decide html vs text
    if _looks_like_html(body_text):
        html_body = body_text
        text_body = _html_to_plain(body_text)
    else:
        html_body = None
        text_body = body_text

    # Inline image: embed as data URI inside the HTML
    if image_bytes and image_placement == "inline":
        b64 = base64.b64encode(image_bytes).decode()
        mime = image_mime or "image/png"
        img_tag = f'<br><img src="data:{mime};base64,{b64}" style="max-width:100%">'
        if html_body:
            if "</body>" in html_body.lower():
                idx = html_body.lower().rindex("</body>")
                html_body = html_body[:idx] + img_tag + html_body[idx:]
            else:
                html_body = html_body + img_tag
        else:
            import html as _html
            html_body = ("<div style='white-space:pre-wrap'>" +
                         _html.escape(body_text).replace("\n", "<br>") + "</div>" + img_tag)

    payload = {
        "from": RESEND_FROM,
        "to": [to_addr],
        "subject": subject,
    }
    if html_body:
        payload["html"] = html_body
        payload["text"] = text_body   # plain-text fallback
    else:
        payload["text"] = text_body

    if in_reply_to:
        payload["headers"] = {
            "In-Reply-To": in_reply_to,
            "References": references or in_reply_to,
        }

    # Attachment image
    if image_bytes and image_placement != "inline":
        payload["attachments"] = [{
            "filename": image_filename or "image.png",
            "content": base64.b64encode(image_bytes).decode(),
        }]

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
        # requests sends its own User-Agent, which Cloudflare (fronting
        # Resend) accepts — unlike urllib's default, which triggers a 403
        # error 1010 bot block from datacenter IPs like Render's.
        "Accept": "application/json",
    }

    try:
        resp = requests.post(RESEND_ENDPOINT, json=payload, headers=headers, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"Resend connection error: {e}")

    if resp.status_code >= 400:
        # Surface the error body so it's diagnosable in last_error.
        raise RuntimeError(f"Resend API {resp.status_code}: {resp.text[:300]}")

    try:
        result = resp.json()
    except ValueError:
        raise RuntimeError(f"Resend returned non-JSON: {resp.text[:200]}")

    return result.get("id"), None
