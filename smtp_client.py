"""
SMTP email client — sends via your own authenticated domain (Hostinger
or any SMTP host), instead of the Gmail API.

Why SMTP over the Gmail API for domain sending:
  - No OAuth, no client_secret.json, no token expiry to manage.
  - Sends from your real domain address (info@yourdomain.com), which —
    combined with SPF/DKIM/DMARC set up at your DNS host — is what
    actually keeps mail out of spam. Personal @gmail.com can't be
    domain-authenticated; a real domain over authenticated SMTP can.

Configuration comes from environment variables (set these in Render):
  SMTP_HOST      e.g. smtp.hostinger.com
  SMTP_PORT      465 (SSL) or 587 (STARTTLS)
  SMTP_USER      full mailbox address, e.g. info@yourdomain.com
  SMTP_PASSWORD  that mailbox's password
  SMTP_FROM_NAME optional display name, e.g. "Manofox"

This exposes send_email(...) with the SAME signature the rest of the
app already calls on gmail_client, so sender.py barely changes.
"""
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.utils import formataddr, make_msgid

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.hostinger.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "")


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


def _body_part(body_text):
    if _looks_like_html(body_text):
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(_html_to_plain(body_text), "plain", "utf-8"))
        alt.attach(MIMEText(body_text, "html", "utf-8"))
        return alt
    return MIMEText(body_text, "plain", "utf-8")


def send_email(account, to_addr, subject, body_text, thread_id=None,
                in_reply_to=None, references=None,
                image_bytes=None, image_filename=None, image_mime=None,
                image_placement="attachment"):
    """Send via SMTP. Returns (message_id, thread_id) to match the Gmail
    client's interface. thread_id is not meaningful over SMTP, so we
    return None for it; message_id is the RFC Message-ID we generate.

    The `account` arg is accepted for interface-compatibility but the
    actual sending identity comes from the SMTP_* env vars (your domain
    mailbox), NOT from the account row — since with a real domain you
    send from one authenticated address, not rotating Gmail logins.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        raise RuntimeError(
            "SMTP not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USER, "
            "SMTP_PASSWORD in the environment (your Hostinger mailbox)."
        )

    from_addr = SMTP_USER
    msg_id = make_msgid(domain=from_addr.split("@")[-1])

    # Build the message, with image handling matching the Gmail client.
    if image_bytes and image_placement == "inline":
        root = MIMEMultipart("related")
        alt = MIMEMultipart("alternative")
        root.attach(alt)
        img_tag = '<br><img src="cid:campaign_image" style="max-width:100%">'
        if _looks_like_html(body_text):
            plain = _html_to_plain(body_text)
            if "</body>" in body_text.lower():
                idx = body_text.lower().rindex("</body>")
                html_body = body_text[:idx] + img_tag + body_text[idx:]
            else:
                html_body = body_text + img_tag
        else:
            import html as _html
            plain = body_text
            html_body = ("<div style='white-space:pre-wrap'>" +
                         _html.escape(body_text).replace("\n", "<br>") + "</div>" + img_tag)
        alt.attach(MIMEText(plain, "plain", "utf-8"))
        alt.attach(MIMEText(html_body, "html", "utf-8"))
        subtype = (image_mime or "image/png").split("/")[-1]
        img = MIMEImage(image_bytes, _subtype=subtype)
        img.add_header("Content-ID", "<campaign_image>")
        img.add_header("Content-Disposition", "inline", filename=image_filename or "image")
        root.attach(img)
        msg = root
    elif image_bytes:
        root = MIMEMultipart("mixed")
        root.attach(_body_part(body_text))
        subtype = (image_mime or "image/png").split("/")[-1]
        img = MIMEImage(image_bytes, _subtype=subtype)
        img.add_header("Content-Disposition", "attachment", filename=image_filename or "image.png")
        root.attach(img)
        msg = root
    else:
        msg = _body_part(body_text)

    msg["From"] = formataddr((SMTP_FROM_NAME or account.get("display_name") or "", from_addr))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = msg_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to

    # Send
    if SMTP_PORT == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=30) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(from_addr, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(from_addr, [to_addr], msg.as_string())

    return msg_id, None
