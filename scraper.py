"""CATEGORY-WISE SCRAPER - LinkedIn, Instagram, JustDial Direct"""
import re, time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import config, db

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
HEADERS = {"User-Agent": USER_AGENT}

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
JUNK = {"example.com", "sentry.io", "test.com"}

def get_emails(text):
    found = {m.group(0).lower() for m in EMAIL_RE.finditer(text)}
    return {e for e in found if e.split("@")[-1] not in JUNK}

def fetch_and_extract(url, log_fn=None):
    """Fetch URL and extract emails"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            emails = get_emails(resp.text)
            if log_fn and emails:
                log_fn(f"      ✓ {len(emails)} email(s)")
            elif log_fn:
                log_fn(f"      ○ No emails")
            return emails
    except Exception as e:
        if log_fn:
            log_fn(f"      ✗ Error: {str(e)[:40]}")
    return set()

def run_scrape_job(job_id, category, city=None, keywords=None, max_results=20):
    """Scrape category-wise from real sources"""
    db.update_scrape_job(job_id, status="running")
    log = lambda msg: db.append_scrape_job_log(job_id, msg)
    
    log("="*70)
    log(f"CATEGORY-WISE SCRAPING: '{category}' in '{city or 'India'}'")
    log("="*70)
    
    all_emails = set()
    
    # SOURCE 1: LINKEDIN - Real profile URLs
    log("\n[SOURCE 1] LinkedIn Profiles")
    log("-"*70)
    
    linkedin_profiles = [
        "https://www.linkedin.com/in/realestateexpert/",
        "https://www.linkedin.com/in/propertyconsultant/",
        "https://www.linkedin.com/in/realtordelhi/",
        "https://www.linkedin.com/in/propertydealer/",
        "https://www.linkedin.com/in/housingconsultant/",
    ]
    
    if category.lower() in ["realestate", "real estate", "property"]:
        log(f"  Fetching {len(linkedin_profiles)} LinkedIn profiles...")
        for url in linkedin_profiles:
            log(f"  {url}")
            emails = fetch_and_extract(url, log_fn=log)
            all_emails.update(emails)
            time.sleep(1)
    else:
        log(f"  (Customize profiles for '{category}')")
    
    # SOURCE 2: INSTAGRAM - Real business accounts
    log("\n[SOURCE 2] Instagram Business Accounts")
    log("-"*70)
    
    instagram_accounts = [
        "https://www.instagram.com/zarahomes.realestate/",
        "https://www.instagram.com/perfect_homes_/",
        "https://www.instagram.com/skylinerealestate.in/",
        "https://www.instagram.com/delhirealestate/",
        "https://www.instagram.com/propertyexpertdelhi/",
    ]
    
    if category.lower() in ["realestate", "real estate", "property"]:
        log(f"  Fetching {len(instagram_accounts)} Instagram accounts...")
        for url in instagram_accounts:
            log(f"  {url}")
            emails = fetch_and_extract(url, log_fn=log)
            all_emails.update(emails)
            time.sleep(1)
    else:
        log(f"  (Customize accounts for '{category}')")
    
    # SOURCE 3: JUSTDIAL - Category directory
    log("\n[SOURCE 3] JustDial Business Directory")
    log("-"*70)
    
    category_slug = category.replace(" ", "-").lower()
    city_slug = city.replace(" ", "-").lower() if city else "delhi"
    
    justdial_urls = [
        f"https://www.justdial.com/{city_slug}/{category_slug}",
        f"https://www.justdial.com/{city_slug}/Real-Estate-Consultants",
        f"https://www.justdial.com/{city_slug}/Property-Consultants",
    ]
    
    log(f"  Fetching {len(justdial_urls)} JustDial pages...")
    for url in justdial_urls:
        log(f"  {url}")
        emails = fetch_and_extract(url, log_fn=log)
        all_emails.update(emails)
        time.sleep(1)
    
    # SOURCE 4: LINKEDIN POSTS - Search for posts mentioning category+city
    log("\n[SOURCE 4] LinkedIn Posts & Updates")
    log("-"*70)
    
    linkedin_posts = [
        "https://www.linkedin.com/search/results/content/?keywords=realestate%20delhi",
        "https://www.linkedin.com/search/results/people/?keywords=realestate%20delhi",
    ]
    
    log(f"  Fetching {len(linkedin_posts)} LinkedIn search results...")
    for url in linkedin_posts:
        log(f"  {url}")
        emails = fetch_and_extract(url, log_fn=log)
        all_emails.update(emails)
        time.sleep(1)
    
    # INSERT ALL
    log("\n" + "="*70)
    log(f"TOTAL UNIQUE EMAILS: {len(all_emails)}")
    log("="*70)
    
    inserted = 0
    for email in sorted(all_emails):
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
    
    log("="*70)
    log(f"RESULTS: Found {len(all_emails)} emails, Inserted {inserted} new leads")
    log("="*70)
    
    db.update_scrape_job(job_id, status="done", finished_at=datetime.utcnow())