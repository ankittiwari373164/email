"""
Category-driven lead scraper.

Flow, given a category (+ optional city / extra keywords) typed into the
dashboard:
  1. Build a search query and pull result URLs from DuckDuckGo's HTML
     endpoint (no API key needed).
  2. Visit each result site (homepage + a "contact/about" page if we can
     find one), pull out any email addresses on the page.
  3. Skip anything that's obviously not a real contact address (images,
     example.com, wixpress/sentry-style noise, etc).
  4. MX-check the domain so `leads.mx_valid` is accurate before anything
     ever gets emailed.
  5. Insert into the Supabase `leads` table (deduped by email, via db.insert_lead —
     the email column has a UNIQUE constraint so this is a global de-dupe,
     not just per-run).

Runs in a background thread kicked off from app.py; progress is written to
the `scrape_jobs` row so the dashboard can poll it.

Respect the sites you're crawling: this only reads publicly served pages
(no login walls, no bypassing robots/captchas), uses a normal desktop
user-agent, and paces requests. You're responsible for making sure your use
of any addresses you collect this way complies with the anti-spam law in
your and your recipients' jurisdictions (CAN-SPAM, DPDP, GDPR/PECR, etc) —
the sender.py footer + unsubscribe link handles the outgoing-email side of
that, but consent/legitimate-interest requirements for *collecting* the
address are on you to check per source.
"""
import re
import time
import socket
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

import db

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": USER_AGENT}
REQUEST_TIMEOUT = 10
PAGE_FETCH_DELAY = 1.5  # seconds between site fetches — be a polite crawler

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Domains / patterns that show up constantly but are never real leads
JUNK_DOMAINS = {
    "example.com", "sentry.io", "wixpress.com", "godaddy.com", "schema.org",
    "w3.org", "gmail.com.png", "yourdomain.com", "domain.com",
}
JUNK_LOCALPARTS = {"info@example", "test", "noreply", "no-reply", "donotreply"}
IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|gif|svg|webp)$", re.I)

CONTACT_LINK_WORDS = ("contact", "about", "reach", "get-in-touch")


def _clean_emails(raw_text):
    found = set()
    for m in EMAIL_RE.findall(raw_text):
        email = m.strip().strip(".,;:").lower()
        domain = email.split("@")[-1]
        if domain in JUNK_DOMAINS:
            continue
        if IMAGE_EXT_RE.search(email):
            continue
        if any(email.startswith(p) for p in JUNK_LOCALPARTS):
            continue
        found.add(email)
    return found


def search_duckduckgo(query, max_results=20):
    """Return a list of result URLs for `query` using DuckDuckGo's
    no-JS HTML endpoint (works without an API key)."""
    urls = []
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return urls

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.select("a.result__a"):
        href = a.get("href")
        if href:
            urls.append(href)
        if len(urls) >= max_results:
            break

    # Fallback selector in case DDG markup changes
    if not urls:
        for a in soup.select("a[href^='http']"):
            href = a.get("href")
            if href and "duckduckgo.com" not in href:
                urls.append(href)
            if len(urls) >= max_results:
                break

    return urls[:max_results]


def _fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
            return r.text
    except requests.RequestException:
        pass
    return None


def _find_contact_page(base_url, soup):
    for a in soup.find_all("a", href=True):
        text = (a.get_text() or "").lower()
        href = a["href"].lower()
        if any(w in text for w in CONTACT_LINK_WORDS) or any(w in href for w in CONTACT_LINK_WORDS):
            return urljoin(base_url, a["href"])
    return None


def _business_name_from(soup, fallback_domain):
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        if title:
            return title.split("|")[0].split("-")[0].strip()[:120]
    return fallback_domain


def emails_from_site(url):
    """Visit a site's homepage (+ contact page if found) and return
    (emails:set, business_name:str|None)."""
    html = _fetch(url)
    if not html:
        return set(), None

    soup = BeautifulSoup(html, "html.parser")
    domain = urlparse(url).netloc
    emails = _clean_emails(html)
    business_name = _business_name_from(soup, domain)

    if not emails:
        contact_url = _find_contact_page(url, soup)
        if contact_url and urlparse(contact_url).netloc == domain:
            time.sleep(PAGE_FETCH_DELAY)
            contact_html = _fetch(contact_url)
            if contact_html:
                emails |= _clean_emails(contact_html)

    # Only keep emails whose domain matches (or is a subdomain of) the site
    # we're on, or plain gmail/other free providers business owners often
    # list directly — this cuts down heavily on noise from footer widgets,
    # ad scripts, etc pulled in from third-party domains.
    site_root = domain.replace("www.", "")
    kept = {e for e in emails if site_root in e.split("@")[-1]}
    if not kept and emails:
        # nothing matched the site's own domain — still keep a max of 1
        # generic address found on the page rather than discarding entirely
        kept = set(list(emails)[:1])

    return kept, business_name


def has_mx_record(domain):
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        return len(answers) > 0
    except Exception:
        # Fall back to a plain A-record / socket check if dnspython isn't
        # installed or the MX lookup fails for a transient reason.
        try:
            socket.gethostbyname(domain)
            return True
        except Exception:
            return False


def run_scrape_job(job_id, category, city=None, keywords=None, max_results=20):
    """Entry point called on a background thread from app.py."""
    db.update_scrape_job(job_id, status="running")
    db.append_scrape_job_log(job_id, f"Starting scrape for category='{category}' city='{city or ''}'")

    query_parts = [category]
    if city:
        query_parts.append(city)
    if keywords:
        query_parts.append(keywords)
    query_parts.append("contact email")
    query = " ".join(query_parts)

    db.append_scrape_job_log(job_id, f"Search query: {query}")
    urls = search_duckduckgo(query, max_results=max_results)
    db.append_scrape_job_log(job_id, f"Found {len(urls)} candidate sites")

    sites_checked = 0
    emails_found = 0
    emails_inserted = 0
    mx_cache = {}

    for url in urls:
        sites_checked += 1
        domain = urlparse(url).netloc
        try:
            found_emails, business_name = emails_from_site(url)
        except Exception as e:
            db.append_scrape_job_log(job_id, f"  [skip] {domain}: {e}")
            found_emails, business_name = set(), None

        for email in found_emails:
            emails_found += 1
            edomain = email.split("@")[-1]
            if edomain not in mx_cache:
                mx_cache[edomain] = has_mx_record(edomain)
            mx_ok = mx_cache[edomain]

            inserted = db.insert_lead(
                email=email,
                source_domain=domain,
                source_url=url,
                source_type="scrape",
                category=category,
                city=city,
                business_name=business_name,
                mx_valid=1 if mx_ok else 0,
            )
            if inserted:
                emails_inserted += 1
                db.append_scrape_job_log(job_id, f"  + {email}  ({domain}, mx_valid={mx_ok})")

        db.update_scrape_job(
            job_id,
            sites_checked=sites_checked,
            emails_found=emails_found,
            emails_inserted=emails_inserted,
        )
        time.sleep(PAGE_FETCH_DELAY)

    conn = db.get_conn()
    conn.execute(
        "INSERT INTO scrape_log (category, city, query, urls_found, emails_found, run_at) VALUES (?,?,?,?,?,?)",
        (category, city, query, len(urls), emails_found, __import__("datetime").datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()

    db.update_scrape_job(
        job_id,
        status="done",
        finished_at=__import__("datetime").datetime.utcnow().isoformat(),
    )
    db.append_scrape_job_log(
        job_id,
        f"Done. Checked {sites_checked} sites, found {emails_found} emails, inserted {emails_inserted} new leads.",
    )