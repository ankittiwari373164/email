"""
COMPLETE LEAD SCRAPER WITH MULTI-SOURCE AUTOMATION

Three-phase scraping for educational purposes:
Phase 1: LinkedIn profiles (Selenium + real Chrome browser)
Phase 2: Instagram profiles (Selenium + real Chrome browser)  
Phase 3: Web search + directory harvest

All with detailed logging and error handling.
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

# Try to import Selenium for browser automation
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

CONTACT_LINK_WORDS = ("contact", "about", "reach", "get-in-touch")

DIRECTORY_SITES = [
    "justdial.com",
    "indiamart.com",
    "sulekha.com",
    "yellowpages.in",
]

DIRECTORY_LINK_JUNK = (
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "wa.me", "whatsapp.com", "play.google.com", "apps.apple.com",
    "googleusercontent.com", "gstatic.com", "doubleclick.net", "google.com",
)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def _clean_emails(raw_text):
    """Extract and filter emails from raw text."""
    found = set()
    for m in EMAIL_RE.findall(raw_text):
        email = m.strip().strip(".,;:").lower()
        localpart, domain = email.split("@", 1)
        if domain in JUNK_DOMAINS:
            continue
        if any(sub in domain for sub in JUNK_DOMAIN_SUBSTRINGS):
            continue
        if IMAGE_EXT_RE.search(email):
            continue
        if any(email.startswith(p) for p in JUNK_LOCALPARTS):
            continue
        if HEX_HASH_LOCALPART_RE.match(localpart):
            continue
        found.add(email)
    return found


def _fetch(url):
    """Fetch URL with error handling."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
            return r.text
    except requests.RequestException:
        pass
    return None


def _text_to_html(text):
    """Convert plain text to HTML for email rendering."""
    import html as _html
    escaped = _html.escape(text)
    return "<div style='white-space:pre-wrap;font-family:sans-serif'>" + escaped.replace("\n", "<br>") + "</div>"


# ============================================================================
# SELENIUM BROWSER AUTOMATION
# ============================================================================

def init_chrome_driver():
    """Initialize headless Chrome WebDriver."""
    if not SELENIUM_AVAILABLE:
        return None
    try:
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument(f"user-agent={USER_AGENT}")
        
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        return None


def scrape_linkedin_profile_selenium(profile_url, driver=None, log_fn=None):
    """Use Selenium to scrape LinkedIn profile with JavaScript rendering."""
    if not SELENIUM_AVAILABLE:
        return set(), None
    
    close_driver = False
    if driver is None:
        driver = init_chrome_driver()
        close_driver = True
        if not driver:
            return set(), None
    
    try:
        if log_fn:
            log_fn(f"      [Browser] Loading: {profile_url}")
        
        driver.get(profile_url)
        time.sleep(3)
        
        name = None
        try:
            name = driver.find_element(By.CSS_SELECTOR, "h1").text
        except:
            pass
        
        page_text = driver.find_element(By.TAG_NAME, "body").text
        emails = _clean_emails(page_text)
        
        personal_emails = set()
        for email in emails:
            domain = email.split("@")[-1]
            if any(p in domain for p in ("gmail", "yahoo", "outlook", "hotmail", "protonmail", "icloud")):
                personal_emails.add(email)
            elif domain not in {"linkedin.com", "google.com"}:
                personal_emails.add(email)
        
        if log_fn and personal_emails:
            log_fn(f"        → {len(personal_emails)} email(s): {', '.join(list(personal_emails)[:1])}")
        
        return personal_emails, name
        
    except Exception as e:
        if log_fn:
            log_fn(f"      [Browser] Error: {str(e)[:80]}")
        return set(), None
    finally:
        if close_driver and driver:
            driver.quit()


