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
import time
from datetime import datetime

import config
import db
import gmail_client

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


def build_unsubscribe_link(lead_id):
    return f"{config.PUBLIC_BASE_URL}/unsubscribe/{lead_id}"


def send_one(lead, account, campaign, sender_name=None):
    subject = render_template(campaign["subject_template"], lead)
    body = render_template(campaign["body_template"], lead)
    footer = config.EMAIL_FOOTER_TEMPLATE.format(
        sender_name=sender_name or account["display_name"] or account["email"],
        company_name=config.COMPANY_NAME,
        company_address=config.COMPANY_ADDRESS,
        unsubscribe_link=build_unsubscribe_link(lead["id"]),
    )
    full_body = body + footer

    message_id, thread_id = gmail_client.send_email(
        account, lead["email"], subject, full_body
    )

    db.log_message(
        lead_id=lead["id"], account_id=account["id"], campaign_id=campaign["id"],
        gmail_message_id=message_id, thread_id=thread_id, direction="sent",
        subject=subject, snippet=full_body[:200], body=full_body,
        from_addr=account["email"], to_addr=lead["email"],
    )
    db.update_lead_after_send(lead["id"], account["email"], thread_id)
    db.increment_sent_count(account["id"])
    return message_id, thread_id


def _is_account_level_error(error_message):
    msg = (error_message or "").lower()
    return any(marker in msg for marker in ACCOUNT_LEVEL_ERROR_MARKERS)


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
                 and l.get("verify_status") != "invalid"]
        if not leads:
            break

        lead = leads[0]
        try:
            send_one(lead, account, campaign)
            sent_count += 1
        except Exception as e:
            err = str(e)
            if _is_account_level_error(err):
                db.set_account_error(account["id"], err)
                failed_account_ids.add(account["id"])
                # leave the lead as 'new' so it's retried on a different account
            else:
                # a per-recipient problem — don't touch the account, just
                # flag this one lead and move on so the rest of the batch
                # still goes out.
                db.mark_lead_status(lead["id"], "bounced")
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