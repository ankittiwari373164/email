"""
LOCAL CHROME SCRAPER — run this on YOUR computer, not on Render.

Render can't run real Chrome (no browser installed on its standard web
service tier), and Google blocks/serves empty results to datacenter IPs
making automated requests. Your PC doesn't have either problem — real
Chrome, real residential IP, and (if you're logged into Google in that
Chrome profile) an authenticated session that avoids bot detection.

This script opens real Chrome, runs the exact query format that works
in your browser (site:www.X.com "@gmail.com" "category" city), reads
the emails directly from the search result snippets, and writes any
new leads straight into the same Supabase database your Render
dashboard reads from — so they show up there automatically, no need
to copy/paste anything.

═══════════════════════════════════════════════════════════════════
SETUP (one-time, on your PC — not Render)
═══════════════════════════════════════════════════════════════════

1. Make sure Google Chrome is installed (you already have it).

2. Install Python packages:
   pip install selenium webdriver-manager psycopg2-binary python-dotenv

3. Create a file named `.env` in this same folder with your Supabase
   connection string (same one Render uses — check Render's
   Environment tab for DATABASE_URL and copy it here):

   DATABASE_URL=postgresql://postgres:...@db.xxxxx.supabase.co:5432/postgres

4. (Recommended) Log into your Google account in a normal Chrome
   window first. This script launches Chrome with your default
   profile so it inherits that logged-in session, which makes Google
   far less likely to block/rate-limit the automated searches.

═══════════════════════════════════════════════════════════════════
USAGE
═══════════════════════════════════════════════════════════════════

   python local_scraper.py "realestate" "Delhi"
   python local_scraper.py "interior design" "Mumbai"
   python local_scraper.py "realestate"              (no city = broader)

Leads get inserted into the same `leads` table your dashboard shows —
refresh the Leads page after this finishes and they'll be there.
═══════════════════════════════════════════════════════════════════
"""

import sys
import re
import time
import os
import random

import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found. Create a .env file with your Supabase connection string.")
    sys.exit(1)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
JUNK_DOMAINS = {"example.com", "sentry.io", "wixpress.com", "google.com", "gstatic.com", "googleapis.com"}

PLATFORMS = {
    "LinkedIn": "www.linkedin.com",
    "Instagram": "www.instagram.com",
    "JustDial": "www.justdial.com",
    "Facebook": "www.facebook.com",
}


def clean_emails(text):
    found = set()
    for m in EMAIL_RE.findall(text):
        email = m.strip().strip(".,;:").lower()
        # Reject URL-encoding artifacts that leak in from query-string
        # links in the page (e.g. "www.facebook.com+%22@gmail.com" from
        # a "search again" link) — real emails never contain these.
        if "%22" in email or "%20" in email or "+" in email:
            continue
        localpart, domain = email.split("@", 1)
        if not localpart or "." not in domain:
            continue
        if domain in JUNK_DOMAINS or "sentry" in domain or "wixpress" in domain:
            continue
        if email.startswith(("noreply", "no-reply", "postmaster")):
            continue
        # Reject if the "domain" is actually one of the platform hosts
        # themselves (another sign of a mis-captured URL fragment)
        if any(p in domain for p in ("linkedin.com", "instagram.com", "facebook.com", "justdial.com")):
            continue
        found.add(email)
    return found


def insert_lead(email, source_type, category, city):
    """Same logic as db.insert_lead() in the main app — writes to the
    identical leads table so it shows up in your Render dashboard."""
    with psycopg2.connect(DATABASE_URL) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO leads
                (email, source_domain, source_url, source_type, category, city,
                 business_name, mx_valid, status, scraped_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'new', %s)
            ON CONFLICT (email) DO NOTHING
            RETURNING id
        """, (email, email.split("@")[-1], "", source_type, category, city,
              None, 1, datetime.now(timezone.utc)))
        conn.commit()
        return cur.fetchone() is not None


PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome_profile")


def init_driver():
    """Launch real Chrome (visible, not headless) using a DEDICATED
    persistent profile folder (not your everyday Chrome profile — that
    would lock/conflict if your regular Chrome is open at the same
    time). The first time you run this, you'll log into Google once in
    that window; every run after that reuses the same saved session/
    cookies automatically, since it's the same profile folder on disk.
    That's the actual fix for CAPTCHA frequency — a real logged-in
    session looks like normal browsing, not a fresh anonymous bot."""
    options = Options()
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    options.add_argument("--start-maximized")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def ensure_logged_in(driver):
    """Check if we're logged into Google in this profile. We do NOT try
    to drive the login flow from inside this Selenium session — Google
    deliberately blocks sign-in attempts from automated browsers
    ("This browser or app may not be secure"), and that's a security
    feature to respect, not a bug to route around. If you're not
    logged in yet, run login_setup.py first (plain, non-automated
    Chrome) to log in once, then come back here."""
    driver.get("https://myaccount.google.com/")
    time.sleep(2)

    if "myaccount.google.com" in driver.current_url and "signin" not in driver.current_url:
        print("✓ Logged into Google (session reused from login_setup.py)\n")
        return True

    print("\n" + "=" * 70)
    print("Not logged into Google in this profile yet.")
    print("This script won't attempt to log in itself — Google blocks")
    print("sign-in from automated browsers as a security measure.")
    print()
    print("Run this first, in a separate terminal, then come back:")
    print("   python login_setup.py")
    print("=" * 70)
    return False


def wait_if_captcha(driver, timeout=180):
    """Google shows a CAPTCHA when it sees automated-looking traffic —
    usually from searching too fast/too often. We don't (and won't)
    auto-solve it; that's circumventing Google's anti-abuse system,
    not a bug to work around in code. Instead: detect it, pause, and
    let you solve it by hand in the visible window (takes 2 seconds),
    then the script continues on its own once it's gone.

    The real fix is triggering it less often — see the slower pacing
    and session persistence below."""
    if "google.com/sorry" in driver.current_url or "unusual traffic" in driver.page_source.lower():
        print("\n" + "!" * 70)
        print("Google showed a CAPTCHA (this happens when queries run too fast).")
        print("Please solve it manually in the Chrome window now.")
        print("The script will continue automatically once it's gone.")
        print("!" * 70)

        waited = 0
        while waited < timeout:
            time.sleep(3)
            waited += 3
            if "google.com/sorry" not in driver.current_url:
                print("CAPTCHA cleared, continuing...\n")
                return True
        print("Timed out waiting for CAPTCHA to be solved. Skipping this query.")
        return False
    return True


def type_search_query(driver, query):
    """Go to google.com and type the query into the actual search box,
    like a human would, instead of jumping straight to a ?q=... URL.
    This is meaningfully less bot-like than direct URL navigation."""
    driver.get("https://www.google.com")
    time.sleep(1.5)

    box = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.NAME, "q"))
    )
    box.clear()
    # Type character by character with tiny pauses rather than one
    # instant send_keys() call — closer to real human typing speed.
    for ch in query:
        box.send_keys(ch)
        time.sleep(0.02)
    time.sleep(0.5)
    box.send_keys(Keys.RETURN)
    time.sleep(2.5)


def click_next_page(driver):
    """Click the 'Next' link at the bottom of results, like a human
    clicking through pages, instead of editing the URL's start= param.
    Returns True if it clicked through to another page, False if
    there's no next page (end of results)."""
    try:
        next_link = driver.find_element(By.ID, "pnnext")
    except NoSuchElementException:
        try:
            next_link = driver.find_element(By.PARTIAL_LINK_TEXT, "Next")
        except NoSuchElementException:
            return False

    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", next_link)
        time.sleep(0.5)
        next_link.click()
        time.sleep(3)
        return True
    except Exception:
        return False


