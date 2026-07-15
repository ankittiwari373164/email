"""Direct email extraction from Google search results"""
import re, time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import config, db

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
HEADERS = {"User-Agent": USER_AGENT}
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

def extract_emails(text):
    return {m.lower() for m in EMAIL_RE.findall(text) 
            if "example" not in m and "sentry" not in m}

def search_and_extract(query, log_fn=None):
    if log_fn: log_fn(f"  {query}")
    try:
        resp = requests.get(f"https://www.google.com/search?q={query.replace(' ','+')}", 
                           headers=HEADERS, timeout=12)
        if log_fn: log_fn(f"    HTTP {resp.status_code}")
        if resp.status_code == 200:
            emails = extract_emails(resp.text)
            if log_fn and emails: log_fn(f"    → {len(emails)} email(s)")
            return emails
    except Exception as e:
        if log_fn: log_fn(f"    ✗ {str(e)[:40]}")
    return set()

def run_scrape_job(job_id, category, city=None, keywords=None, max_results=20):
    db.update_scrape_job(job_id, status="running")
    log = lambda msg: db.append_scrape_job_log(job_id, msg)
    
    log(f"Extracting emails: '{category}' {f'in {city}' if city else ''}")
    log("=" * 60)
    
    all_emails = set()
    queries = [
        f"{category} {city} email" if city else f"{category} email",
        f'"{category}" "{city}" gmail.com' if city else f'"{category}" gmail.com',
        f'site:linkedin.com "{category}" "{city}"' if city else f'site:linkedin.com "{category}"',
        f'site:instagram.com "{category}" "{city}"' if city else f'site:instagram.com "{category}"',
    ]
    
    for query in queries:
        log(f"\n{query}")
        emails = search_and_extract(query, log_fn=log)
        all_emails.update(emails)
        time.sleep(2)
    
    log("\n" + "=" * 60)
    inserted = sum(1 for email in all_emails if db.insert_lead(
        email=email, source_domain=email.split("@")[-1], source_url="",
        source_type="google", category=category, city=city, 
        business_name=None, mx_valid=1))
    
    log(f"Found: {len(all_emails)} | Inserted: {inserted}")
    log("=" * 60)
    db.update_scrape_job(job_id, status="done", finished_at=datetime.utcnow())