"""Mailgun email client — 100/day free tier."""
import os
import requests
import base64

MAILGUN_API_KEY = os.environ.get("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.environ.get("MAILGUN_DOMAIN", "")
MAILGUN_FROM = os.environ.get("MAILGUN_FROM", "")


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
    """Send via Mailgun API. Returns (message_id, thread_id)."""
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN or not MAILGUN_FROM:
        raise RuntimeError("Mailgun not configured. Set MAILGUN_API_KEY, MAILGUN_DOMAIN, MAILGUN_FROM.")

    if _looks_like_html(body_text):
        html_body = body_text
        text_body = _html_to_plain(body_text)
    else:
        html_body = None
        text_body = body_text

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

    endpoint = f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages"

    data = {
        "from": MAILGUN_FROM,
        "to": to_addr,
        "subject": subject,
        "text": text_body,
    }
    if html_body:
        data["html"] = html_body

    if image_bytes and image_placement == "attachment":
        files = {
            "attachment": (image_filename or "image.png", image_bytes, image_mime or "image/png")
        }
    else:
        files = None

    auth = ("api", MAILGUN_API_KEY)

    try:
        resp = requests.post(endpoint, data=data, files=files, auth=auth, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"Mailgun connection error: {e}")

    if resp.status_code >= 400:
        raise RuntimeError(f"Mailgun API {resp.status_code}: {resp.text[:300]}")

    try:
        result = resp.json()
    except ValueError:
        raise RuntimeError(f"Mailgun returned non-JSON: {resp.text[:200]}")

    msg_id = result.get("id")
    return msg_id, None
