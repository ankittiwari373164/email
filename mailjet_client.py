"""Mailjet email client — 200/day free tier."""
import os
import requests
import base64

MAILJET_API_KEY = os.environ.get("MAILJET_API_KEY", "")
MAILJET_SECRET_KEY = os.environ.get("MAILJET_SECRET_KEY", "")
MAILJET_FROM = os.environ.get("MAILJET_FROM", "")
MAILJET_ENDPOINT = "https://api.mailjet.com/v3.1/send"


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
    """Send via Mailjet API. Returns (message_id, thread_id)."""
    if not MAILJET_API_KEY or not MAILJET_SECRET_KEY or not MAILJET_FROM:
        raise RuntimeError("Mailjet not configured. Set MAILJET_API_KEY, MAILJET_SECRET_KEY, MAILJET_FROM.")

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

    from_email = MAILJET_FROM.split("<")[-1].strip(" <>") if "<" in MAILJET_FROM else MAILJET_FROM

    payload = {
        "Messages": [{
            "From": {"Email": from_email, "Name": "Manofox"},
            "To": [{"Email": to_addr}],
            "Subject": subject,
            "TextPart": text_body,
        }]
    }
    if html_body:
        payload["Messages"][0]["HTMLPart"] = html_body

    if image_bytes and image_placement == "attachment":
        b64 = base64.b64encode(image_bytes).decode()
        payload["Messages"][0]["Attachments"] = [{
            "ContentType": image_mime or "image/png",
            "Filename": image_filename or "image.png",
            "Base64Content": b64,
        }]

    auth = (MAILJET_API_KEY, MAILJET_SECRET_KEY)

    try:
        resp = requests.post(MAILJET_ENDPOINT, json=payload, auth=auth, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"Mailjet connection error: {e}")

    if resp.status_code >= 400:
        raise RuntimeError(f"Mailjet API {resp.status_code}: {resp.text[:300]}")

    try:
        result = resp.json()
    except ValueError:
        raise RuntimeError(f"Mailjet returned non-JSON: {resp.text[:200]}")

    msg_id = result.get("Messages", [{}])[0].get("ID") if result.get("Messages") else None
    return msg_id, None
                  
