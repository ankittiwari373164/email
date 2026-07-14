import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------- Database (Supabase Postgres) ----------------
# In Supabase: Project Settings -> Database -> Connection string -> URI
# (use the "Session pooler" URI if you deploy on Render/Vercel — it plays
# nicer with serverless/short-lived connections than the direct one).
# Example:
# postgresql://postgres.xxxx:PASSWORD@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Create a Supabase project, copy its Postgres "
        "connection string (Project Settings -> Database -> Connection string -> URI) "
        "into a DATABASE_URL env var (or a .env file locally), and restart."
    )

# ---------------- Gmail OAuth ----------------
CLIENT_SECRET_FILE = os.environ.get(
    "CLIENT_SECRET_FILE_PATH",
    os.path.join(BASE_DIR, "client_secret.json")
)
TOKENS_DIR = os.path.join(BASE_DIR, "tokens")

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Must exactly match a redirect URI registered in Google Cloud Console.
# Locally: http://localhost:5000/oauth2callback
# In production: https://your-app.onrender.com/oauth2callback
OAUTH_REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "http://localhost:5000/oauth2callback")

# Public base URL, used to build unsubscribe links and the OAuth redirect
# above. Set this to your real Render URL once deployed.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:5000")

# ---------------- Sending ----------------
DEFAULT_DAILY_LIMIT = int(os.environ.get("DEFAULT_DAILY_LIMIT", "500"))
SEND_PACING_SECONDS = int(os.environ.get("SEND_PACING_SECONDS", "8"))

# How many sends a single automatic cycle attempts per campaign before
# moving to the next one (keeps each scheduler tick bounded).
AUTO_SEND_BATCH_SIZE = int(os.environ.get("AUTO_SEND_BATCH_SIZE", "25"))

# How often (seconds) the background scheduler tries to send more emails
# for every 'running' campaign, and how often it polls for replies.
AUTO_SEND_INTERVAL_SECONDS = int(os.environ.get("AUTO_SEND_INTERVAL_SECONDS", "600"))
REPLY_POLL_INTERVAL_SECONDS = int(os.environ.get("REPLY_POLL_INTERVAL_SECONDS", "120"))

# Master on/off switch for full automation (auto-sending + reply polling).
# Leave true once you're confident in your campaigns; flip to false (env
# var AUTO_AUTOMATION=false) if you want manual "Send 50" control only.
AUTO_AUTOMATION_ENABLED = os.environ.get("AUTO_AUTOMATION", "true").lower() != "false"

FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "change-me-in-production")






# ---------------- Email verification ----------------
# SMTP handshake verification (RCPT TO without sending) is best-effort —
# many mail servers (esp. Gmail/Outlook) accept-all at RCPT stage and only
# bounce after acceptance, so treat "smtp_check" results as a hint, not
# gospel. It's skipped by default because it's slow and many networks
# (including some PaaS hosts) block outbound port 25 entirely.
VERIFY_SMTP_CHECK = os.environ.get("VERIFY_SMTP_CHECK", "false").lower() == "true"
VERIFY_SMTP_TIMEOUT = int(os.environ.get("VERIFY_SMTP_TIMEOUT", "8"))
VERIFY_FROM_ADDR = os.environ.get("VERIFY_FROM_ADDR", "verify@example.com")