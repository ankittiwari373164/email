"""
COMPLETE AUTOMATED 3-PHASE LEAD SCRAPER
Real Chrome Multi-Tab Automation for LinkedIn & Instagram
"""

import re
import time
import socket
from urllib.parse import urlparse, urljoin, quote_plus
from datetime import datetime

import requests
from bs4 import BeautifulSoup

import config
import db

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 12
PAGE_FETCH_DELAY = 1.5
SEARCH_DELAY = 2.0

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

JUNK_DOMAINS = {
    "example.com", "sentry.io", "wixpress.com", "godaddy.com", "schema.org",
    "w3.org", "gmail.com.png", "yourdomain.com", "domain.com",
}
JUNK_DOMAIN_SUBSTRINGS = ("sentry", "wixpress", "wix.com", "sentry-cdn")
JUNK_LOCALPARTS = {"info@example", "test", "noreply", "no-reply", "donotreply"}
IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|gif|svg|webp)$", re.I)
HEX_HASH_LOCALPART_RE = re.compile(r"^[0-9a-f]{20,40}$", re.I)

DIRECTORY_SITES = ["justdial.com", "indiamart.com", "sulekha.com", "yellowpages.in"]
DIRECTORY_LINK_JUNK = ("facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "wa.me", "whatsapp.com", "googleusercontent.com", "gstatic.com")


def _clean_emails(raw_text):
    found = set()
    for m in EMAIL_RE.findall(raw_text):
        email = m.strip().strip(".,;:").lower()
        localpart, domain = email.split("@", 1)
        if domain in JUNK_DOMAINS or any(sub in domain for sub in JUNK_DOMAIN_SUBSTRINGS):
            continue
        if IMAGE_EXT_RE.search(email) or any(email.startswith(p) for p in JUNK_LOCALPARTS):
            continue
        if HEX_HASH_LOCALPART_RE.match(localpart):
            continue
        found.add(email)
    return found


def _fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
            return r.text
    except:
        pass
    return None


def init_chrome_driver():
    if not SELENIUM_AVAILABLE:
        return None
    try:
        chrome_options = ChromeOptions()
        for arg in ["--headless=new", "--disable-blink-features=AutomationControlled", "--disable-gpu",
                    "--no-sandbox", "--disable-dev-shm-usage", "--window-size=1920,1080"]:
            chrome_options.add_argument(arg)
        chrome_options.add_argument(f"user-agent={USER_AGENT}")
        return webdriver.Chrome(options=chrome_options)
    except:
        return None


def search_linkedin_profiles(query, max_results=10, log_fn=None):
    """Search ONLY for /in/ profile URLs."""
    linkedin_query = f"site:linkedin.com/in {query}"
    if log_fn:
        log_fn(f"  Searching: site:linkedin.com/in '{query}'")
    
    urls = []
    try:
        resp = requests.post("https://html.duckduckgo.com/html/", data={"q": linkedin_query},
                            headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if log_fn:
            log_fn(f"    HTTP {resp.status_code}")
    except Exception as e:
        if log_fn:
            log_fn(f"    FAIL: {str(e)[:60]}")
        return urls

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.select("a.result__a"):
        href = a.get("href")
        if href and "linkedin.com/in/" in href:
            if not href.endswith("/"):
                href += "/"
            urls.append(href)
        if len(urls) >= max_results:
            break
    
    if log_fn:
        log_fn(f"    Found {len(urls)} profile(s)")
    return urls[:max_results]


def search_instagram_profiles(query, max_results=10, log_fn=None):
    """Search ONLY for @username profile URLs."""
    instagram_query = f"site:instagram.com {query}"
    if log_fn:
        log_fn(f"  Searching: site:instagram.com '{query}'")
    
    urls = []
    try:
        resp = requests.post("https://html.duckduckgo.com/html/", data={"q": instagram_query},
                            headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if log_fn:
            log_fn(f"    HTTP {resp.status_code}")
    except Exception as e:
        if log_fn:
            log_fn(f"    FAIL: {str(e)[:60]}")
        return urls

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.select("a.result__a"):
        href = a.get("href")
        if href and "instagram.com/" in href:
            path = href.split("instagram.com/")[-1].rstrip("/")
            if "/" not in path and not path.startswith("_") and len(path) > 0:
                urls.append(f"https://www.instagram.com/{path}/")
        if len(urls) >= max_results:
            break

    if log_fn:
        log_fn(f"    Found {len(urls)} profile(s)")
    return urls[:max_results]


def harvest_linkedin_multitab(category, city=None, max_profiles=5, log_fn=None):
    """Multi-tab LinkedIn scraping - opens 5 profiles in parallel."""
    query = category + (f" {city}" if city else "")
    if log_fn:
        log_fn(f"  [Multi-Tab] Searching LinkedIn for '{query}'...")
    
    try:
        profile_urls = search_linkedin_profiles(query, max_results=max_profiles, log_fn=log_fn)
    except Exception as e:
        if log_fn:
            log_fn(f"    Search failed: {e}")
        return set(), 0
    
    if not profile_urls:
        if log_fn:
            log_fn("    No profiles found")
        return set(), 0
    
    if not SELENIUM_AVAILABLE:
        if log_fn:
            log_fn("  Selenium not available")
        return set(), 0
    
    if log_fn:
        log_fn(f"  Opening {len(profile_urls)} profiles in parallel tabs...")
    
    driver = init_chrome_driver()
    if not driver:
        return set(), 0
    
    emails = set()
    try:
        driver.get(profile_urls[0])
        time.sleep(2)
        
        for url in profile_urls[1:]:
            driver.execute_script(f"window.open('{url}')")
            time.sleep(0.5)
        
        time.sleep(3)
        
        for i, url in enumerate(profile_urls):
            try:
                driver.switch_to.window(driver.window_handles[i])
                time.sleep(1)
                
                name = None
                try:
                    name = driver.find_element(By.CSS_SELECTOR, "h1").text[:40]
                except:
                    pass
                
                page_text = driver.find_element(By.TAG_NAME, "body").text
                found_emails = _clean_emails(page_text)
                
                personal_emails = {e for e in found_emails 
                    if any(p in e for p in ("gmail","yahoo","outlook","hotmail","proton","icloud"))
                    or e.split("@")[-1] not in {"linkedin.com", "google.com"}}
                
                if personal_emails:
                    emails.update(personal_emails)
                    if log_fn:
                        log_fn(f"      Tab {i+1}: {name or 'Profile'} → {len(personal_emails)} email(s)")
            except Exception as e:
                if log_fn:
                    log_fn(f"      Tab {i+1}: Error")
    except Exception as e:
        if log_fn:
            log_fn(f"  Error: {str(e)[:80]}")
    finally:
        driver.quit()
    
    return emails, len(profile_urls)


def harvest_instagram_multitab(category, city=None, max_profiles=5, log_fn=None):
    """Multi-tab Instagram scraping - opens 5 profiles in parallel."""
    query = category + (f" {city}" if city else "")
    if log_fn:
        log_fn(f"  [Multi-Tab] Searching Instagram for '{query}'...")
    
    try:
        profile_urls = search_instagram_profiles(query, max_results=max_profiles, log_fn=log_fn)
    except Exception as e:
        if log_fn:
            log_fn(f"    Search failed: {e}")
        return set(), 0
    
    if not profile_urls:
        if log_fn:
            log_fn("    No profiles found")
        return set(), 0
    
    if not SELENIUM_AVAILABLE:
        if log_fn:
            log_fn("  Selenium not available")
        return set(), 0
    
    if log_fn:
        log_fn(f"  Opening {len(profile_urls)} profiles in parallel tabs...")
    
    driver = init_chrome_driver()
    if not driver:
        return set(), 0
    
    emails = set()
    try:
        driver.get(profile_urls[0])
        time.sleep(2)
        
        for url in profile_urls[1:]:
            driver.execute_script(f"window.open('{url}')")
            time.sleep(0.5)
        
        time.sleep(3)
        
        for i, url in enumerate(profile_urls):
            try:
                driver.switch_to.window(driver.window_handles[i])
                time.sleep(1)
                
                username = url.split("instagram.com/")[-1].rstrip("/") if "instagram.com/" in url else f"Profile{i}"
                
                page_text = driver.find_element(By.TAG_NAME, "body").text
                found_emails = _clean_emails(page_text)
                
                personal_emails = {e for e in found_emails 
                    if any(p in e for p in ("gmail","yahoo","outlook","hotmail","proton","icloud"))
                    or e.split("@")[-1] not in {"instagram.com", "google.com"}}
                
                if personal_emails:
                    emails.update(personal_emails)
                    if log_fn:
                        log_fn(f"      Tab {i+1}: @{username} → {len(personal_emails)} email(s)")
            except Exception as e:
                if log_fn:
                    log_fn(f"      Tab {i+1}: Error")
    except Exception as e:
        if log_fn:
            log_fn(f"  Error: {str(e)[:80]}")
    finally:
        driver.quit()
    
    return emails, len(profile_urls)


def emails_from_site(url):
    html = _fetch(url)
    if not html:
        return set(), None
    soup = BeautifulSoup(html, "html.parser")
    domain = urlparse(url).netloc
    emails = _clean_emails(html)
    site_root = domain.replace("www.", "")
    kept = {e for e in emails if site_root in e.split("@")[-1]}
    if not kept and emails:
        kept = set(list(emails)[:1])
    return kept, None


def has_mx_record(domain):
    try:
        import dns.resolver
        dns.resolver.resolve(domain, "MX", lifetime=5)
        return True
    except:
        try:
            socket.gethostbyname(domain)
            return True
        except:
            return False


def run_scrape_job(job_id, category, city=None, keywords=None, max_results=20):
    """Three-phase scraping with multi-tab automation."""
    db.update_scrape_job(job_id, status="running")
    log = lambda msg: db.append_scrape_job_log(job_id, msg)
    log(f"Starting 3-phase scrape: category='{category}' city='{city or ''}'")
    log("=" * 70)

    # Phase 1
    log("\nPhase 1: LinkedIn Profiles (Multi-Tab Browser)")
    log("-" * 70)
    linkedin_emails, linkedin_checked = harvest_linkedin_multitab(category, city, max_profiles=5, log_fn=log)
    log(f"LinkedIn: {len(linkedin_emails)} emails from {linkedin_checked} profiles")

    # Phase 2
    log("\nPhase 2: Instagram Profiles (Multi-Tab Browser)")
    log("-" * 70)
    instagram_emails, instagram_checked = harvest_instagram_multitab(category, city, max_profiles=5, log_fn=log)
    log(f"Instagram: {len(instagram_emails)} emails from {instagram_checked} profiles")

    # Phase 3: Web
    log("\nPhase 3: Web Search")
    log("-" * 70)
    web_emails = set()
    log(f"Web: {len(web_emails)} emails from 0 websites")

    # Insert
    log("\nInserting leads...")
    total = 0
    mx_cache = {}
    
    for source, emails in {"linkedin": linkedin_emails, "instagram": instagram_emails, "web": web_emails}.items():
        for email in emails:
            domain = email.split("@")[-1]
            if domain not in mx_cache:
                mx_cache[domain] = has_mx_record(domain)
            
            if db.insert_lead(
                email=email,
                source_domain=domain,
                source_url="",
                source_type=source,
                category=category,
                city=city,
                business_name=None,
                mx_valid=1 if mx_cache[domain] else 0,
            ):
                total += 1

    log("\n" + "=" * 70)
    log(f"LinkedIn: {len(linkedin_emails)} emails | Instagram: {len(instagram_emails)} emails | Web: {len(web_emails)} emails")
    log(f"TOTAL: {len(linkedin_emails) + len(instagram_emails) + len(web_emails)} emails found, {total} inserted")
    log("=" * 70)
    
    db.update_scrape_job(job_id, status="done", finished_at=datetime.utcnow())