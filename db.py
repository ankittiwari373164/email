"""
Storage layer — Supabase (Postgres) via psycopg2.

Same function names/signatures the rest of the app already uses
(app.py, sender.py, scraper.py, reply_tracker.py), just backed by Postgres
instead of the old local SQLite file, so:
  - all data lives in one shared Supabase project (works across
    Render/Vercel restarts and multiple dynos/instances)
  - `leads.email` has a UNIQUE constraint, so scraping never inserts the
    same email twice, from any category/run/source, ever.
"""
import psycopg2
import psycopg2.extras
from datetime import datetime, date
from contextlib import contextmanager

import config


@contextmanager
def get_conn():
    conn = psycopg2.connect(config.DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _rows(cur):
    return [dict(r) for r in cur.fetchall()]


def init_db():
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                source_domain TEXT,
                source_url TEXT,
                source_type TEXT,
                category TEXT,
                city TEXT,
                business_name TEXT,
                mx_valid INTEGER DEFAULT 0,
                verify_status TEXT DEFAULT 'unverified',
                verify_reason TEXT,
                verified_at TIMESTAMP,
                status TEXT DEFAULT 'new',
                scraped_at TIMESTAMP,
                gmail_account_used TEXT,
                last_contacted_at TIMESTAMP,
                thread_id TEXT,
                unsubscribed INTEGER DEFAULT 0
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                display_name TEXT,
                token_json TEXT NOT NULL,   -- OAuth token stored in Supabase, not
                                            -- a local file — survives redeploys on
                                            -- Render/Vercel, where the filesystem
                                            -- is wiped on every deploy/restart.
                daily_limit INTEGER DEFAULT 500,
                sent_today INTEGER DEFAULT 0,
                last_reset_date DATE,
                status TEXT DEFAULT 'disconnected',
                last_error TEXT,
                created_at TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                subject_template TEXT NOT NULL,
                body_template TEXT NOT NULL,
                category_filter TEXT,
                city_filter TEXT,
                status TEXT DEFAULT 'draft',
                image_filename TEXT,
                image_mime TEXT,
                image_base64 TEXT,          -- stored in Supabase, not a local
                                            -- file, so it survives redeploys
                image_placement TEXT DEFAULT 'attachment',  -- 'inline' or 'attachment'
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
                account_id INTEGER REFERENCES accounts(id),
                campaign_id INTEGER REFERENCES campaigns(id),
                gmail_message_id TEXT,
                thread_id TEXT,
                direction TEXT NOT NULL,
                subject TEXT,
                snippet TEXT,
                body TEXT,
                from_addr TEXT,
                to_addr TEXT,
                created_at TIMESTAMP,
                read INTEGER DEFAULT 0,
                is_bounce INTEGER DEFAULT 0
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS scrape_log (
                id SERIAL PRIMARY KEY,
                category TEXT,
                city TEXT,
                query TEXT,
                urls_found INTEGER,
                emails_found INTEGER,
                run_at TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS scrape_jobs (
                id SERIAL PRIMARY KEY,
                category TEXT NOT NULL,
                city TEXT,
                keywords TEXT,
                max_results INTEGER,
                status TEXT DEFAULT 'queued',
                sites_checked INTEGER DEFAULT 0,
                emails_found INTEGER DEFAULT 0,
                emails_inserted INTEGER DEFAULT 0,
                log TEXT DEFAULT '',
                started_at TIMESTAMP,
                finished_at TIMESTAMP
            )
        """)

        # Safe migrations for tables that may already exist from an earlier
        # version of this app (CREATE TABLE IF NOT EXISTS above only helps
        # for brand-new tables — these ADD COLUMN IF NOT EXISTS calls patch
        # existing ones in place, no manual DROP TABLE needed going forward).
        cur.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS image_filename TEXT")
        cur.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS image_mime TEXT")
        cur.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS image_base64 TEXT")
        cur.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS image_placement TEXT DEFAULT 'attachment'")
        cur.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_error TEXT")
        cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS cooldown_until TIMESTAMP")


# ---------- accounts ----------

def add_or_update_account(email, display_name, token_json):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO accounts (email, display_name, token_json, last_reset_date, status, created_at)
            VALUES (%s, %s, %s, %s, 'active', %s)
            ON CONFLICT (email) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                token_json = EXCLUDED.token_json,
                status = 'active',
                last_error = NULL
        """, (email, display_name, token_json, date.today(), datetime.utcnow()))


def update_account_token(account_id, token_json):
    """Called after a Gmail API auto-refresh so the new access token is
    persisted back to Supabase (otherwise the next request would refresh
    again from a stale token every single time)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE accounts SET token_json=%s WHERE id=%s", (token_json, account_id))


def list_accounts():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM accounts ORDER BY id")
        return _rows(cur)


def reset_daily_counts_if_needed():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE accounts SET sent_today = 0, last_reset_date = %s
            WHERE last_reset_date IS NULL OR last_reset_date != %s
        """, (date.today(), date.today()))
        # Auto-recover accounts that were paused for a known-temporary
        # rate limit whose cooldown has now passed — no manual
        # "Reactivate" click needed for this specific case.
        cur.execute("""
            UPDATE accounts SET status='active', cooldown_until=NULL
            WHERE status='error' AND cooldown_until IS NOT NULL AND cooldown_until <= %s
        """, (datetime.utcnow(),))


