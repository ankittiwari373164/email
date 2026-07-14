# Outreach Dashboard — Gmail sending + reply tracking + category scraping

Type a category (and optional city) into the **Scrape** page and it finds
businesses in that category on the web, pulls contact emails off their
sites, and drops new leads straight into `leads.db`. From there it sends
via 5 Gmail accounts on rotation (500/day cap each, tracked and reset
daily), polls for replies, and shows everything in a dashboard.

## 0. Scraping leads by category

Go to **Scrape**, enter a category (e.g. "yoga studios"), optionally a
city and extra keywords, and click "Start scrape". It runs in the
background so you can keep using the dashboard — refresh the Scrape page
to watch site-count/emails-found/new-leads tick up live, or click "Log"
on a job row for a line-by-line trace.

How it works (`scraper.py`):
- Searches DuckDuckGo's HTML endpoint for `<category> <city> contact email`
  (no API key needed).
- Visits each result site's homepage, and its contact/about page if the
  homepage itself has no email, extracting addresses that belong to that
  site's own domain (cuts down heavily on noise from ad widgets etc).
- MX-checks each email's domain and sets `leads.mx_valid` accordingly —
  campaigns already skip `mx_valid=0` leads.
- Inserts into `leads` with `category`/`city`/`source_url` set, skipping
  duplicates by email automatically.

Worth knowing before you lean on this at volume:
- It's a lightweight scraper (requests + BeautifulSoup), not a full
  browser — sites that render contact info via JavaScript won't yield an
  email from this pass.
- It's deliberately polite (paced requests, normal browser user-agent,
  only reads public pages) but you're still responsible for checking that
  collecting and emailing addresses from a given source complies with the
  anti-spam/privacy law that applies to you and your recipients
  (CAN-SPAM, India's DPDP Act, GDPR/PECR, etc). The outgoing-email side
  (real sender identity + working unsubscribe) is already handled by
  `sender.py`; consent/legitimate-interest for *collecting* an address is
  worth checking per source, especially outside the US.
- Start with a modest `max_results` (20-30) per run while you get a feel
  for lead quality per category before scaling up.

## 1. One-time Google Cloud setup (do this first — ~10 min)

You need ONE Google Cloud OAuth client. All 5 Gmail accounts authorize
against it individually — you don't need 5 separate projects.

1. Go to https://console.cloud.google.com/ and create a new project
   (e.g. "Outreach Dashboard").
2. **Enable the Gmail API**: APIs & Services → Library → search "Gmail API" → Enable.
3. **Configure OAuth consent screen**: APIs & Services → OAuth consent screen.
   - User type: External (unless you have Google Workspace, then Internal is fine)
   - Fill app name, support email
   - Scopes: add `gmail.send`, `gmail.readonly`, `gmail.modify`
   - **Test users**: add all 5 Gmail addresses you'll be sending from
     (required while the app is in "Testing" mode — otherwise only your
     own account can authorize)
4. **Create credentials**: APIs & Services → Credentials → Create Credentials
   → OAuth client ID → Application type: **Web application**.
   - Authorized redirect URI: `http://localhost:5000/oauth2callback`
5. Download the JSON, rename it `client_secret.json`, place it at:
   `credentials/client_secret.json` (already gitignored — never commit this)

Note: while your OAuth app is in "Testing" status, tokens expire after 7
days unless the account is listed as a test user (test users don't
expire). Once you've connected your 5 accounts, you don't need to publish
the app — testing mode with test users is fine for internal use like this.

## 2. Install & run

```bash
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000

## 3. Connect your 5 Gmail accounts

Go to **Gmail Accounts** → "Connect a Gmail account" → sign in with the
first account → grant access → repeat 4 more times, once per account.
Each shows up in the accounts table with `sent_today` / `daily_limit`
tracking.

## 4. Create a campaign

Go to **Campaigns** → fill in subject/body templates (use
`{business_name}`, `{city}`, `{category}`, `{email}` placeholders) →
optionally filter by category/city to target a subset of your scraped
leads → Create → click "Send 50" to send a batch.

Sending automatically:
- Picks whichever of your 5 accounts has the most remaining daily capacity
- Skips leads with `mx_valid = 0` or that unsubscribed
- Appends your company name/address + a working unsubscribe link to every email
- Paces sends (default 8s apart per send) rather than blasting
- Marks each lead `contacted`, records which account + thread sent it

Click "Send 50" again later (or wire a cron/scheduler call to
`POST /api/campaigns/<id>/send`) to keep working through the list —
it naturally stops once all 5 accounts hit their daily cap.

## 5. Replies

A background poller checks all 5 inboxes every 2 minutes
(`REPLY_POLL_INTERVAL_SECONDS` in `config.py`) for new messages in
threads you started, logs them, and flips the lead to `replied`. You
can also hit "Check for new replies now" on the **Replies** page.
Click into any thread to see the full back-and-forth.

## Compliance basics already wired in (don't rip these out)

- Every email includes your real sender name/company + a working
  **unsubscribe link** (`/unsubscribe/<lead_id>`) — clicking it sets
  `unsubscribed=1` and the lead is skipped by future sends.
- Only `mx_valid` leads are sent to.
- Per-account daily cap defaults to 500 (`DEFAULT_DAILY_LIMIT` in
  `config.py`) and resets at midnight.
- Sends are paced (not bursted) to reduce spam-flagging risk on your
  Gmail accounts.

Two things this doesn't do for you, worth doing before you scale up:
- **List hygiene**: bounces aren't auto-detected yet — Gmail API doesn't
  surface delivery failures the same way SMTP does. Worth adding a check
  against `mailer-daemon@` replies and marking those leads `bounced`.
- **Volume ramp-up**: brand-new/lightly-used Gmail accounts that suddenly
  send 500/day tend to get spam-flagged or temporarily limited by Google.
  Start each new account around 20-50/day and step it up over ~2 weeks
  before relying on the full 500 cap.

## Files

| File | Purpose |
|---|---|
| `config.py` | all settings — DB path, daily limits, pacing, footer text |
| `db.py` | schema (leads/accounts/campaigns/messages) + queries |
| `gmail_client.py` | OAuth flow + Gmail API send/read wrapper |
| `sender.py` | picks lead + account, sends, logs, updates status |
| `reply_tracker.py` | polls inboxes, logs replies, flips lead status |
| `scheduler.py` | background job that calls reply_tracker on an interval |
| `app.py` | Flask routes + dashboard |
| `templates/` | dashboard pages (Bootstrap, no build step needed) |

## Deploying beyond localhost

Change `OAUTH_REDIRECT_URI` and `PUBLIC_BASE_URL` in `config.py` to your
real domain, add that redirect URI in Google Cloud Console too, and put
`leads.db`/`tokens/`/`credentials/` somewhere persistent (they're just
files — no separate database server required, though you can swap
`db.py` for Postgres later using the same schema).