def scrape_instagram_profile_selenium(profile_url, driver=None, log_fn=None):
    """Use Selenium to scrape Instagram profile with JavaScript rendering."""
    if not SELENIUM_AVAILABLE:
        return set(), None
    
    close_driver = False
    if driver is None:
        driver = init_chrome_driver()
        close_driver = True
        if not driver:
            return set(), None
    
    try:
        if log_fn:
            log_fn(f"      [Browser] Loading: {profile_url}")
        
        driver.get(profile_url)
        time.sleep(3)
        
        username = profile_url.split("instagram.com/")[-1].rstrip("/") if "instagram.com/" in profile_url else None
        
        page_text = driver.find_element(By.TAG_NAME, "body").text
        emails = _clean_emails(page_text)
        
        personal_emails = set()
        for email in emails:
            domain = email.split("@")[-1]
            if any(p in domain for p in ("gmail", "yahoo", "outlook", "hotmail", "protonmail", "icloud")):
                personal_emails.add(email)
            elif domain not in {"instagram.com", "google.com"}:
                personal_emails.add(email)
        
        if log_fn and personal_emails:
            log_fn(f"        → {len(personal_emails)} email(s): {', '.join(list(personal_emails)[:1])}")
        
        return personal_emails, username
        
    except Exception as e:
        if log_fn:
            log_fn(f"      [Browser] Error: {str(e)[:80]}")
        return set(), None
    finally:
        if close_driver and driver:
            driver.quit()


# ============================================================================
# SEARCH BACKENDS (NO SELENIUM)
# ============================================================================

def search_duckduckgo(query, max_results=15, log_fn=None):
    """DuckDuckGo HTML search."""
    urls = []
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if log_fn:
            log_fn(f"    DDG → HTTP {resp.status_code}")
        resp.raise_for_status()
    except Exception as e:
        if log_fn:
            log_fn(f"    DDG → FAIL: {str(e)[:60]}")
        return urls

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.select("a.result__a"):
        href = a.get("href")
        if href:
            urls.append(href)
        if len(urls) >= max_results:
            break

    if log_fn:
        log_fn(f"    DDG → {len(urls)} result(s)")
    return urls[:max_results]


