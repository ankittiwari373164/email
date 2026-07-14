"""
Polls each connected Gmail account's inbox for new messages belonging to
threads we started, logs them as 'received' messages, and flips the
matching lead's status — to 'replied' for a genuine reply, or 'bounced'
for a delivery-failure notification (mailer-daemon / postmaster bounce),
so bounces don't inflate your Replies page or get double-counted as
engagement.

Run poll_all_accounts() on a schedule (see scheduler.py) or hit
POST /api/replies/check-now from the dashboard.
"""
import db
import gmail_client

BOUNCE_FROM_MARKERS = (
    "mailer-daemon", "postmaster", "mail delivery subsystem",
    "delivery status notification", "mail delivery failed",
)
BOUNCE_SUBJECT_MARKERS = (
    "delivery status notification", "delivery failure", "undeliverable",
    "returned mail", "failure notice", "address not found",
)


def _looks_like_bounce(msg):
    frm = (msg.get("from") or "").lower()
    subj = (msg.get("subject") or "").lower()
    return (any(m in frm for m in BOUNCE_FROM_MARKERS) or
            any(m in subj for m in BOUNCE_SUBJECT_MARKERS))


def poll_account(account):
    """Check one account's inbox for messages in threads we own."""
    new_replies = 0
    try:
        message_ids = gmail_client.list_recent_message_ids(
            account, query="in:inbox newer_than:14d"
        )
    except Exception as e:
        db.set_account_error(account["id"], str(e))
        return 0

    for mid in message_ids:
        if db.message_exists(mid):
            continue  # already logged

        msg = gmail_client.get_message(account, mid)
        lead = db.lead_by_thread(msg["thread_id"])
        if not lead:
            continue  # not a thread we started — ignore

        if account["email"].lower() in msg["from"].lower():
            continue  # our own sent copy surfacing in the thread

        is_bounce = _looks_like_bounce(msg)

        db.log_message(
            lead_id=lead["id"], account_id=account["id"], campaign_id=None,
            gmail_message_id=msg["id"], thread_id=msg["thread_id"], direction="received",
            subject=msg["subject"], snippet=msg["snippet"], body=msg["body"],
            from_addr=msg["from"], to_addr=msg["to"], is_bounce=1 if is_bounce else 0,
        )

        if is_bounce:
            db.mark_lead_status(lead["id"], "bounced")
        else:
            db.mark_lead_status(lead["id"], "replied")
            new_replies += 1  # only genuine replies count toward the badge/total

    return new_replies


def poll_all_accounts():
    total = 0
    for account in db.list_accounts():
        if account["status"] != "active":
            continue
        total += poll_account(account)
    return total