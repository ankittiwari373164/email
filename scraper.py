"""4-SOURCE LEAD SCRAPER WITH CHROME MULTI-TAB AUTOMATION
Sources: LinkedIn, Instagram, JustDial, Web
"""
import re, time, socket
from urllib.parse import urlparse
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import config, db

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
HEADERS = {"User-Agent": USER_AGENT}
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

def extract_emails(text):
    """Extract and clean emails."""
    return {m.lower() for m in EMAIL_RE.findall(text) 
            if "example" not in m and "sentry" not in m and "test" not in m}

def init_chrome():
    """Create Chrome driver."""
    if not SELENIUM_AVAILABLE:
        return None
    try:
        opts = ChromeOptions()
        for arg in ["--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"]:
            opts.add_argument(arg)
        opts.add_argument(f"user-agent={USER_AGENT}")
        return webdriver.Chrome(options=opts)
    except:
        return None

def scrape_multitab(urls, log_fn=None):
    """Open URLs in parallel tabs and extract emails."""
    if not urls or not SELENIUM_AVAILABLE:
        return set()
    
    driver = init_chrome()
    if not driver:
        return set()
    
    emails = set()
    try:
        # Open first URL
        driver.get(urls[0])
        time.sleep(2)
        
        # Open rest in new tabs
        for url in urls[1:]:
            driver.execute_script(f"window.open('{url}')")
            time.sleep(0.5)
        
        time.sleep(3)  # Wait for all to load
        
        # Extract from each tab
        for i in range(len(urls)):
            try:
                driver.switch_to.window(driver.window_handles[i])
                time.sleep(1)
                text = driver.find_element(By.TAG_NAME, "body").text
                found = extract_emails(text)
                emails.update(found)
                if log_fn and found:
                    log_fn(f"      Tab {i+1}: {len(found)} email(s)")
            except:
                pass
    except:
        pass
    finally:
        driver.quit()
    
    return emails

def google_search_urls(query, log_fn=None):
    """Search Google for URLs."""
    if log_fn:
        log_fn(f"  Searching: {query}")
    urls = []
    try:
        resp = requests.get(f"https://www.google.com/search?q={query.replace(' ', '+')}", 
                           headers=HEADERS, timeout=12)
        if log_fn:
            log_fn(f"    HTTP {resp.status_code}")
        
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.startswith("http") and "google" not in href:
                    urls.append(href)
                if len(urls) >= 5:
                    break
    except Exception as e:
        if log_fn:
            log_fn(f"    Error: {str(e)[:40]}")
    
    if log_fn and urls:
        log_fn(f"    Found {len(urls)} URL(s)")
    return urls

def run_scrape_job(job_id, category, city=None, keywords=None, max_results=20):
    """4-source scraping: LinkedIn, Instagram, JustDial, Web"""
    db.update_scrape_job(job_id, status="running")
    log = lambda msg: db.append_scrape_job_log(job_id, msg)
    
    log(f"4-SOURCE SCRAPING: '{category}' in '{city or 'India'}'")
    log("=" * 70)
    
    all_emails = set()
    
    # SOURCE 1: LINKEDIN
    log("\nSOURCE 1: LinkedIn Profiles (Chrome Multi-Tab)")
    log("-" * 70)
    query = f"site:linkedin.com/in {category} {city}" if city else f"site:linkedin.com/in {category}"
    urls = google_search_urls(query, log_fn=log)
    if urls:
        emails = scrape_multitab(urls, log_fn=log)
        all_emails.update(emails)
        log(f"  Result: {len(emails)} emails")
    time.sleep(2)
    
    # SOURCE 2: INSTAGRAM
    log("\nSOURCE 2: Instagram Profiles (Chrome Multi-Tab)")
    log("-" * 70)
    query = f"site:instagram.com {category} {city}" if city else f"site:instagram.com {category}"
    urls = google_search_urls(query, log_fn=log)
    if urls:
        emails = scrape_multitab(urls, log_fn=log)
        all_emails.update(emails)
        log(f"  Result: {len(emails)} emails")
    time.sleep(2)
    
    # SOURCE 3: JUSTDIAL
    log("\nSOURCE 3: JustDial Business Listings (Chrome Multi-Tab)")
    log("-" * 70)
    query = f"site:justdial.com {category} {city}" if city else f"site:justdial.com {category}"
    urls = google_search_urls(query, log_fn=log)
    if urls:
        emails = scrape_multitab(urls, log_fn=log)
        all_emails.update(emails)
        log(f"  Result: {len(emails)} emails")
    time.sleep(2)
    
    # SOURCE 4: WEB (Google Search)
    log("\nSOURCE 4: Web Search (Google)")
    log("-" * 70)
    query = f"{category} {city} email" if city else f"{category} email contact"
    log(f"  Searching: {query}")
    try:
        resp = requests.get(f"https://www.google.com/search?q={query.replace(' ', '+')}", 
                           headers=HEADERS, timeout=12)
        if resp.status_code == 200:
            emails = extract_emails(resp.text)
            all_emails.update(emails)
            log(f"  Result: {len(emails)} emails")
    except:
        log(f"  No results")
    
    # INSERT ALL
    log("\n" + "=" * 70)
    log(f"TOTAL FOUND: {len(all_emails)} unique emails")
    
    inserted = 0
    for email in all_emails:
        try:
            if db.insert_lead(
                email=email,
                source_domain=email.split("@")[-1],
                source_url="",
                source_type="scrape",
                category=category,
                city=city,
                business_name=None,
                mx_valid=1,
            ):
                inserted += 1
                log(f"  ✓ {email}")
        except:
            pass
    
    log("=" * 70)
    log(f"INSERTED: {inserted} new leads")
    log("=" * 70)
    
    db.update_scrape_job(job_id, status="done", finished_at=datetime.utcnow())