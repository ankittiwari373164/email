"""Elastic Email client — 100/day free tier."""
import os
import requests
import base64

ELASTIC_API_KEY = os.environ.get("ELASTIC_API_KEY", "")
ELASTIC_FROM = os.environ.get("ELASTIC_FROM", "")
ELASTIC_ENDPOINT = "https://api.elasticemail.com/v2/email/send"


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
    """Send via Elastic Email API. Returns (message_id, thread_id)."""
    if not ELASTIC_API_KEY or not ELASTIC_FROM:
        raise RuntimeError("Elastic Email not configured. Set ELASTIC_API_KEY and ELASTIC_FROM.")

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

    from_email = ELASTIC_FROM.split("<")[-1].strip(" <>") if "<" in ELASTIC_FROM else ELASTIC_FROM

    data = {
        "apikey": ELASTIC_API_KEY,
        "from": from_email,
        "to": to_addr,
        "subject": subject,
        "body": html_body or text_body,
        "isTransactional": False,
    }

    if html_body:
        data["bodyHtml"] = html_body
        data["bodyText"] = text_body

    if image_bytes and image_placement == "attachment":
        b64 = base64.b64encode(image_bytes).decode()
        # Elastic Email attachment handling via POST data
        data["attachmentBinary"] = b64
        data["attachmentName"] = image_filename or "image.png"

    try:
        resp = requests.post(ELASTIC_ENDPOINT, data=data, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"Elastic Email connection error: {e}")

    if resp.status_code >= 400:
        raise RuntimeError(f"Elastic Email API {resp.status_code}: {resp.text[:300]}")

    try:
        result = resp.json()
    except ValueError:
        raise RuntimeError(f"Elastic Email returned non-JSON: {resp.text[:200]}")

    # Elastic Email returns MessageID in response
    msg_id = result.get("messageid") or result.get("MessageID")
    return msg_id, None
