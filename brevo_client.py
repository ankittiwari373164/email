"""Brevo email client — 300/day free tier."""
import os
import requests
import base64

BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_FROM = os.environ.get("BREVO_FROM", "")
BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"


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
    """Send via Brevo API. Returns (message_id, thread_id)."""
    if not BREVO_API_KEY or not BREVO_FROM:
        raise RuntimeError("Brevo not configured. Set BREVO_API_KEY and BREVO_FROM.")

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

    payload = {
        "sender": {"name": "Manofox", "email": BREVO_FROM.split("<")[-1].strip(" <>") if "<" in BREVO_FROM else BREVO_FROM},
        "to": [{"email": to_addr}],
        "subject": subject,
    }
    if html_body:
        payload["htmlContent"] = html_body
    payload["textContent"] = text_body

    if image_bytes and image_placement == "attachment":
        b64 = base64.b64encode(image_bytes).decode()
        payload["attachment"] = [{
            "name": image_filename or "image.png",
            "content": b64,
        }]

    headers = {
        "api-key": BREVO_API_KEY,
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(BREVO_ENDPOINT, json=payload, headers=headers, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"Brevo connection error: {e}")

    if resp.status_code >= 400:
        raise RuntimeError(f"Brevo API {resp.status_code}: {resp.text[:300]}")

    try:
        result = resp.json()
    except ValueError:
        raise RuntimeError(f"Brevo returned non-JSON: {resp.text[:200]}")

    # Brevo returns messageId
    return result.get("messageId"), None
