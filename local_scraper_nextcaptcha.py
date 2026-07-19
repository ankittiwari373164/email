"""
STARTPAGE EMAIL SCRAPER
Searches Startpage (Google results via privacy proxy) for emails across
LinkedIn / Instagram / JustDial / Facebook, and writes leads to your DB.

Why Startpage: it serves Google-quality results but is far less aggressive
about the Google "sorry" CAPTCHA page. Combined with your DataImpulse
residential proxy + a real (non-headless) Chrome + human-like pacing, it
usually runs without any CAPTCHA. If Startpage ever shows a challenge, the
script PAUSES so you can solve it once by hand in the window, then continues.

═══════════════════════════════════════════════════════════════════
SETUP
═══════════════════════════════════════════════════════════════════
pip install selenium selenium-wire blinker==1.7.0 webdriver-manager psycopg2-binary python-dotenv
# (setuptools<81 already handled earlier so selenium-wire imports)

.env (same folder):
    DATABASE_URL=postgresql://...            (optional; omit to just print)
    PROXY_HOST=gw.dataimpulse.com
    PROXY_PORT=823
    PROXY_USER=6553fd52db05df73a04f
    PROXY_PASS=e3060527ca5fbdbc
    USE_PROXY=1                              (set 0 to test on home IP)

USAGE
    python startpage_scraper.py "realestate" "Madhya Pradesh"
    python startpage_scraper.py "interior design" "Mumbai"
    python startpage_scraper.py "realestate"          (no city = broader)
═══════════════════════════════════════════════════════════════════
"""

import sys
import re
import os
import time
import random
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

# ---------- Config ----------
DATABASE_URL = os.getenv("DATABASE_URL")
PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT = os.getenv("PROXY_PORT")
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")
USE_PROXY = os.getenv("USE_PROXY", "1") == "1" and all([PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS])

# NextCaptcha only solves reCAPTCHA/Turnstile (NOT image CAPTCHAs), so for
# Startpage's image-text CAPTCHA we use 2Captcha's ImageToText instead.
NEXTCAPTCHA_API_KEY = os.getenv("NEXTCAPTCHA_API_KEY")
TWOCAPTCHA_API_KEY = os.getenv("TWOCAPTCHA_API_KEY")

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
JUNK_DOMAINS = {"example.com", "sentry.io", "wixpress.com", "google.com",
                "gstatic.com", "googleapis.com", "startpage.com", "startmail.com"}

PLATFORMS = {
    "LinkedIn": "www.linkedin.com",
    "Instagram": "www.instagram.com",
    "JustDial": "www.justdial.com",
    "Facebook": "www.facebook.com",
}

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "startpage_profile")
STARTPAGE_URL = "https://www.startpage.com/sp/search"

# ---------- DB (optional) ----------
try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def clean_emails(text):
    found = set()
    for m in EMAIL_RE.findall(text or ""):
        email = m.strip().strip(".,;:").lower()
        if "%22" in email or "%20" in email or "+" in email:
            continue
        if "@" not in email:
            continue
        localpart, domain = email.split("@", 1)
        if not localpart or "." not in domain:
            continue
        if domain in JUNK_DOMAINS or "sentry" in domain or "wixpress" in domain:
            continue
        if email.startswith(("noreply", "no-reply", "postmaster")):
            continue
        if any(p in domain for p in ("linkedin.com", "instagram.com", "facebook.com", "justdial.com")):
            continue
        found.add(email)
    return found


def insert_lead(email, source_type, category, city):
    if not (DATABASE_URL and HAS_PSYCOPG2):
        return False
    try:
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
    except Exception as e:
        print(f"    DB error: {str(e)[:80]}")
        return False


def init_driver():
    """Real, visible Chrome through the DataImpulse proxy (selenium-wire).
    Persistent profile keeps cookies/session so repeat runs look human."""
    from selenium.webdriver.chrome.options import Options

    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    seleniumwire_options = None
    if USE_PROXY:
        proxy_url = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
        seleniumwire_options = {
            "proxy": {"http": proxy_url, "https": proxy_url, "no_proxy": "localhost,127.0.0.1"}
        }
        print(f"🔌 Routing through proxy {PROXY_HOST}:{PROXY_PORT}")
    else:
        print("⚠️  No proxy (home IP). Set USE_PROXY=1 in .env to use DataImpulse.")

    if USE_PROXY:
        from seleniumwire import webdriver as wire_webdriver
        driver = wire_webdriver.Chrome(options=chrome_options,
                                       seleniumwire_options=seleniumwire_options)
    else:
        from selenium import webdriver
        driver = webdriver.Chrome(options=chrome_options)

    # Mask webdriver flag
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
    except Exception:
        pass
    return driver


def verify_ip(driver):
    from selenium.webdriver.common.by import By
    try:
        driver.get("https://api.ipify.org?format=json")
        time.sleep(2)
        body = driver.find_element(By.TAG_NAME, "body").text
        print(f"🔎 Browser exit IP: {body}")
        if "103.209.141.200" in body and USE_PROXY:
            print("   ❌ Still on HOME IP — proxy not applied. Stopping.")
            return False
        return True
    except Exception as e:
        print(f"   ⚠️  Could not verify IP: {e}")
        return True  # continue anyway


