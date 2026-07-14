"""
Email verification, run on demand from the Leads page ("Verify" button /
"Verify all unverified") rather than automatically on every scrape, so you
control when the (slower) checks run.

Three layers, cheapest first:
  1. Syntax check (regex)
  2. MX check — does the domain have mail servers at all? (fast, reliable)
  3. Optional SMTP handshake (RCPT TO, no message actually sent) — only
     runs if config.VERIFY_SMTP_CHECK is true. Off by default because:
       - many hosts (Render, Vercel, most PaaS free tiers) block outbound
         port 25, so this will just time out/fail everywhere
       - big providers (Gmail, Outlook, Yahoo) accept-all at the RCPT
         stage and only bounce after actually accepting the message, so a
         "pass" here doesn't guarantee deliverability anyway
  Treat the result as: mx-valid = safe to attempt sending to; smtp-valid =
  extra confidence, not a guarantee.
"""
import re
import smtplib
import socket

import dns.resolver

import config

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

_mx_cache = {}


def _get_mx_host(domain):
    if domain in _mx_cache:
        return _mx_cache[domain]
    host = None
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        best = min(answers, key=lambda r: r.preference)
        host = str(best.exchange).rstrip(".")
    except Exception:
        host = None
    _mx_cache[domain] = host
    return host


def verify_email(email):
    """Returns dict: {status: 'valid'|'invalid'|'risky', reason: str, mx_valid: 0|1}"""
    email = (email or "").strip().lower()

    if not EMAIL_RE.match(email):
        return {"status": "invalid", "reason": "bad syntax", "mx_valid": 0}

    domain = email.split("@")[-1]
    mx_host = _get_mx_host(domain)
    if not mx_host:
        return {"status": "invalid", "reason": "no MX record for domain", "mx_valid": 0}

    if not config.VERIFY_SMTP_CHECK:
        return {"status": "valid", "reason": "syntax + MX ok (SMTP check disabled)", "mx_valid": 1}

    smtp_result = _smtp_check(mx_host, email)
    if smtp_result is True:
        return {"status": "valid", "reason": "syntax + MX + SMTP accepted", "mx_valid": 1}
    elif smtp_result is False:
        return {"status": "invalid", "reason": "SMTP server rejected recipient", "mx_valid": 1}
    else:
        # inconclusive (timeout, greylisting, accept-all server, blocked port 25, etc)
        return {"status": "risky", "reason": "MX ok, SMTP check inconclusive", "mx_valid": 1}


def _smtp_check(mx_host, email):
    """Returns True (accepted), False (rejected), or None (inconclusive)."""
    try:
        with smtplib.SMTP(mx_host, 25, timeout=config.VERIFY_SMTP_TIMEOUT) as smtp:
            smtp.ehlo_or_helo_if_needed()
            smtp.mail(config.VERIFY_FROM_ADDR)
            code, _ = smtp.rcpt(email)
            if code in (250, 251):
                return True
            if code in (550, 551, 553):
                return False
            return None
    except (socket.timeout, smtplib.SMTPException, OSError):
        return None


def verify_batch(emails):
    """Verify a list of emails, returns {email: result_dict}."""
    return {e: verify_email(e) for e in emails}