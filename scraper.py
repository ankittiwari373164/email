"""PRODUCTION EMAIL SCRAPER - Multi-Source with Google Parse"""
import re, time
from urllib.parse import urlparse, parse_qs
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import config, db

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}

# Email extraction - strict but comprehensive
EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
JUNK = {"example.com", "sentry.io", "wixpress.com", "test.com", "yourdomain.com", "domain.com"}

def clean_emails(text):
    """Extract and filter emails from text"""
    found = set()
    for match in EMAIL_RE.finditer(text):
        email = match.group(0).lower()
        domain = email.split("@")[-1]
        
        # Skip junk
        if domain in JUNK or any(x in domain for x in ["sentry", "wixpress", "example"]):
            continue
        if email.startswith(("noreply", "no-reply", "postmaster", "abuse")):
            continue
        
        found.add(email)
    
    return found

def google_search_and_extract(query, log_fn=None):
    """Search Google, extract emails from snippets AND page content"""
    if log_fn:
        log_fn(f"  Query: {query}")
    
    emails = set()
    
    try:
        # Search Google
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        resp = requests.get(search_url, headers=HEADERS, timeout=15)
        
        if log_fn:
            log_fn(f"    HTTP {resp.status_code}")
        
        if resp.status_code != 200:
            return emails
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Method 1: Extract from search result snippets (most reliable)
        for div in soup.find_all("div", {"class": ["g", "VwiC3b"]}):
            # Get snippet text
            snippet = div.get_text()
            found = clean_emails(snippet)
            emails.update(found)
        
        # Method 2: Extract from all text if Method 1 didn't work
        if not emails:
            all_text = soup.get_text()
            found = clean_emails(all_text)
            emails.update(found)
        
        if log_fn and emails:
            log_fn(f"    ✓ Found {len(emails)} email(s)")
        elif log_fn:
            log_fn(f"    ○ No emails in results")
    
    except Exception as e:
        if log_fn:
            log_fn(f"    ✗ Error: {str(e)[:50]}")
    
    return emails

def run_scrape_job(job_id, category, city=None, keywords=None, max_results=20):
    """4-source email extraction"""
    db.update_scrape_job(job_id, status="running")
    log = lambda msg: db.append_scrape_job_log(job_id, msg)
    
    log(f"{'='*70}")
    log(f"4-SOURCE EMAIL SCRAPING")
    log(f"Category: '{category}' | City: '{city or 'India'}'")
    log(f"{'='*70}")
    
    all_emails = set()
    
    # SOURCE 1: LinkedIn
    log(f"\n[1/4] LinkedIn Profiles")
    log(f"{'-'*70}")
    q = f'site:linkedin.com/in "{category}" "{city}"' if city else f'site:linkedin.com/in "{category}"'
    emails = google_search_and_extract(q, log_fn=log)
    all_emails.update(emails)
    if emails:
        log(f"  FOUND: {len(emails)} emails")
    time.sleep(2)
    
    # SOURCE 2: Instagram
    log(f"\n[2/4] Instagram Business Accounts")
    log(f"{'-'*70}")
    q = f'site:instagram.com "{category}" "{city}" @' if city else f'site:instagram.com "{category}"'
    emails = google_search_and_extract(q, log_fn=log)
    all_emails.update(emails)
    if emails:
        log(f"  FOUND: {len(emails)} emails")
    time.sleep(2)
    
    # SOURCE 3: JustDial
    log(f"\n[3/4] JustDial Business Directory")
    log(f"{'-'*70}")
    q = f'site:justdial.com "{category}" "{city}"' if city else f'site:justdial.com "{category}"'
    emails = google_search_and_extract(q, log_fn=log)
    all_emails.update(emails)
    if emails:
        log(f"  FOUND: {len(emails)} emails")
    time.sleep(2)
    
    # SOURCE 4: General Web
    log(f"\n[4/4] General Web Search")
    log(f"{'-'*70}")
    q = f'"{category}" "{city}" email contact' if city else f'"{category}" email contact'
    emails = google_search_and_extract(q, log_fn=log)
    all_emails.update(emails)
    if emails:
        log(f"  FOUND: {len(emails)} emails")
    
    # INSERT TO DATABASE
    log(f"\n{'='*70}")
    log(f"TOTAL UNIQUE EMAILS: {len(all_emails)}")
    log(f"{'='*70}")
    
    inserted = 0
    failed = 0
    
    for email in sorted(all_emails):
        try:
            domain = email.split("@")[-1]
            result = db.insert_lead(
                email=email,
                source_domain=domain,
                source_url="",
                source_type="scrape",
                category=category,
                city=city,
                business_name=None,
                mx_valid=1,
            )
            if result:
                inserted += 1
                log(f"  ✓ {email}")
            else:
                failed += 1
        except Exception as e:
            failed += 1
    
    log(f"\n{'='*70}")
    log(f"RESULTS:")
    log(f"  Found: {len(all_emails)} emails")
    log(f"  Inserted: {inserted} new leads")
    if failed > 0:
        log(f"  Duplicates/Failed: {failed}")
    log(f"{'='*70}")
    
    db.update_scrape_job(job_id, status="done", finished_at=datetime.utcnow())