def try_2captcha_image(driver):
    """Auto-solve Startpage's image-text CAPTCHA via 2Captcha ImageToText.
    Uses the exact Startpage elements: img[alt=captcha], #captcha-input,
    button[type=submit]. Returns True if submitted, else False."""
    if not TWOCAPTCHA_API_KEY:
        print("    No TWOCAPTCHA_API_KEY set — using manual.")
        return False
    try:
        import requests, base64
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys

        # Startpage's CAPTCHA image
        img_el = None
        for by, sel in [
            (By.CSS_SELECTOR, "img[alt='captcha']"),
            (By.CSS_SELECTOR, "img[src*='captcha']"),
            (By.CSS_SELECTOR, ".captcha-section img"),
        ]:
            try:
                img_el = driver.find_element(by, sel)
                if img_el:
                    break
            except Exception:
                continue
        if not img_el:
            print("    2Captcha: no CAPTCHA image found, using manual.")
            return False

        png_bytes = img_el.screenshot_as_png
        b64 = base64.b64encode(png_bytes).decode().strip()
        print(f"    2Captcha: solving image CAPTCHA... ({len(b64)} b64 chars)")

        # Create ImageToText task (case-sensitive; Startpage says so)
        create = requests.post(
            "https://api.2captcha.com/createTask",
            json={
                "clientKey": TWOCAPTCHA_API_KEY,
                "task": {
                    "type": "ImageToTextTask",
                    "body": b64,
                    "case": True,
                    "phrase": False,
                    "numeric": 0,
                    "math": False,
                },
                "languagePool": "en",
            },
            timeout=30,
        ).json()

        if create.get("errorId"):
            print(f"    2Captcha error: {create.get('errorDescription')}")
            return False
        task_id = create.get("taskId")
        if not task_id:
            print(f"    2Captcha: no taskId (raw: {str(create)[:150]})")
            return False

        # Poll for the OCR answer
        text = None
        for _ in range(20):
            time.sleep(3)
            res = requests.post(
                "https://api.2captcha.com/getTaskResult",
                json={"clientKey": TWOCAPTCHA_API_KEY, "taskId": task_id},
                timeout=30,
            ).json()
            if res.get("status") == "ready":
                text = res.get("solution", {}).get("text")
                break
            if res.get("errorId"):
                print(f"    2Captcha solve error: {res.get('errorDescription')}")
                return False
        if not text:
            print("    2Captcha: no answer, using manual.")
            return False

        text = text.strip()
        print(f"    2Captcha: answer '{text}', entering...")

        # Type into Startpage's input and submit
        try:
            box = driver.find_element(By.CSS_SELECTOR, "#captcha-input")
        except Exception:
            box = driver.find_element(By.CSS_SELECTOR, "input[type=text]")
        box.clear()
        for ch in text:
            box.send_keys(ch)
            time.sleep(0.05)
        time.sleep(0.4)

        clicked = False
        for by, sel in [
            (By.CSS_SELECTOR, "button[type=submit]"),
            (By.XPATH, "//button[contains(., 'Submit')]"),
        ]:
            try:
                driver.find_element(by, sel).click()
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            box.send_keys(Keys.RETURN)
        time.sleep(4)
        print("    2Captcha: submitted.")
        return True
    except Exception as e:
        print(f"    2Captcha exception: {str(e)[:80]} — using manual.")
        return False


def wait_if_captcha(driver, timeout=240):
    """If Startpage challenges: try 2Captcha image OCR first; if that fails,
    pause for a manual solve in the visible window, then continue."""
    def is_captcha():
        s = (driver.page_source or "").lower()
        u = (driver.current_url or "").lower()
        return "captcha" in u or "captcha verification" in s or "enter image characters" in s

    if not is_captcha():
        return True

    print("\n" + "!" * 70)
    print("Startpage showed an image CAPTCHA.")

    # 1) Try automatic solve, retry a few times (OCR can misread)
    for attempt in range(3):
        if try_2captcha_image(driver):
            time.sleep(3)
            if not is_captcha():
                print("Auto-solved via 2Captcha, continuing.\n")
                return True
            print(f"Attempt {attempt+1} didn't clear it, retrying...")
            # click "Get new image" so next attempt has a fresh CAPTCHA
            try:
                from selenium.webdriver.common.by import By
                driver.find_element(By.XPATH, "//button[contains(., 'Get new image')]").click()
                time.sleep(2)
            except Exception:
                pass
    print("Auto-solve failed — falling back to manual.")

    # 2) Manual fallback
    print("Solve it BY HAND in the Chrome window now.")
    print("The script continues automatically once it clears.")
    print("!" * 70)
    waited = 0
    while waited < timeout:
        time.sleep(3)
        waited += 3
        if not is_captcha():
            print("Cleared, continuing...\n")
            return True
    print("Timed out waiting for CAPTCHA. Skipping this query.")
    return False


