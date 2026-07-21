"""
Multi-provider email router with fixed domain mapping and per-provider daily limits.

Each provider is assigned one domain and has its own daily send limit.
Sends rotate through providers, respecting each provider's free tier limit.

Provider → Domain → Daily Limit mapping:
  - Brevo     → BREVO_DOMAIN → 300/day
  - Mailjet   → MAILJET_DOMAIN → 200/day
  - SendGrid  → SENDGRID_DOMAIN → 100/day
  - Mailgun   → MAILGUN_DOMAIN → 100/day
  - Elastic   → ELASTIC_DOMAIN → 100/day
  - Resend    → RESEND_DOMAIN → 100/day

Tracks sends per provider and blocks when daily limit reached.
"""
import os
import sys
from datetime import datetime

# Import all provider clients
import brevo_client
import mailjet_client
import sendgrid_client
import mailgun_client
import elasticemail_client
import resend_client

PROVIDERS = [
    ("brevo", brevo_client),
    ("mailjet", mailjet_client),
    ("sendgrid", sendgrid_client),
    ("mailgun", mailgun_client),
    ("elasticemail", elasticemail_client),
    ("resend", resend_client),
]

# Provider → Domain mapping (from env vars)
PROVIDER_DOMAINS = {
    "brevo": os.environ.get("BREVO_DOMAIN", ""),
    "mailjet": os.environ.get("MAILJET_DOMAIN", ""),
    "sendgrid": os.environ.get("SENDGRID_DOMAIN", ""),
    "mailgun": os.environ.get("MAILGUN_DOMAIN", ""),
    "elasticemail": os.environ.get("ELASTIC_DOMAIN", ""),
    "resend": os.environ.get("RESEND_DOMAIN", ""),
}

# Provider → Daily limit (free tier)
PROVIDER_DAILY_LIMITS = {
    "brevo": 300,
    "mailjet": 200,
    "sendgrid": 100,
    "mailgun": 100,
    "elasticemail": 100,
    "resend": 100,
}

# Track sends per provider per day: {provider_name: {date: count}}
_provider_send_counts = {p[0]: {} for p in PROVIDERS}

# Track which provider sends next (rotation)
_provider_index = 0


def _get_today_date():
    """Get today's date as YYYY-MM-DD for tracking."""
    return datetime.utcnow().strftime("%Y-%m-%d")


def _increment_provider_count(provider_name):
    """Increment send count for provider today."""
    today = _get_today_date()
    if today not in _provider_send_counts[provider_name]:
        _provider_send_counts[provider_name][today] = 0
    _provider_send_counts[provider_name][today] += 1


def _get_provider_count(provider_name):
    """Get send count for provider today."""
    today = _get_today_date()
    return _provider_send_counts[provider_name].get(today, 0)


def _has_capacity(provider_name):
    """Check if provider still has capacity for today."""
    count = _get_provider_count(provider_name)
    limit = PROVIDER_DAILY_LIMITS.get(provider_name, 100)
    return count < limit


def _get_next_provider():
    """Return next provider in rotation that has capacity, with its domain."""
    global _provider_index
    if not PROVIDERS:
        raise RuntimeError("No providers configured")
    
    # Find the next provider with available capacity
    attempts = 0
    while attempts < len(PROVIDERS):
        provider_name, provider_module = PROVIDERS[_provider_index % len(PROVIDERS)]
        _provider_index += 1
        attempts += 1
        
        # Check if this provider has capacity
        if _has_capacity(provider_name):
            domain = PROVIDER_DOMAINS.get(provider_name, "")
            return provider_name, provider_module, domain
    
    # All providers hit their daily limit
    raise RuntimeError("All providers have reached their daily send limits")


def send_email(account, to_addr, subject, body_text, thread_id=None,
                in_reply_to=None, references=None,
                image_bytes=None, image_filename=None, image_mime=None,
                image_placement="attachment"):
    """
    Send via the next provider in rotation.
    Each provider uses its fixed assigned domain.
    Returns (message_id, thread_id, provider, domain).
    """
    provider_name, provider_module, domain = _get_next_provider()
    
    if not domain:
        raise RuntimeError(
            f"Domain not configured for {provider_name}. "
            f"Set {provider_name.upper()}_DOMAIN in environment."
        )

    # Override the provider's FROM env var to use the assigned domain
    old_from = None
    env_key = None
    
    if provider_name == "brevo":
        env_key = "BREVO_FROM"
    elif provider_name == "mailjet":
        env_key = "MAILJET_FROM"
    elif provider_name == "sendgrid":
        env_key = "SENDGRID_FROM"
    elif provider_name == "mailgun":
        env_key = "MAILGUN_FROM"
    elif provider_name == "elasticemail":
        env_key = "ELASTIC_FROM"
    elif provider_name == "resend":
        env_key = "RESEND_FROM"
    
    if env_key:
        old_from = os.environ.get(env_key)
        os.environ[env_key] = f"Manofox <info@{domain}>"

    try:
        print(f"[DEBUG] Sending via {provider_name} from info@{domain} to {to_addr} (capacity: {_get_provider_count(provider_name)}/{PROVIDER_DAILY_LIMITS[provider_name]})", file=sys.stderr)
        msg_id, tid = provider_module.send_email(
            account, to_addr, subject, body_text,
            thread_id=thread_id,
            in_reply_to=in_reply_to,
            references=references,
            image_bytes=image_bytes,
            image_filename=image_filename,
            image_mime=image_mime,
            image_placement=image_placement,
        )
        _increment_provider_count(provider_name)
        count = _get_provider_count(provider_name)
        print(f"[DEBUG] SUCCESS: {provider_name} sent message {msg_id} ({count}/{PROVIDER_DAILY_LIMITS[provider_name]} today)", file=sys.stderr)
        return msg_id, tid, provider_name, domain
    except Exception as e:
        print(f"[ERROR] {provider_name} failed: {str(e)}", file=sys.stderr)
        raise
    finally:
        # Restore original FROM
        if env_key and old_from is not None:
            os.environ[env_key] = old_from


def get_provider_stats():
    """Return provider info including daily send counts."""
    today = _get_today_date()
    stats = {
        "providers": [name for name, _ in PROVIDERS],
        "provider_domains": PROVIDER_DOMAINS,
        "provider_daily_limits": PROVIDER_DAILY_LIMITS,
        "today": today,
        "provider_counts": {
            name: _get_provider_count(name) for name, _ in PROVIDERS
        },
        "next_provider_index": _provider_index,
    }
    return stats