def search_platform_emails(driver, site, category, city):
    """Runs the exact query format proven to surface emails in the
    snippets: site:www.X.com "@gmail.com" "category" city

    Types the query into the real search box (not a direct URL), then
    clicks through every available page of results for THIS platform
    — no page cap — before moving to the next platform. Waits 10-30s
    (randomized) between each page to keep the pacing well below what
    triggers rate limiting."""
    query = f'site:{site} "@gmail.com" "{category}"'
    if city:
        query += f" {city}"

    print(f"  Searching: {query}")
    type_search_query(driver, query)

    if not wait_if_captcha(driver):
        return set()

    all_emails = set()
    page_num = 1
    stale_pages_in_a_row = 0

    while True:
        if "did not match any documents" in driver.page_source.lower():
            print(f"    Page {page_num}: no results")
            break

        page_emails = clean_emails(driver.page_source)
        new_emails = page_emails - all_emails
        print(f"    Page {page_num}: {len(new_emails)} new email(s) ({len(page_emails)} on page)")

        all_emails.update(page_emails)

        if not new_emails:
            stale_pages_in_a_row += 1
            if stale_pages_in_a_row >= 2:
                # Two pages in a row with nothing new — genuinely done,
                # not just a fluke, stop paginating.
                print(f"    No new emails for 2 pages in a row, stopping")
                break
        else:
            stale_pages_in_a_row = 0

        if not click_next_page(driver):
            print(f"    No more pages")
            break

        if not wait_if_captcha(driver):
            break

        page_num += 1
        delay = random.uniform(10, 30)
        print(f"    Waiting {delay:.0f}s before next page...")
        time.sleep(delay)

    print(f"    -> {len(all_emails)} total email(s) for this platform ({page_num} page(s) checked)")
    return all_emails


def run(category, city=None):
    print("=" * 70)
    print(f"LOCAL CHROME SCRAPE: '{category}' in '{city or 'anywhere'}'")
    print("=" * 70)

    driver = init_driver()
    all_emails = {}

    try:
        if not ensure_logged_in(driver):
            print("\nStopping — log in via login_setup.py first, then re-run this.")
            return

        for name, site in PLATFORMS.items():
            print(f"\n[{name}]")
            emails = search_platform_emails(driver, site, category, city)
            all_emails[name] = emails
            delay = random.uniform(15, 30)
            print(f"\n  Waiting {delay:.0f}s before next platform...")
            time.sleep(delay)
    finally:
        driver.quit()

    print("\n" + "=" * 70)
    print("Inserting leads into database...")
    total_inserted = 0
    for source, emails in all_emails.items():
        for email in emails:
            if insert_lead(email, source.lower(), category, city):
                total_inserted += 1
                print(f"  ✓ {email}  ({source})")

    total_found = sum(len(e) for e in all_emails.values())
    print("\n" + "=" * 70)
    print("DONE")
    for source, emails in all_emails.items():
        print(f"{source}: {len(emails)} emails")
    print(f"TOTAL: {total_found} found, {total_inserted} new leads inserted")
    print("=" * 70)
    print("\nRefresh your dashboard's Leads page to see them.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python local_scraper.py "category" ["city"]')
        print('Example: python local_scraper.py "realestate" "Delhi"')
        sys.exit(1)

    category = sys.argv[1]
    city = sys.argv[2] if len(sys.argv) > 2 else None
    run(category, city)