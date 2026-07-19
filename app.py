import os
import threading
from dotenv import load_dotenv

load_dotenv()  # loads .env in this folder if present (local dev only —
                # Render/Vercel set real env vars, .env is gitignored)

from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash

import config
import db
import gmail_client
import sender
import reply_tracker
import scheduler

import verify

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY

from datetime import timedelta
app.permanent_session_lifetime = timedelta(days=7)

# Allow OAuth over http:// for local dev only. In production PUBLIC_BASE_URL
# should be https:// (Render gives you this for free) so this env var
# simply won't matter there.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

_db_ready = False

# Paths reachable WITHOUT logging in:
#  - /login itself
#  - /health for UptimeRobot
#  - /unsubscribe/* so recipients can opt out without a dashboard account
#  - /oauth2callback so Google can complete the OAuth redirect
#  - /static for CSS
PUBLIC_PATH_PREFIXES = ("/login", "/health", "/unsubscribe", "/oauth2callback", "/static")


@app.before_request
def _ensure_db():
    global _db_ready
    if not _db_ready:
        db.init_db()
        _db_ready = True


@app.before_request
def _require_login():
    # Skip auth for public paths
    path = request.path
    if any(path == p or path.startswith(p + "/") or path.startswith(p) for p in PUBLIC_PATH_PREFIXES):
        return None
    # If no dashboard password is configured, don't lock anyone out.
    if not config.DASHBOARD_PASSWORD:
        return None
    if session.get("authed"):
        return None
    return redirect(url_for("login", next=path))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not config.DASHBOARD_PASSWORD:
        # No password set — nothing to log into.
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        if request.form.get("password") == config.DASHBOARD_PASSWORD:
            session["authed"] = True
            session.permanent = True
            nxt = request.args.get("next") or url_for("dashboard")
            # only allow same-site relative redirects
            if not nxt.startswith("/"):
                nxt = url_for("dashboard")
            return redirect(nxt)
        flash("Wrong password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("authed", None)
    flash("Logged out.")
    return redirect(url_for("login"))


# ---------------- Dashboard pages ----------------

@app.route("/")
def dashboard():
    return render_template("dashboard.html", stats=db.stats(), accounts=db.list_accounts())


@app.route("/health")
def health():
    """Plain-text 200 OK for uptime monitors (UptimeRobot etc). Also
    touches the DB so a broken DATABASE_URL shows up as a failed check
    instead of silently serving 200s."""
    try:
        db.stats()
        return "ok", 200
    except Exception as e:
        return f"db error: {e}", 503


@app.route("/leads")
def leads_page():
    status = request.args.get("status") or None
    category = request.args.get("category") or None
    city = request.args.get("city") or None
    verify_status = request.args.get("verify_status") or None
    leads = db.list_leads(status=status, category=category, city=city,
                           verify_status=verify_status, limit=500)
    return render_template("leads.html", leads=leads, status=status,
                            category=category, city=city, verify_status=verify_status)


@app.route("/accounts")
def accounts_page():
    return render_template("accounts.html", accounts=db.list_accounts())


@app.route("/accounts/<int:account_id>/reactivate", methods=["POST"])
def accounts_reactivate(account_id):
    """Manually flip an 'error' account back to 'active' after you've fixed
    whatever the last_error said (or if it was tripped by the old bug where
    a single bad recipient took the whole account offline)."""
    db.set_account_status(account_id, "active", error=None)
    flash("Account reactivated.")
    return redirect(url_for("accounts_page"))


@app.route("/accounts/<int:account_id>/delete", methods=["POST"])
def accounts_delete(account_id):
    """Permanently remove a connected Gmail account from the rotation."""
    db.delete_account(account_id)
    flash("Account removed.")
    return redirect(url_for("accounts_page"))


@app.route("/campaigns")
def campaigns_page():
    return render_template("campaigns.html", campaigns=db.list_campaigns())


@app.route("/templates")
def templates_page():
    return render_template("templates.html")


@app.route("/api/templates/<template_name>/preview")
def template_preview(template_name):
    import email_templates
    
    templates = {
        "digital_marketing": email_templates.TEMPLATE_DIGITAL_MARKETING,
        "real_estate": email_templates.TEMPLATE_REAL_ESTATE,
        "ecommerce": email_templates.TEMPLATE_ECOMMERCE,
    }
    
    if template_name not in templates:
        return "Template not found", 404
    
    config = templates[template_name]["config"].copy()
    # Add sample personalization
    config["sender_name"] = "Ankit Tiwari"
    config["contact_phone"] = "+91 92110 72781"
    config["contact_email"] = "info@yourcompany.com"
    config["contact_website"] = "www.yourcompany.com"
    config["cta_link"] = config["contact_email"]  # button opens a reply

    html = email_templates.build_professional_html_email(**config)
    return html


@app.route("/api/templates/<template_name>")
def template_api(template_name):
    import email_templates
    
    templates = {
        "digital_marketing": email_templates.TEMPLATE_DIGITAL_MARKETING,
        "real_estate": email_templates.TEMPLATE_REAL_ESTATE,
        "ecommerce": email_templates.TEMPLATE_ECOMMERCE,
    }
    
    if template_name not in templates:
        return {"error": "Template not found"}, 404
    
    template = templates[template_name]
    config = template["config"].copy()
    config["sender_name"] = config.get("sender_name", "")
    if config.get("contact_email"):
        config.setdefault("cta_link", config["contact_email"])
    
    body_html = email_templates.build_professional_html_email(**config)
    
    return jsonify({
        "name": template["name"],
        "subject": template["subject"],
        "body": body_html
    })


@app.route("/campaigns/<int:campaign_id>/edit")
def campaign_edit_page(campaign_id):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        flash("Campaign not found.")
        return redirect(url_for("campaigns_page"))
    return render_template("campaign_edit.html", campaign=campaign)


@app.route("/replies")
def replies_page():
    replies = db.list_replies()
    return render_template("replies.html", replies=replies)


@app.route("/thread/<thread_id>")
def thread_page(thread_id):
    messages = db.thread_messages(thread_id)
    lead = db.lead_by_thread(thread_id)
    for m in messages:
        if m["direction"] == "received":
            db.mark_message_read(m["id"])
    return render_template("thread.html", messages=messages, lead=lead)


# ---------------- Scraping (category -> leads) ----------------

@app.route("/scrape")
def scrape_page():
    return render_template(
        "scrape.html",
        jobs=db.list_scrape_jobs(),
        categories=db.distinct_categories(),
    )


@app.route("/scrape/start", methods=["POST"])
def scrape_start():
    category = request.form["category"].strip()
    city = (request.form.get("city") or "").strip() or None
    keywords = (request.form.get("keywords") or "").strip() or None
    max_results = int(request.form.get("max_results") or 20)
    max_results = max(1, min(max_results, 100))

    if not category:
        flash("Category is required.")
        return redirect(url_for("scrape_page"))

    # Raise a ticket only. The actual scraping runs on your LOCAL PC via
    # worker.py (which polls for pending jobs) — NOT here on Render,
    # since Render can't run a real browser and gets IP-blocked by
    # Google. The job sits as 'pending' until the local worker picks
    # it up, runs your scraper, writes leads to this same database,
    # and marks the ticket done.
    job_id = db.create_scrape_job(category, city, keywords, max_results)

    flash(
        f"Scrape ticket #{job_id} raised for '{category}'"
        + (f" in {city}" if city else "")
        + ". Make sure worker.py is running on your PC — it'll pick this up shortly."
    )
    return redirect(url_for("scrape_page"))


@app.route("/api/scrape/status/<int:job_id>")
def api_scrape_status(job_id):
    job = db.get_scrape_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify(job)


@app.route("/api/scrape/jobs")
def api_scrape_jobs():
    return jsonify(db.list_scrape_jobs())


# ---------------- Gmail OAuth: connect Gmail accounts ----------------

@app.route("/accounts/connect")
def accounts_connect():
    if not os.path.exists(config.CLIENT_SECRET_FILE):
        flash("Missing credentials/client_secret.json — download it from Google Cloud Console first. See README.")
        return redirect(url_for("accounts_page"))
    auth_url, state = gmail_client.get_authorization_url()
    session["oauth_state"] = state
    return redirect(auth_url)


@app.route("/oauth2callback")
def oauth2callback():
    state = session.get("oauth_state")
    creds = gmail_client.exchange_code_for_token(state, request.url)
    email = gmail_client.get_profile_email(creds)
    token_json = gmail_client.save_credentials(creds, email)
    db.add_or_update_account(email, email.split("@")[0], token_json)
    flash(f"Connected {email}")
    return redirect(url_for("accounts_page"))


# ---------------- Campaigns ----------------

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5MB — plenty for a logo/product shot,
                                    # keeps Supabase rows and email size sane


def _read_uploaded_image():
    """Returns (filename, mime, base64_str) or (None, None, None) if no
    file was uploaded / it's over the size limit (flashes a message)."""
    file = request.files.get("image")
    if not file or not file.filename:
        return None, None, None
    data = file.read()
    if len(data) > MAX_IMAGE_BYTES:
        flash(f"Image too large ({len(data)//1024}KB) — 5MB max. Image was not attached.")
        return None, None, None
    import base64 as _b64
    return file.filename, (file.mimetype or "image/png"), _b64.b64encode(data).decode()


@app.route("/campaigns/new", methods=["POST"])
def campaigns_new():
    image_filename, image_mime, image_base64 = _read_uploaded_image()
    db.create_campaign(
        name=request.form["name"],
        subject_template=request.form["subject_template"],
        body_template=request.form["body_template"],
        category_filter=request.form.get("category_filter") or None,
        city_filter=request.form.get("city_filter") or None,
        image_filename=image_filename,
        image_mime=image_mime,
        image_base64=image_base64,
        image_placement=request.form.get("image_placement") or "attachment",
    )
    return redirect(url_for("campaigns_page"))


@app.route("/campaigns/<int:campaign_id>/edit", methods=["POST"])
def campaigns_update(campaign_id):
    remove_image = request.form.get("remove_image") == "on"
    image_filename, image_mime, image_base64 = (None, None, None)
    if not remove_image:
        image_filename, image_mime, image_base64 = _read_uploaded_image()

    db.update_campaign(
        campaign_id,
        name=request.form["name"],
        subject_template=request.form["subject_template"],
        body_template=request.form["body_template"],
        category_filter=request.form.get("category_filter") or None,
        city_filter=request.form.get("city_filter") or None,
        image_filename=image_filename,
        image_mime=image_mime,
        image_base64=image_base64,
        image_placement=request.form.get("image_placement") or "attachment",
        remove_image=remove_image,
    )
    flash("Campaign updated.")
    return redirect(url_for("campaigns_page"))


@app.route("/campaigns/<int:campaign_id>/delete", methods=["POST"])
def campaigns_delete(campaign_id):
    db.delete_campaign(campaign_id)
    flash("Campaign deleted.")
    return redirect(url_for("campaigns_page"))


@app.route("/api/campaigns/<int:campaign_id>/status", methods=["POST"])
def api_campaign_set_status(campaign_id):
    """Toggle draft/running/paused — 'running' is what the full-automation
    scheduler picks up, so this is effectively the on/off switch for
    hands-free sending on this campaign."""
    status = request.json.get("status") if request.is_json else request.form.get("status")
    if status not in ("draft", "running", "paused", "done"):
        return jsonify({"error": "invalid status"}), 400
    db.set_campaign_status(campaign_id, status)
    return jsonify({"status": status})


_send_in_progress = set()  # campaign_ids currently sending, so double-clicks don't stack


@app.route("/api/campaigns/<int:campaign_id>/send", methods=["POST"])
def api_campaign_send(campaign_id):
    """Runs in a background thread — sending 50 emails at
    SEND_PACING_SECONDS apart easily takes several minutes, far longer
    than gunicorn's request timeout, so this must NOT block the request
    or the worker gets killed mid-batch (which is what was happening
    before this fix)."""
    if campaign_id in _send_in_progress:
        return jsonify({"already_running": True})

    max_sends = request.json.get("max_sends", 50) if request.is_json else 50

    def _run():
        _send_in_progress.add(campaign_id)
        try:
            sender.run_campaign(campaign_id, max_sends=max_sends)
        finally:
            _send_in_progress.discard(campaign_id)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"started": True, "max_sends": max_sends})