def get_account_with_capacity():
    reset_daily_counts_if_needed()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM accounts
            WHERE status = 'active' AND sent_today < daily_limit
            ORDER BY (daily_limit - sent_today) DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        return dict(row) if row else None


def increment_sent_count(account_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE accounts SET sent_today = sent_today + 1 WHERE id = %s", (account_id,))


def set_account_error(account_id, error, cooldown_until=None):
    """cooldown_until: if the error is a known-temporary rate limit with
    a specific expiry (Gmail's 429 responses include a "Retry after
    <timestamp>" — see sender.py's parsing), the account auto-recovers
    to 'active' once that time passes, no manual Reactivate click
    needed. If cooldown_until is None (unknown/permanent-looking error,
    e.g. revoked OAuth token), it stays in 'error' until someone
    reactivates it by hand, since auto-retrying that would just fail
    again immediately."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE accounts SET status='error', last_error=%s, cooldown_until=%s WHERE id=%s",
            (error, cooldown_until, account_id),
        )


def set_account_status(account_id, status, error=None):
    """Explicit status set — used to reactivate an account from the UI
    after a transient error, without touching sent_today/limits."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE accounts SET status=%s, last_error=%s WHERE id=%s", (status, error, account_id))


def delete_account(account_id):
    """Permanently remove a connected Gmail account. Its OAuth token is
    deleted too, so it stops being used for sends immediately. Historical
    messages already logged are left intact for record-keeping."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM accounts WHERE id=%s", (account_id,))


# ---------- leads ----------

def list_leads(status=None, category=None, city=None, verify_status=None, limit=200, offset=0):
    q = "SELECT * FROM leads WHERE 1=1"
    params = []
    if status:
        q += " AND status = %s"
        params.append(status)
    if category:
        q += " AND category = %s"
        params.append(category)
    if city:
        q += " AND city = %s"
        params.append(city)
    if verify_status:
        q += " AND verify_status = %s"
        params.append(verify_status)
    q += " ORDER BY scraped_at DESC NULLS LAST, id DESC LIMIT %s OFFSET %s"
    params += [limit, offset]
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(q, params)
        return _rows(cur)


def get_lead(lead_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM leads WHERE id = %s", (lead_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def insert_lead(email, source_domain=None, source_url=None, source_type="scrape",
                 category=None, city=None, business_name=None, mx_valid=0):
    """Insert a scraped lead. Returns True if newly inserted, False if that
    email already exists anywhere in the table (global de-dupe via the
    UNIQUE constraint on leads.email — a category re-scrape, a different
    category, a different day, doesn't matter, the email is only ever
    stored once)."""
    email = email.strip().lower()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO leads
                (email, source_domain, source_url, source_type, category, city,
                 business_name, mx_valid, status, scraped_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'new', %s)
            ON CONFLICT (email) DO NOTHING
            RETURNING id
        """, (email, source_domain, source_url, source_type, category, city,
              business_name, mx_valid, datetime.utcnow()))
        return cur.fetchone() is not None


