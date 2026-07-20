"""
Multi-provider email router with fixed domain mapping.

Each provider is assigned one domain. Sends rotate through providers only,
each always using its assigned domain.

Provider → Domain mapping:
  - Brevo     → BREVO_DOMAIN
  - Mailjet   → MAILJET_DOMAIN
  - SendGrid  → SENDGRID_DOMAIN
  - Mailgun   → MAILGUN_DOMAIN
  - Elastic   → ELASTIC_DOMAIN
  - Resend    → RESEND_DOMAIN

Tracks which provider/domain sent each email for monitoring.
"""
import os

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

# Track which provider sends next (rotation)
_provider_index = 0


def _get_next_provider():
    """Return next provider in rotation, with its domain."""
    global _provider_index
    if not PROVIDERS:
        raise RuntimeError("No providers configured")
    
    provider_name, provider_module = PROVIDERS[_provider_index % len(PROVIDERS)]
    domain = PROVIDER_DOMAINS.get(provider_name, "")
    
    _provider_index += 1
    
    return provider_name, provider_module, domain


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
        return msg_id, tid, provider_name, domain
    finally:
        # Restore original FROM
        if env_key and old_from is not None:
            os.environ[env_key] = old_from


def get_provider_stats():
    """Return provider info for logging/debugging."""
    stats = {
        "providers": [name for name, _ in PROVIDERS],
        "provider_domains": PROVIDER_DOMAINS,
        "next_provider_index": _provider_index,
    }
    return stats