@app.route("/api/campaigns/<int:campaign_id>/send-status")
def api_campaign_send_status(campaign_id):
    return jsonify({"running": campaign_id in _send_in_progress})


# ---------------- Leads: delete + verify ----------------

@app.route("/leads/<int:lead_id>/delete", methods=["POST"])
def lead_delete(lead_id):
    db.delete_lead(lead_id)
    flash("Lead deleted.")
    return redirect(request.referrer or url_for("leads_page"))


@app.route("/leads/bulk-delete", methods=["POST"])
def leads_bulk_delete():
    ids = request.form.getlist("lead_ids")
    ids = [int(i) for i in ids if i.isdigit()]
    count = db.delete_leads(ids)
    flash(f"Deleted {count} lead(s).")
    return redirect(request.referrer or url_for("leads_page"))


@app.route("/leads/delete-filtered", methods=["POST"])
def leads_delete_filtered():
    """Delete every lead matching the current status/category/city filter
    (e.g. clear out every 'bounced' lead in one click)."""
    status = request.form.get("status") or None
    category = request.form.get("category") or None
    city = request.form.get("city") or None
    count = db.delete_leads_by_filter(status=status, category=category, city=city)
    flash(f"Deleted {count} lead(s) matching that filter.")
    return redirect(url_for("leads_page"))