def search_bing(query, max_results=15, log_fn=None):
    """Bing HTML search."""
    urls = []
    try:
        resp = requests.get(
            f"https://www.bing.com/search?q={quote_plus(query)}&count=30",
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if log_fn:
            log_fn(f"    Bing → HTTP {resp.status_code}")
        resp.raise_for_status()
    except Exception as e:
        if log_fn:
            log_fn(f"    Bing → FAIL: {str(e)[:60]}")
        return urls

    soup = BeautifulSoup(resp.text, "html.parser")
    for li in soup.select("li.b_algo h2 a"):
        href = li.get("href")
        if href and href.startswith("http"):
            urls.append(href)
        if len(urls) >= max_results:
            break

    if log_fn:
        log_fn(f"    Bing → {len(urls)} result(s)")
    return urls[:max_results]


def search_linkedin_profiles(query, max_results=10, log_fn=None):
    """Find LinkedIn profiles via site: search."""
    linkedin_query = f"site:linkedin.com {query} email OR gmail OR contact"
    if log_fn:
        log_fn(f"  Searching: site:linkedin.com '{query}'")
    return search_duckduckgo(linkedin_query, max_results, log_fn)


def search_instagram_profiles(query, max_results=10, log_fn=None):
    """Find Instagram profiles via site: search."""
    instagram_query = f"site:instagram.com {query} email OR gmail OR contact"
    if log_fn:
        log_fn(f"  Searching: site:instagram.com '{query}'")
    return search_duckduckgo(instagram_query, max_results, log_fn)


# ============================================================================
# DIRECTORY & WEB SCRAPING
# ============================================================================

def _slugify_for_directory(text):
    return re.sub(r"[^a-zA-Z0-9]+", "-", text.strip()).strip("-")


def build_directory_listing_urls(category, city):
    """Build directory listing URLs."""
    cat_slug = _slugify_for_directory(category)
    city_slug = _slugify_for_directory(city) if city else ""

    urls = []
    if city_slug:
        urls.append(f"https://www.justdial.com/{city_slug}/{cat_slug}")
        urls.append(f"https://dir.indiamart.com/search.mp?ss={quote_plus(category + ' ' + city)}")
        urls.append(f"https://www.sulekha.com/{cat_slug}/{city_slug}")
    else:
        urls.append(f"https://dir.indiamart.com/search.mp?ss={quote_plus(category)}")
    return urls


def harvest_directory_outbound_links(directory_url, max_results=10, log_fn=None):
    """Harvest business links from directory listings."""
    html = _fetch(directory_url)
    if not html:
        if log_fn:
            log_fn(f"    Directory fetch failed: {directory_url}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    directory_domain = urlparse(directory_url).netloc.replace("www.", "")
    found = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        link_domain = urlparse(href).netloc.replace("www.", "")
        if not link_domain or link_domain == directory_domain:
            continue
        if any(j in link_domain for j in DIRECTORY_LINK_JUNK):
            continue
        if link_domain in seen:
            continue
        seen.add(link_domain)
        found.append(href)
        if len(found) >= max_results:
            break

    if log_fn:
        log_fn(f"    Directory harvested {len(found)} link(s)")
    return found


def emails_from_site(url):
    """Extract emails and business name from website."""
    html = _fetch(url)
    if not html:
        return set(), None

    soup = BeautifulSoup(html, "html.parser")
    domain = urlparse(url).netloc
    emails = _clean_emails(html)
    
    business_name = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        if title:
            business_name = title.split("|")[0].split("-")[0].strip()[:120]

    site_root = domain.replace("www.", "")
    kept = {e for e in emails if site_root in e.split("@")[-1]}
    if not kept and emails:
        if any(d in site_root for d in ["justdial", "indiamart", "sulekha"]):
            kept = emails
        else:
            kept = set(list(emails)[:1])

    return kept, business_name


def has_mx_record(domain):
    """Check if domain has MX record."""
    try:
        import dns.resolver
        dns.resolver.resolve(domain, "MX", lifetime=5)
        return True
    except Exception:
        try:
            socket.gethostbyname(domain)
            return True
        except Exception:
            return False


# ============================================================================
# MAIN SCRAPING ORCHESTRATION
# ============================================================================

def run_scrape_job(job_id, category, city=None, keywords=None, max_results=20):
    """Complete three-phase scraping: LinkedIn (Selenium) → Instagram (Selenium) → Web."""
    db.update_scrape_job(job_id, status="running")
    log = lambda msg: db.append_scrape_job_log(job_id, msg)
    log(f"Starting 3-phase scrape: category='{category}' city='{city or ''}'")
    log("=" * 70)

    # ========== PHASE 1: LINKEDIN WITH SELENIUM ==========
    log("\nPhase 1: LinkedIn Profiles (Real Browser)")
    log("-" * 70)
    
    linkedin_emails = set()
    linkedin_checked = 0
    
    try:
        profile_urls = search_linkedin_profiles(f"{category} {city or ''}", max_results=5, log_fn=log)
        if profile_urls:
            log(f"Found {len(profile_urls)} LinkedIn profiles to check")
            driver = init_chrome_driver() if SELENIUM_AVAILABLE else None
            
            for url in profile_urls:
                profile_emails, name = scrape_linkedin_profile_selenium(url, driver=driver, log_fn=log)
                if profile_emails:
                    linkedin_emails.update(profile_emails)
                linkedin_checked += 1
                time.sleep(2)
            
            if driver:
                driver.quit()
    except Exception as e:
        log(f"LinkedIn phase error: {str(e)[:100]}")
    
    log(f"LinkedIn result: {len(linkedin_emails)} emails from {linkedin_checked} profiles")

    # ========== PHASE 2: INSTAGRAM WITH SELENIUM ==========
    log("\nPhase 2: Instagram Profiles (Real Browser)")
    log("-" * 70)
    
    instagram_emails = set()
    instagram_checked = 0
    
    try:
        profile_urls = search_instagram_profiles(f"{category} {city or ''}", max_results=5, log_fn=log)
        if profile_urls:
            log(f"Found {len(profile_urls)} Instagram profiles to check")
            driver = init_chrome_driver() if SELENIUM_AVAILABLE else None
            
            for url in profile_urls:
                profile_emails, username = scrape_instagram_profile_selenium(url, driver=driver, log_fn=log)
                if profile_emails:
                    instagram_emails.update(profile_emails)
                instagram_checked += 1
                time.sleep(2)
            
            if driver:
                driver.quit()
    except Exception as e:
        log(f"Instagram phase error: {str(e)[:100]}")
    
    log(f"Instagram result: {len(instagram_emails)} emails from {instagram_checked} profiles")

    # ========== PHASE 3: WEB SEARCH & DIRECTORIES ==========
    log("\nPhase 3: Web Search & Directories")
    log("-" * 70)
    
    collected_urls = []
    seen_domains = set()
    
    # Try directories first
    log("Harvesting from business directories...")
    for dir_url in build_directory_listing_urls(category, city):
        try:
            links = harvest_directory_outbound_links(dir_url, max_results=5, log_fn=log)
            for link in links:
                domain = urlparse(link).netloc
                if domain and domain not in seen_domains:
                    seen_domains.add(domain)
                    collected_urls.append(link)
        except Exception as e:
            if log:
                log(f"    Directory error: {str(e)[:60]}")
        time.sleep(PAGE_FETCH_DELAY)
    
    # Then search engines
    log("Searching web for business websites...")
    variants = [
        f"{category} {city} contact email" if city else f"{category} contact email",
        f"{category} {city} email address" if city else f"{category} email address",
    ]
    
    for query in variants:
        if len(collected_urls) >= max_results:
            break
        for search_fn in [search_duckduckgo, search_bing]:
            results = search_fn(query, max_results=10, log_fn=log)
            for url in results:
                domain = urlparse(url).netloc
                if domain and domain not in seen_domains:
                    seen_domains.add(domain)
                    collected_urls.append(url)
                if len(collected_urls) >= max_results:
                    break
            time.sleep(SEARCH_DELAY)
    
    log(f"Web search collected {len(collected_urls)} candidate sites")

    # ========== EMAIL EXTRACTION FROM WEBSITES ==========
    web_emails = set()
    sites_checked = 0
    mx_cache = {}
    
    log("\nExtracting emails from websites...")
    for url in collected_urls:
        sites_checked += 1
        domain = urlparse(url).netloc
        try:
            found_emails, business_name = emails_from_site(url)
            if found_emails:
                web_emails.update(found_emails)
                log(f"  {domain}: {len(found_emails)} email(s)")
        except Exception as e:
            pass
        time.sleep(PAGE_FETCH_DELAY)
    
    log(f"Web scraping: {len(web_emails)} emails from {sites_checked} websites")

    # ========== INSERT ALL EMAILS INTO DATABASE ==========
    log("\nInserting leads into database...")
    total_inserted = 0
    
    all_emails = {
        "linkedin": linkedin_emails,
        "instagram": instagram_emails,
        "web": web_emails,
    }
    
    for source, emails in all_emails.items():
        for email in emails:
            edomain = email.split("@")[-1]
            if edomain not in mx_cache:
                mx_cache[edomain] = has_mx_record(edomain)
            mx_ok = mx_cache[edomain]
            
            source_domain = edomain if source == "web" else source + ".com"
            source_url = f"https://{source_domain}" if source != "web" else ""
            
            inserted = db.insert_lead(
                email=email,
                source_domain=source_domain,
                source_url=source_url,
                source_type=source,
                category=category,
                city=city,
                business_name=None,
                mx_valid=1 if mx_ok else 0,
            )
            if inserted:
                total_inserted += 1
    
    # ========== FINAL SUMMARY ==========
    log("\n" + "=" * 70)
    log("SCRAPE COMPLETE")
    log("=" * 70)
    log(f"LinkedIn:  {len(linkedin_emails)} emails from {linkedin_checked} profiles")
    log(f"Instagram: {len(instagram_emails)} emails from {instagram_checked} profiles")
    log(f"Web:       {len(web_emails)} emails from {sites_checked} websites")
    log(f"TOTAL:     {len(linkedin_emails) + len(instagram_emails) + len(web_emails)} emails found")
    log(f"INSERTED:  {total_inserted} new leads to database")
    log("=" * 70)
    
    db.update_scrape_job(job_id, status="done", finished_at=datetime.utcnow())