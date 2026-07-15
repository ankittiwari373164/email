"""WORKING EMAIL SCRAPER - Direct Regex Extraction"""
import re, time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import config, db

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
HEADERS = {"User-Agent": USER_AGENT}

# STRONG email regex - matches what you see in Google results
EMAIL_RE = re.compile(
    r'(?:^|[^a-zA-Z0-9._%+-])'  # Start or non-email char before
    r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'  # Email
    r'(?:[^a-zA-Z0-9._%+-]|$)',  # End or non-email char after
    re.MULTILINE | re.IGNORECASE
)

JUNK_DOMAINS = {
    "example.com", "sentry.io", "wixpress.com", "test.com", 
    "yourdomain.com", "domain.com", "mail.google.com", "gmail.com.png"
}

def extract_all_emails(text):
    """Extract ALL emails from text using multiple strategies"""
    emails = set()
    
    # Strategy 1: Strong regex
    for match in EMAIL_RE.finditer(text):
        email = match.group(1).lower().strip()
        if email and "@" in email:
            emails.add(email)
    
    # Strategy 2: Simple split on @ (catches emails in any format)
    parts = text.split("@")
    if len(parts) > 1:
        for i in range(len(parts) - 1):
            # Get text before @
            before = parts[i].split()[-1] if parts[i].split() else ""
            # Get text after @
            after = parts[i + 1].split()[0] if parts[i + 1].split() else ""
            
            if before and after and len(after) > 2:
                potential = f"{before}@{after}".lower()
                # Validate it looks like email
                if len(before) >= 2 and "." in after:
                    emails.add(potential)
    
    # Filter junk
    clean = set()
    for email in emails:
        if not email or "@" not in email:
            continue
        
        domain = email.split("@")[-1]
        
        # Skip obvious junk
        if domain in JUNK_DOMAINS or any(x in domain for x in ["sentry", "wixpress", "example"]):
            continue
        if email.startswith(("noreply", "no-reply", "postmaster", "abuse", "test")):
            continue
        
        clean.add(email)
    
    return clean

def google_search(query, log_fn=None):
    """Search Google and extract emails from raw HTML"""
    if log_fn:
        log_fn(f"  {query}")
    
    emails = set()
    
    try:
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        
        if log_fn:
            log_fn(f"    HTTP {resp.status_code}")
        
        if resp.status_code != 200:
            return emails
        
        # Get raw HTML text
        html_text = resp.text
        
        # Extract emails directly from HTML
        emails = extract_all_emails(html_text)
        
        if log_fn and emails:
            log_fn(f"    ✓ Found: {', '.join(list(emails)[:3])}" + (f" +{len(emails)-3} more" if len(emails) > 3 else ""))
        elif log_fn:
            log_fn(f"    ○ No emails found")
    
    except Exception as e:
        if log_fn:
            log_fn(f"    ✗ Error: {str(e)[:40]}")
    
    return emails

def run_scrape_job(job_id, category, city=None, keywords=None, max_results=20):
    """Run 4-source scraping"""
    db.update_scrape_job(job_id, status="running")
    log = lambda msg: db.append_scrape_job_log(job_id, msg)
    
    log("="*70)
    log(f"4-SOURCE EMAIL SCRAPING: '{category}' in '{city or 'India'}'")
    log("="*70)
    
    all_emails = set()
    
    # SOURCE 1: LinkedIn
    log("\n[SOURCE 1] LinkedIn Profiles")
    log("-"*70)
    q1 = f'site:linkedin.com "{category}" "{city}" gmail' if city else f'site:linkedin.com "{category}" gmail'
    e1 = google_search(q1, log_fn=log)
    all_emails.update(e1)
    log(f"  Result: {len(e1)} emails\n")
    time.sleep(2)
    
    # SOURCE 2: Instagram
    log("[SOURCE 2] Instagram Accounts")
    log("-"*70)
    q2 = f'site:instagram.com "{category}" "{city}" gmail' if city else f'site:instagram.com "{category}" gmail'
    e2 = google_search(q2, log_fn=log)
    all_emails.update(e2)
    log(f"  Result: {len(e2)} emails\n")
    time.sleep(2)
    
    # SOURCE 3: JustDial
    log("[SOURCE 3] JustDial Listings")
    log("-"*70)
    q3 = f'site:justdial.com "{category}" "{city}"' if city else f'site:justdial.com "{category}"'
    e3 = google_search(q3, log_fn=log)
    all_emails.update(e3)
    log(f"  Result: {len(e3)} emails\n")
    time.sleep(2)
    
    # SOURCE 4: Web
    log("[SOURCE 4] Web Search")
    log("-"*70)
    q4 = f'"{category}" "{city}" email contact' if city else f'"{category}" email contact'
    e4 = google_search(q4, log_fn=log)
    all_emails.update(e4)
    log(f"  Result: {len(e4)} emails\n")
    
    # INSERT
    log("="*70)
    log(f"TOTAL FOUND: {len(all_emails)} unique emails")
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
    log(f"INSERTED: {inserted} new leads")
    log("="*70)
    
    db.update_scrape_job(job_id, status="done", finished_at=datetime.utcnow())