@app.route("/api/leads/<int:lead_id>/verify", methods=["POST"])
def api_lead_verify(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        return jsonify({"error": "not found"}), 404
    result = verify.verify_email(lead["email"])
    db.set_lead_verification(lead_id, result["status"], result["reason"], result["mx_valid"])
    return jsonify(result)


@app.route("/api/leads/verify-unverified", methods=["POST"])
def api_leads_verify_unverified():
    """Verify every lead that hasn't been checked yet. Runs inline (not a
    background job) — for large lists call this repeatedly with a small
    limit, or trigger it from the Scrape job flow instead."""
    limit = int(request.json.get("limit", 100)) if request.is_json else 100
    leads = db.list_leads(verify_status="unverified", limit=limit)
    results = []
    for lead in leads:
        r = verify.verify_email(lead["email"])
        db.set_lead_verification(lead["id"], r["status"], r["reason"], r["mx_valid"])
        results.append({"id": lead["id"], "email": lead["email"], **r})
    return jsonify({"checked": len(results), "results": results})


# ---------------- Replies ----------------

_reply_check_in_progress = {"running": False, "last_result": None}


@app.route("/api/replies/check-now", methods=["POST"])
def api_check_replies():
    if _reply_check_in_progress["running"]:
        return jsonify({"already_running": True})

    def _run():
        _reply_check_in_progress["running"] = True
        try:
            n = reply_tracker.poll_all_accounts()
            _reply_check_in_progress["last_result"] = n
        finally:
            _reply_check_in_progress["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"started": True})


@app.route("/api/replies/check-status")
def api_check_replies_status():
    return jsonify(_reply_check_in_progress)


# ---------------- Unsubscribe (public, no login) ----------------

@app.route("/unsubscribe/<int:lead_id>")
def unsubscribe(lead_id):
    """GET only shows a confirmation page — it does NOT unsubscribe.
    This matters: corporate email security scanners (Outlook Safe Links,
    Gmail's link-safety prefetcher, various proxies) automatically visit
    every link in an email before the recipient ever opens it. If GET
    unsubscribed directly, those scanners would silently unsubscribe
    leads who never saw the email — which is very likely what's been
    happening (see the Bounced/Unsubscribed counts on Overview). Only the
    POST from the button below actually unsubscribes."""
    lead = db.get_lead(lead_id)
    if not lead:
        return "This link isn't valid.", 404
    if lead.get("unsubscribed"):
        return "You're already unsubscribed — no further emails will be sent.", 200
    return render_template("unsubscribe_confirm.html", lead=lead)


@app.route("/unsubscribe/<int:lead_id>/confirm", methods=["POST"])
def unsubscribe_confirm(lead_id):
    db.mark_lead_unsubscribed(lead_id)
    return "You've been unsubscribed and won't receive further emails from us.", 200


# ---------------- Stats API (dashboard auto-refresh) ----------------

@app.route("/api/stats")
def api_stats():
    return jsonify(db.stats())


# Start the background scheduler (reply polling + optional auto-send) once,
# whether run via `python app.py` locally or imported by gunicorn in prod.
#
# IMPORTANT: this process must run as exactly ONE worker (see Procfile:
# `gunicorn app:app --workers 1 --threads 8`). Each gunicorn *worker* is a
# separate process with its own copy of this module, so N workers would
# start N independent schedulers — each polling replies and auto-sending
# on its own, which risks the same lead getting emailed twice in a race.
# Threads are fine (they share this one process/scheduler); workers are not.
db.init_db()
_db_ready = True
scheduler.start()

if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
