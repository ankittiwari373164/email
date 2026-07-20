"""
Sends outreach emails: pulls 'new' leads matching a campaign's filters,
rotates across the connected Gmail accounts respecting each account's daily
cap, personalizes the template, appends a compliant footer + unsubscribe
link, and logs everything to messages/leads tables.

IMPORTANT FIX vs the original version: a failure sending to ONE lead (bad
address, mailbox full, etc) used to mark the whole Gmail ACCOUNT as
status='error', which made it invisible to every future send attempt —
that's why a batch would silently stop partway through (e.g. 14 of 62) even
though nothing was actually wrong with the account. Now:
  - lead-level failures (invalid recipient, quota-ish per-message errors)
    mark just that LEAD as 'bounced' and the loop keeps going on the same
    account.
  - only account-level failures (expired/revoked OAuth token, account
    fully out of send quota) mark the ACCOUNT as 'error' and move on to
    the next account.
"""
import re
import time
from datetime import datetime

import config
import db
import multi_provider
import os

# Multi-provider mode: rotates across 6 providers + 10 domains
_mailer = multi_provider

# Substrings in a Gmail API error that indicate the ACCOUNT itself is the
# problem (auth broke, whole-account quota), vs. a one-off per-recipient
# failure. Checked case-insensitively against the exception message.
ACCOUNT_LEVEL_ERROR_MARKERS = (
    "invalid_grant", "invalid credentials", "unauthorized", "insufficient",
    "daily user sending limit exceeded", "user-rate limit exceeded",
    "account has been temporarily disabled", "reconnect this account",
)


def render_template(template, lead):
    return template.format(
        business_name=lead.get("business_name") or "there",
        city=lead.get("city") or "",
        category=lead.get("category") or "",
        email=lead.get("email") or "",
    )


def _append_unsubscribe(body, lead_id):
    """Append a minimal, unobtrusive unsubscribe line at the very bottom.
    Required for bulk sending (Gmail sender guidelines + anti-spam law)
    and a strong deliverability signal. Detects HTML vs plain body so it
    injects correctly either way."""
    unsub_url = f"{config.PUBLIC_BASE_URL}/unsubscribe/{lead_id}"
    lowered = (body or "").lower()
    is_html = lowered.lstrip().startswith(("<!doctype", "<html")) or "<body" in lowered

    if is_html:
        footer = (
            '<div style="text-align:center;color:#9aa4b2;font-size:11px;'
            'line-height:1.6;padding:16px 10px;font-family:sans-serif;">'
            f'If you\'d prefer not to receive these emails, you can '
            f'<a href="{unsub_url}" style="color:#9aa4b2;text-decoration:underline;">unsubscribe here</a>.'
            '</div>'
        )
        if "</body>" in lowered:
            idx = lowered.rindex("</body>")
            return body[:idx] + footer + body[idx:]
        return body + footer
    else:
        return body + f"\n\n---\nIf you'd prefer not to receive these emails, unsubscribe: {unsub_url}"


def _is_valid_email(email):
    """Reject malformed addresses (e.g. double-@ like foo@gmail.com@gmail.com
    from a bad scrape) before handing them to the mail API, which would
    otherwise 4xx/403 the whole send."""
    if not email:
        return False
    # exactly one @, non-empty local + domain, domain has a dot, no spaces
    if email.count("@") != 1:
        return False
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain or " " in email:
        return False
    return True