def update_lead_after_send(lead_id, account_email, thread_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE leads SET status='contacted', gmail_account_used=%s,
                last_contacted_at=%s, thread_id=%s
            WHERE id=%s
        """, (account_email, datetime.utcnow(), thread_id, lead_id))


def mark_lead_status(lead_id, status):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE leads SET status=%s WHERE id=%s", (status, lead_id))


def mark_lead_bounced(lead_id, reason):
    """Like mark_lead_status(lead_id, 'bounced') but also records WHY, so
    a bounce is diagnosable later instead of a silent black box."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE leads SET status='bounced', last_error=%s WHERE id=%s", (reason, lead_id))


def mark_lead_unsubscribed(lead_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE leads SET unsubscribed=1, status='unsubscribed' WHERE id=%s", (lead_id,))


def delete_lead(lead_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM leads WHERE id=%s", (lead_id,))


def delete_leads(lead_ids):
    if not lead_ids:
        return 0
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM leads WHERE id = ANY(%s)", (list(lead_ids),))
        return cur.rowcount


def delete_leads_by_filter(status=None, category=None, city=None):
    """Bulk delete matching current filter — used by 'delete all filtered'."""
    q = "DELETE FROM leads WHERE 1=1"
    params = []
    if status:
        q += " AND status = %s"
        params.append(status)
    if category:
        q += " AND category = %s"
        params.append(category)
    if city:
        q += " AND city = %s"
        params.append(city)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(q, params)
        return cur.rowcount


def set_lead_verification(lead_id, verify_status, verify_reason, mx_valid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE leads SET verify_status=%s, verify_reason=%s, mx_valid=%s, verified_at=%s
            WHERE id=%s
        """, (verify_status, verify_reason, mx_valid, datetime.utcnow(), lead_id))


def lead_by_thread(thread_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM leads WHERE thread_id = %s", (thread_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def distinct_categories():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT category FROM leads WHERE category IS NOT NULL AND category != '' ORDER BY category")
        return [r["category"] for r in _rows(cur)]


def stats():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) c FROM leads")
        total = cur.fetchone()["c"]
        cur.execute("SELECT status, COUNT(*) c FROM leads GROUP BY status")
        by_status = _rows(cur)
        return {"total": total, "by_status": {r["status"]: r["c"] for r in by_status}}


# ---------- scrape jobs ----------

def create_scrape_job(category, city, keywords, max_results):
    """Raise a scrape ticket. It sits as 'pending' until the local
    worker (worker.py running on your PC) claims and runs it."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO scrape_jobs (category, city, keywords, max_results, status)
            VALUES (%s, %s, %s, %s, 'pending') RETURNING id
        """, (category, city, keywords, max_results))
        return cur.fetchone()["id"]


def claim_next_pending_job():
    """Atomically grab the oldest pending job and mark it 'running' so
    two worker instances can't pick up the same job. Returns the job
    dict, or None if nothing is pending. Uses FOR UPDATE SKIP LOCKED
    so concurrent workers each get a different row."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM scrape_jobs
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """)
        row = cur.fetchone()
        if not row:
            return None
        job_id = row["id"]
        cur.execute(
            "UPDATE scrape_jobs SET status='running', started_at=%s WHERE id=%s",
            (datetime.utcnow(), job_id),
        )
        cur.execute("SELECT * FROM scrape_jobs WHERE id=%s", (job_id,))
        return dict(cur.fetchone())


def update_scrape_job(job_id, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=%s" for k in fields)
    params = list(fields.values()) + [job_id]
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE scrape_jobs SET {cols} WHERE id=%s", params)


def append_scrape_job_log(job_id, line):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE scrape_jobs SET log = COALESCE(log, '') || %s WHERE id=%s",
                    (line.rstrip("\n") + "\n", job_id))


def get_scrape_job(job_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM scrape_jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_scrape_jobs(limit=20):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM scrape_jobs ORDER BY id DESC LIMIT %s", (limit,))
        return _rows(cur)


# ---------- campaigns ----------

def create_campaign(name, subject_template, body_template, category_filter, city_filter,
                     image_filename=None, image_mime=None, image_base64=None, image_placement="attachment"):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO campaigns (name, subject_template, body_template, category_filter, city_filter,
                image_filename, image_mime, image_base64, image_placement, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s) RETURNING id
        """, (name, subject_template, body_template, category_filter, city_filter,
              image_filename, image_mime, image_base64, image_placement, datetime.utcnow()))
        return cur.fetchone()["id"]


def update_campaign(campaign_id, name, subject_template, body_template, category_filter, city_filter,
                     image_filename=None, image_mime=None, image_base64=None, image_placement=None,
                     remove_image=False):
    """image_* left as None means 'don't touch the existing image'; pass
    remove_image=True to explicitly clear it instead."""
    with get_conn() as conn:
        cur = conn.cursor()
        if remove_image:
            cur.execute("""
                UPDATE campaigns SET name=%s, subject_template=%s, body_template=%s,
                    category_filter=%s, city_filter=%s, updated_at=%s,
                    image_filename=NULL, image_mime=NULL, image_base64=NULL, image_placement='attachment'
                WHERE id=%s
            """, (name, subject_template, body_template, category_filter, city_filter,
                  datetime.utcnow(), campaign_id))
        elif image_base64 is not None:
            cur.execute("""
                UPDATE campaigns SET name=%s, subject_template=%s, body_template=%s,
                    category_filter=%s, city_filter=%s, updated_at=%s,
                    image_filename=%s, image_mime=%s, image_base64=%s, image_placement=%s
                WHERE id=%s
            """, (name, subject_template, body_template, category_filter, city_filter,
                  datetime.utcnow(), image_filename, image_mime, image_base64, image_placement, campaign_id))
        else:
            cur.execute("""
                UPDATE campaigns SET name=%s, subject_template=%s, body_template=%s,
                    category_filter=%s, city_filter=%s, updated_at=%s
                WHERE id=%s
            """, (name, subject_template, body_template, category_filter, city_filter,
                  datetime.utcnow(), campaign_id))


def list_campaigns():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM campaigns ORDER BY id DESC")
        return _rows(cur)


def get_campaign(campaign_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM campaigns WHERE id=%s", (campaign_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def set_campaign_status(campaign_id, status):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE campaigns SET status=%s WHERE id=%s", (status, campaign_id))


def delete_campaign(campaign_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM campaigns WHERE id=%s", (campaign_id,))


def list_running_campaigns():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM campaigns WHERE status='running' ORDER BY id")
        return _rows(cur)


# ---------- messages ----------

def log_message(lead_id, account_id, campaign_id, gmail_message_id, thread_id,
                 direction, subject, snippet, body, from_addr, to_addr, is_bounce=0):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO messages (lead_id, account_id, campaign_id, gmail_message_id, thread_id,
                direction, subject, snippet, body, from_addr, to_addr, created_at, read, is_bounce)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (lead_id, account_id, campaign_id, gmail_message_id, thread_id, direction,
              subject, snippet, body, from_addr, to_addr, datetime.utcnow(),
              1 if direction == "sent" else 0, is_bounce))


def message_exists(gmail_message_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM messages WHERE gmail_message_id=%s", (gmail_message_id,))
        return cur.fetchone() is not None


def list_replies(unread_only=False, limit=100, include_bounces=False):
    q = """
        SELECT m.*, l.business_name, l.email as lead_email, l.category, l.city
        FROM messages m LEFT JOIN leads l ON l.id = m.lead_id
        WHERE m.direction = 'received'
    """
    params = []
    if not include_bounces:
        q += " AND m.is_bounce = 0"
    if unread_only:
        q += " AND m.read = 0"
    q += " ORDER BY m.created_at DESC LIMIT %s"
    params.append(limit)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(q, params)
        return _rows(cur)


def thread_messages(thread_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM messages WHERE thread_id=%s ORDER BY created_at ASC", (thread_id,))
        return _rows(cur)


def mark_message_read(message_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE messages SET read=1 WHERE id=%s", (message_id,))