def search_query(driver, query):
    """Load Startpage results for a query, then wait for results to render."""
    from urllib.parse import urlencode
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    params = {"query": query, "cat": "web"}
    driver.get(f"{STARTPAGE_URL}?{urlencode(params)}")
    time.sleep(random.uniform(2.5, 4.0))
    # Wait for either results or a captcha to appear
    try:
        WebDriverWait(driver, 10).until(
            lambda d: "captcha" in (d.current_url or "").lower()
            or d.find_elements(By.CSS_SELECTOR, "a.result-link, .w-gl__result, [class*='result']")
        )
    except Exception:
        pass


def get_results_text(driver):
    """Return the visible text of the results area (where emails live).
    Reading rendered text catches emails that raw page_source splits up."""
    from selenium.webdriver.common.by import By
    texts = []
    # Try the main results container first
    for sel in [".w-gl", ".mainline-results", "main", "body"]:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for e in els:
                t = e.text or ""
                if t:
                    texts.append(t)
            if texts:
                break
        except Exception:
            continue
    # Always add raw source too, as a backstop
    texts.append(driver.page_source or "")
    return "\n".join(texts)


def has_results(driver):
    """True if the page actually shows search results."""
    from selenium.webdriver.common.by import By
    els = driver.find_elements(
        By.CSS_SELECTOR,
        "a.result-link, .w-gl__result, .result, [data-testid='result']"
    )
    return len(els) > 0


def click_next(driver):
    """Startpage 'Next' pagination — tries many selectors + text match."""
    from selenium.webdriver.common.by import By
    from selenium.common.exceptions import NoSuchElementException
    candidates = [
        (By.CSS_SELECTOR, "button.pagination__next"),
        (By.CSS_SELECTOR, "a.pagination__next"),
        (By.CSS_SELECTOR, "button.next"),
        (By.CSS_SELECTOR, "a.next"),
        (By.CSS_SELECTOR, "form.pagination__form button"),
        (By.XPATH, "//button[contains(translate(., 'NEXT','next'),'next')]"),
        (By.XPATH, "//a[contains(translate(., 'NEXT','next'),'next')]"),
        (By.XPATH, "//button[contains(@aria-label,'Next') or contains(@aria-label,'next')]"),
    ]
    for by, sel in candidates:
        try:
            el = driver.find_element(by, sel)
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.6)
            try:
                el.click()
            except Exception:
                driver.execute_script("arguments[0].click();", el)
            time.sleep(random.uniform(2.5, 4.0))
            return True
        except NoSuchElementException:
            continue
        except Exception:
            continue
    return False


def search_platform(driver, site, category, city, max_pages=50):
    query = f'site:{site} "@gmail.com" "{category}"'
    if city:
        query += f" {city}"
    print(f"  Searching: {query}")

    search_query(driver, query)
    if not wait_if_captcha(driver):
        return set()

    # After a possible CAPTCHA solve, give results a moment to render
    time.sleep(random.uniform(2.0, 3.5))

    all_emails = set()
    page_num = 1
    stale = 0

    while page_num <= max_pages:
        # Give the page a beat, then read RENDERED results text
        time.sleep(1.5)
        text = get_results_text(driver)
        page_emails = clean_emails(text)
        new = page_emails - all_emails
        print(f"    Page {page_num}: {len(new)} new ({len(page_emails)} on page)")
        all_emails.update(page_emails)

        # Only treat as "empty" if there are genuinely no result elements
        if not has_results(driver) and page_num == 1:
            print("    (no result elements detected on page 1)")

        if not new:
            stale += 1
            if stale >= 3:
                print("    No new emails 3 pages running, stopping")
                break
        else:
            stale = 0

        if not click_next(driver):
            print("    No more pages")
            break
        if not wait_if_captcha(driver):
            break

        page_num += 1
        delay = random.uniform(8, 18)
        print(f"    Waiting {delay:.0f}s before next page...")
        time.sleep(delay)

    print(f"    -> {len(all_emails)} email(s) for this platform ({page_num} page(s))")
    return all_emails


def run(category, city=None):
    print("=" * 70)
    print(f"STARTPAGE SCRAPE: '{category}' in '{city or 'anywhere'}'")
    print("=" * 70)

    driver = init_driver()
    all_emails = {}
    try:
        if not verify_ip(driver):
            return
        for name, site in PLATFORMS.items():
            print(f"\n[{name}]")
            all_emails[name] = search_platform(driver, site, category, city)
            delay = random.uniform(15, 30)
            print(f"  Waiting {delay:.0f}s before next platform...")
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
    if not (DATABASE_URL and HAS_PSYCOPG2):
        print("(No DB configured — emails printed above but not saved.)")
    else:
        print("Refresh your dashboard's Leads page to see them.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python startpage_scraper.py "category" ["city"]')
        print('Example: python startpage_scraper.py "realestate" "Madhya Pradesh"')
        sys.exit(1)
    category = sys.argv[1]
    city = sys.argv[2] if len(sys.argv) > 2 else None
    run(category, city)