def send_one(lead, account, campaign, sender_name=None):
    subject = render_template(campaign["subject_template"], lead)
    full_body = render_template(campaign["body_template"], lead)
    # Append a minimal unsubscribe footer at the very bottom — required
    # for bulk sending and important for staying out of spam.
    full_body = _append_unsubscribe(full_body, lead["id"])

    image_bytes = None
    if campaign.get("image_base64"):
        import base64
        image_bytes = base64.b64decode(campaign["image_base64"])

    result = _mailer.send_email(
        account, lead["email"], subject, full_body,
        image_bytes=image_bytes,
        image_filename=campaign.get("image_filename"),
        image_mime=campaign.get("image_mime"),
        image_placement=campaign.get("image_placement") or "attachment",
    )
    
    # Multi-provider returns (msg_id, thread_id, provider, domain)
    if len(result) == 4:
        message_id, thread_id, provider, domain = result
    else:
        message_id, thread_id = result
        provider, domain = "unknown", "unknown"

    db.log_message(
        lead_id=lead["id"], account_id=account["id"], campaign_id=campaign["id"],
        gmail_message_id=message_id, thread_id=thread_id, direction="sent",
        subject=subject, snippet=full_body[:200], body=full_body,
        from_addr=account["email"], to_addr=lead["email"],
    )
    # Store provider/domain info in the message log as notes or extended field
    # For now, we'll add it to the snippet so you can see it in logs
    db.update_lead_after_send(lead["id"], f"{account['email']} via {provider}@{domain}", thread_id)
    db.increment_sent_count(account["id"])
    return message_id, thread_id


def _is_account_level_error(error_message):
    msg = (error_message or "").lower()
    return any(marker in msg for marker in ACCOUNT_LEVEL_ERROR_MARKERS)


RETRY_AFTER_RE = re.compile(r"Retry after (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)")


def _extract_retry_after(error_message):
    """Gmail's 429 rate-limit errors include an explicit expiry, e.g.
    'Retry after 2026-07-16T00:34:55.867Z (Mail sending)'. If we can
    parse it, the account auto-recovers at that exact time instead of
    needing a manual Reactivate click. Returns None if not found/
    unparseable — caller falls back to requiring manual reactivation."""
    if not error_message:
        return None
    match = RETRY_AFTER_RE.search(error_message)
    if not match:
        return None
    try:
        ts = match.group(1)
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).replace(tzinfo=None)
    except ValueError:
        return None


def run_campaign(campaign_id, max_sends=None):
    """Send a batch of emails for a campaign. Call this repeatedly (manually
    via 'Send 50', or automatically via scheduler.py) — it stops naturally
    once max_sends is hit or every account is out of capacity."""
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        raise ValueError("Campaign not found")

    sent_count = 0
    failed_account_ids = set()  # avoid retrying an account we just errored on, this cycle

    while True:
        if max_sends is not None and sent_count >= max_sends:
            break

        account = db.get_account_with_capacity()
        if not account or account["id"] in failed_account_ids:
            # try the next-best account excluding ones that already failed this cycle
            candidates = [a for a in db.list_accounts()
                          if a["status"] == "active" and a["sent_today"] < a["daily_limit"]
                          and a["id"] not in failed_account_ids]
            account = candidates[0] if candidates else None
        if not account:
            break  # every account is either capped or errored this cycle

        leads = db.list_leads(
            status="new",
            category=campaign["category_filter"] or None,
            city=campaign["city_filter"] or None,
            limit=5,
        )
        leads = [l for l in leads if not l.get("unsubscribed") and l.get("mx_valid")
                 and l.get("verify_status") != "invalid"
                 and _is_valid_email(l.get("email"))]
        if not leads:
            break

        lead = leads[0]
        try:
            send_one(lead, account, campaign)
            sent_count += 1
        except Exception as e:
            err = str(e)
            # Log to stdout (shows up in Render logs) — this was silently
            # swallowed before, which is why the last batch of "bounces"
            # had no visible cause anywhere.
            print(f"[sender] Send failed for lead {lead['id']} ({lead['email']}) "
                  f"via account {account['email']}: {err}", flush=True)

            if _is_account_level_error(err):
                cooldown_until = _extract_retry_after(err)
                db.set_account_error(account["id"], err, cooldown_until=cooldown_until)
                failed_account_ids.add(account["id"])
                # leave the lead as 'new' so it's retried on a different account
            else:
                db.mark_lead_bounced(lead["id"], err)
            continue

        time.sleep(config.SEND_PACING_SECONDS)

    return sent_count


def run_all_running_campaigns(batch_size=None):
    """Called by the scheduler for full automation: sends a bounded batch
    for every campaign currently marked 'running'."""
    batch_size = batch_size or config.AUTO_SEND_BATCH_SIZE
    total = 0
    for campaign in db.list_running_campaigns():
        try:
            total += run_campaign(campaign["id"], max_sends=batch_size)
        except Exception:
            continue
    return total
