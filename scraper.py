"""
Category-driven lead scraper.

v2 changes (fixing "Found 0 candidate sites" every time):
  - Search failures used to fail SILENTLY (return an empty list, no error
    logged) — the #1 real-world cause is a search engine blocking/rate-
    limiting the *cloud host's* IP (Render/AWS datacenter IPs get this a
    lot from DuckDuckGo especially). Every search attempt now logs its
    HTTP status / exception to the job log, so you can actually see why.
  - One query, one engine used to be it. Now: several query VARIANTS per
    category (plain, +city, "near me"-style, directory-flavored) tried
    across MULTIPLE search backends (DuckDuckGo HTML, then Bing HTML as a
    fallback) until enough candidate URLs are collected or we run out of
    variants.
  - Added India-focused business-directory targeting (JustDial, IndiaMART,
    Sulekha, Yellow Pages India) via `site:` filtered queries — these
    directories list thousands of businesses per category/city and tend
    to be far more scrape-friendly than trying to find + crawl individual
    company websites one by one.

Flow, given a category (+ optional city / extra keywords):
  1. Build several query variants, try each against DuckDuckGo then Bing
     until we have enough candidate URLs (or run out of variants).
  2. Visit each result site (homepage + a contact/about page if needed),
     pull out any email addresses.
  3. Filter obvious noise (images, example.com, sentry, etc).
  4. MX-check the domain.
  5. Insert into the Supabase `leads` table (deduped by email — UNIQUE
     constraint means an email is never stored twice, across any
     category/city/run).

Runs in a background thread kicked off from app.py; progress is written to
the `scrape_jobs` row so the dashboard can poll it.
"""
import re
import time
import socket
from urllib.parse import urlparse, urljoin, quote_plus

import requests
from bs4 import BeautifulSoup

import config
import db

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 12
PAGE_FETCH_DELAY = 1.5  # seconds between site fetches — be a polite crawler
SEARCH_DELAY = 2.0      # seconds between search-engine requests

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

JUNK_DOMAINS = {
    "example.com", "sentry.io", "wixpress.com", "godaddy.com", "schema.org",
    "w3.org", "gmail.com.png", "yourdomain.com", "domain.com",
}
# Substrings anywhere in the domain — catches subdomains like
# sentry.wixpress.com, o12345.ingest.sentry.io, etc that an exact-match
# check on JUNK_DOMAINS misses.
JUNK_DOMAIN_SUBSTRINGS = ("sentry", "wixpress", "wix.com", "sentry-cdn")
JUNK_LOCALPARTS = {"info@example", "test", "noreply", "no-reply", "donotreply"}
IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|gif|svg|webp)$", re.I)
# Sentry/analytics/tracking IDs are typically a 24-40 char hex string as
# the local-part (e.g. dd0a55ccb8124b9c9d938e3acf41f8aa@...) — never a
# real person's contact address.
HEX_HASH_LOCALPART_RE = re.compile(r"^[0-9a-f]{20,40}$", re.I)

CONTACT_LINK_WORDS = ("contact", "about", "reach", "get-in-touch")

# Directories that list thousands of small/local businesses per
# category+city and are generally easier to get results from than hunting
# down individual company websites. Adjust/add for your market — these
# default to India since that's what your leads.db categories look like
# (real estate consultant / interior designer / etc, Delhi/Bangalore/Mumbai).
DIRECTORY_SITES = [
    "justdial.com",
    "indiamart.com",
    "sulekha.com",
    "yellowpages.in",
]


def _clean_emails(raw_text):
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


def build_query_variants(category, city=None, keywords=None):
    """Several differently-worded queries to try in order, so one bad
    phrasing (or one search engine having a bad day) doesn't zero out the
    whole scrape."""
    variants = []

    base = category
    loc = f" {city}" if city else ""
    kw = f" {keywords}" if keywords else ""

    variants.append(f"{base}{loc}{kw} contact email")
    variants.append(f"{base}{loc}{kw} email address")
    variants.append(f"best {base}{loc}{kw}")
    variants.append(f"{base}{loc}{kw} contact us")
    variants.append(f"{base}{loc}{kw}")  # plain, no suffix — sometimes the extra words hurt

    # Directory-targeted variants — these tend to return far more usable
    # results per query than open web search for local/small businesses.
    for site in DIRECTORY_SITES:
        variants.append(f"{base}{loc} site:{site}")

    # de-dupe while preserving order
    seen = set()
    out = []
    for v in variants:
        v = v.strip()
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def search_google_cse(query, max_results=20, log_fn=None):
    """Google Custom Search JSON API — a real API, not scraping, so it
    doesn't get 403'd like DuckDuckGo/Bing HTML do. Needs
    config.GOOGLE_CSE_API_KEY + config.GOOGLE_CSE_CX (see config.py for
    free setup instructions). Returns [] immediately (no wasted requests)
    if those aren't configured, so the fallback engines get a chance."""
    if not config.GOOGLE_CSE_API_KEY or not config.GOOGLE_CSE_CX:
        if log_fn:
            log_fn("    Google CSE not configured (GOOGLE_CSE_API_KEY/GOOGLE_CSE_CX) — skipping")
        return []

    urls = []
    # Google CSE returns max 10 results per call; page through with `start`
    # for up to max_results (capped at 100 total per API limits).
    start = 1
    while len(urls) < max_results and start <= 91:
        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": config.GOOGLE_CSE_API_KEY,
                    "cx": config.GOOGLE_CSE_CX,
                    "q": query,
                    "start": start,
                    "num": min(10, max_results - len(urls)),
                },
                timeout=REQUEST_TIMEOUT,
            )
            if log_fn:
                log_fn(f"    Google CSE '{query}' (start={start}) -> HTTP {resp.status_code}")
            if resp.status_code != 200:
                if log_fn:
                    log_fn(f"    -> {resp.text[:200]}")
                break
            data = resp.json()
        except requests.RequestException as e:
            if log_fn:
                log_fn(f"    Google CSE '{query}' -> FAILED: {e}")
            break

        items = data.get("items", [])
        if not items:
            break
        for item in items:
            link = item.get("link")
            if link:
                urls.append(link)
        start += 10
        time.sleep(0.3)  # stay well under quota-per-second limits

    if log_fn:
        log_fn(f"    -> {len(urls)} result(s) total")
    return urls[:max_results]


def search_duckduckgo(query, max_results=20, log_fn=None):
    urls = []
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if log_fn:
            log_fn(f"    DuckDuckGo '{query}' -> HTTP {resp.status_code}")
        resp.raise_for_status()
    except requests.RequestException as e:
        if log_fn:
            log_fn(f"    DuckDuckGo '{query}' -> FAILED: {e}")
        return urls

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.select("a.result__a"):
        href = a.get("href")
        if href:
            urls.append(href)
        if len(urls) >= max_results:
            break

    if not urls:
        for a in soup.select("a[href^='http']"):
            href = a.get("href")
            if href and "duckduckgo.com" not in href:
                urls.append(href)
            if len(urls) >= max_results:
                break

    if log_fn:
        log_fn(f"    -> {len(urls)} result(s)")
    return urls[:max_results]


def search_bing(query, max_results=20, log_fn=None):
    """Fallback search engine — tried when DuckDuckGo returns nothing for
    a query, since a block/rate-limit on one engine doesn't necessarily
    apply to the other."""
    urls = []
    try:
        resp = requests.get(
            f"https://www.bing.com/search?q={quote_plus(query)}&count=30",
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if log_fn:
            log_fn(f"    Bing '{query}' -> HTTP {resp.status_code}")
        resp.raise_for_status()
    except requests.RequestException as e:
        if log_fn:
            log_fn(f"    Bing '{query}' -> FAILED: {e}")
        return urls

    soup = BeautifulSoup(resp.text, "html.parser")
    for li in soup.select("li.b_algo h2 a"):
        href = li.get("href")
        if href and href.startswith("http"):
            urls.append(href)
        if len(urls) >= max_results:
            break

    if log_fn:
        log_fn(f"    -> {len(urls)} result(s)")
    return urls[:max_results]


def search_mojeek(query, max_results=20, log_fn=None):
    """Independent search index, no API key, no card. Smaller index than
    Google/Bing so results are thinner, but it's genuinely free and worth
    trying when the bigger engines are blocking scripted requests."""
    urls = []
    try:
        resp = requests.get(
            "https://www.mojeek.com/search",
            params={"q": query},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if log_fn:
            log_fn(f"    Mojeek '{query}' -> HTTP {resp.status_code}")
        resp.raise_for_status()
    except requests.RequestException as e:
        if log_fn:
            log_fn(f"    Mojeek '{query}' -> FAILED: {e}")
        return urls

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.select("a.title, h2.title a, li.result a.ob"):
        href = a.get("href")
        if href and href.startswith("http"):
            urls.append(href)
        if len(urls) >= max_results:
            break

    if log_fn:
        log_fn(f"    -> {len(urls)} result(s)")
    return urls[:max_results]


def search_linkedin_profiles(query, max_results=20, log_fn=None):
    """Search LinkedIn profiles directly using DuckDuckGo's site: operator.
    LinkedIn's own API is restricted, but we can scrape public profile search
    results via site:linkedin.com queries. Looks for emails in profile text
    (many people list contact info in their headline or summary)."""
    urls = []
    linkedin_query = f"site:linkedin.com {query} email OR gmail OR contact"
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": linkedin_query},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if log_fn:
            log_fn(f"    LinkedIn (via DDG) '{query}' -> HTTP {resp.status_code}")
        resp.raise_for_status()
    except requests.RequestException as e:
        if log_fn:
            log_fn(f"    LinkedIn (via DDG) '{query}' -> FAILED: {e}")
        return urls

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.select("a.result__a"):
        href = a.get("href")
        if href and "linkedin.com/in/" in href:
            urls.append(href)
        if len(urls) >= max_results:
            break

    if log_fn:
        log_fn(f"    -> {len(urls)} LinkedIn profile(s)")
    return urls[:max_results]


def emails_from_linkedin_profile(profile_url):
    """Fetch a LinkedIn profile page (public, no login) and extract any
    emails found in the headline, summary, or about sections. LinkedIn
    profiles don't always have emails, but many professionals list contact
    info there."""
    html = _fetch(profile_url)
    if not html:
        return set(), None

    soup = BeautifulSoup(html, "html.parser")
    # LinkedIn profile name is usually in the page title or main heading
    name = None
    if soup.title:
        title = soup.title.string or ""
        if " | LinkedIn" in title:
            name = title.split(" | LinkedIn")[0].strip()
    if not name:
        for h1 in soup.find_all("h1"):
            name = h1.get_text().strip()
            if name:
                break

    # Extract all text from the profile (headline, summary, about, etc)
    # LinkedIn puts contact info in various places; scrape broadly.
    profile_text = soup.get_text()
    emails = _clean_emails(profile_text)

    # Filter to only emails that look like they belong to this person
    # (not company-domain-only emails, which are less useful for cold outreach)
    personal_emails = set()
    for email in emails:
        domain = email.split("@")[-1]
        # Prefer Gmail, Outlook, Yahoo, and other personal domains over
        # company domains (which are less likely to be personal contact).
        if any(p in domain for p in ("gmail", "yahoo", "outlook", "hotmail", "protonmail", "icloud")):
            personal_emails.add(email)
        elif domain not in {"linkedin.com", "google.com"}:  # skip platform domains
            personal_emails.add(email)

    return personal_emails, name


def harvest_linkedin_emails(category, city=None, max_profiles=10, log_fn=None):
    """Find LinkedIn profiles for a category+city and extract contact
    emails. Returns (collected_emails, total_profiles_checked)."""
    query = category
    if city:
        query += f" {city}"

    if log_fn:
        log_fn(f"  Searching LinkedIn for '{query}'...")

    try:
        profile_urls = search_linkedin_profiles(query, max_results=max_profiles, log_fn=log_fn)
    except Exception as e:
        if log_fn:
            log_fn(f"    LinkedIn search failed: {e}")
        return set(), 0

    if not profile_urls:
        if log_fn:
            log_fn("    No LinkedIn profiles found for this query")
        return set(), 0

    emails = set()
    for i, profile_url in enumerate(profile_urls):
        try:
            profile_emails, name = emails_from_linkedin_profile(profile_url)
            if profile_emails:
                if log_fn:
                    log_fn(f"      {name or 'Unknown'}: found {len(profile_emails)} email(s)")
                emails.update(profile_emails)
        except Exception as e:
            if log_fn:
                log_fn(f"      {profile_url}: {type(e).__name__}")
        time.sleep(PAGE_FETCH_DELAY)

    return emails, len(profile_urls)



    """Startpage proxies Google results, no API key/card needed for the
    plain web UI. Best-effort like the others — logs its HTTP status so
    failures are visible rather than silent."""
    urls = []
    try:
        resp = requests.post(
            "https://www.startpage.com/sp/search",
            data={"query": query},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if log_fn:
            log_fn(f"    Startpage '{query}' -> HTTP {resp.status_code}")
        resp.raise_for_status()
    except requests.RequestException as e:
        if log_fn:
            log_fn(f"    Startpage '{query}' -> FAILED: {e}")
        return urls

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.select("a.w-gl__result-title, a.result-link"):
        href = a.get("href")
        if href and href.startswith("http"):
            urls.append(href)
        if len(urls) >= max_results:
            break

    if log_fn:
        log_fn(f"    -> {len(urls)} result(s)")
    return urls[:max_results]


SEARCH_BACKENDS = [search_google_cse, search_duckduckgo, search_bing, search_mojeek, search_startpage]


# Non-search-engine business links commonly found ON a directory listing
# page that we don't want to treat as a "business website" (social/share
# widgets, the directory's own asset domains, etc).
DIRECTORY_LINK_JUNK = (
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "wa.me", "whatsapp.com", "play.google.com", "apps.apple.com",
    "googleusercontent.com", "gstatic.com", "doubleclick.net", "google.com",
)


def _slugify_for_directory(text):
    return re.sub(r"[^a-zA-Z0-9]+", "-", text.strip()).strip("-")


def build_directory_listing_urls(category, city):
    """Best-effort category+city listing URLs for each directory in
    DIRECTORY_SITES. These follow each site's typical /City/Category-slug
    pattern — directories do restructure their URLs occasionally, so this
    is best-effort (logged, never fatal if a pattern's gone stale)."""
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


def harvest_directory_outbound_links(directory_url, max_results=15, log_fn=None):
    """Fetch a directory listing page directly (no search engine involved
    at all) and pull out links to businesses' OWN websites — directory
    pages themselves are phone/WhatsApp-first and rarely show emails, but
    they often link out to each listed business's real site, which our
    normal emails_from_site() crawler is good at getting emails from."""
    html = _fetch(directory_url)
    if not html:
        if log_fn:
            log_fn(f"    Directory fetch failed or blocked: {directory_url}")
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
        log_fn(f"    Directory {directory_domain}: harvested {len(found)} outbound business link(s)")
    return found


def collect_candidate_urls(category, city, keywords, max_results, log_fn=None):
    """Try, in order: (1) direct directory-listing harvest -- no search
    engine, no API, no rate limit, genuinely free forever -- then (2)
    query variants across search backends for whatever's still needed.
    Returns a de-duped list of URLs, logging every attempt along the way
    so failures are visible."""
    collected = []
    seen_domains = set()

    if log_fn:
        log_fn("  Harvesting business links directly from directories (no search engine needed)...")
    for directory_url in build_directory_listing_urls(category, city):
        if len(collected) >= max_results:
            break
        try:
            links = harvest_directory_outbound_links(
                directory_url, max_results=max_results - len(collected), log_fn=log_fn
            )
        except Exception as e:
            if log_fn:
                log_fn(f"    Directory harvest raised {type(e).__name__}: {e}")
            links = []
        for url in links:
            domain = urlparse(url).netloc
            if domain and domain not in seen_domains:
                seen_domains.add(domain)
                collected.append(url)
        time.sleep(PAGE_FETCH_DELAY)

    if len(collected) >= max_results:
        return collected[:max_results]

    variants = build_query_variants(category, city, keywords)

    for query in variants:
        if len(collected) >= max_results:
            break
        for backend in SEARCH_BACKENDS:
            if len(collected) >= max_results:
                break
            if log_fn:
                log_fn(f"  Trying {backend.__name__} for: {query}")
            try:
                results = backend(query, max_results=max_results, log_fn=log_fn)
            except Exception as e:
                if log_fn:
                    log_fn(f"    {backend.__name__} raised {type(e).__name__}: {e}")
                results = []

            new_count = 0
            for url in results:
                domain = urlparse(url).netloc
                if domain and domain not in seen_domains:
                    seen_domains.add(domain)
                    collected.append(url)
                    new_count += 1

            time.sleep(SEARCH_DELAY)

            if new_count > 0:
                # This backend worked for this query -- no need to also hit
                # the (likely-blocked) fallback engines for the same query,
                # move on to the next query variant instead.
                break

    return collected[:max_results]


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

    site_root = domain.replace("www.", "")
    kept = {e for e in emails if site_root in e.split("@")[-1]}
    if not kept and emails:
        # Directory pages (JustDial etc) list OTHER businesses' emails on
        # a domain that obviously isn't the lead's own — keep everything
        # found there rather than filtering by domain match.
        if any(d in site_root for d in DIRECTORY_SITES):
            kept = emails
        else:
            kept = set(list(emails)[:1])

    return kept, business_name


def has_mx_record(domain):
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        return len(answers) > 0
    except Exception:
        try:
            socket.gethostbyname(domain)
            return True
        except Exception:
            return False


def run_scrape_job(job_id, category, city=None, keywords=None, max_results=20):
    """Entry point called on a background thread from app.py."""
    db.update_scrape_job(job_id, status="running")
    log = lambda msg: db.append_scrape_job_log(job_id, msg)
    log(f"Starting scrape for category='{category}' city='{city or ''}'")

    # Try LinkedIn first (educational, often has personal email addresses)
    log("Phase 1: LinkedIn profiles...")
    linkedin_emails, linkedin_profiles_checked = harvest_linkedin_emails(
        category, city, max_profiles=8, log_fn=log
    )
    log(f"LinkedIn: found {len(linkedin_emails)} emails from {linkedin_profiles_checked} profiles")

    urls = collect_candidate_urls(category, city, keywords, max_results, log_fn=log)
    log(f"Phase 2: Web search: {len(urls)} candidate sites collected")

    if not urls and not linkedin_emails:
        log("No candidate sites or LinkedIn profiles found from any source. "
            "This usually means search engines are blocking/rate-limiting "
            "this server's IP (common on cloud hosts). Consider: trying again "
            "later, using a narrower/different category or city, or checking "
            "logs for specific HTTP error codes.")

    sites_checked = 0
    emails_found = 0
    emails_inserted = 0
    mx_cache = {}

    # First, insert LinkedIn emails
    for email in linkedin_emails:
        emails_found += 1
        edomain = email.split("@")[-1]
        if edomain not in mx_cache:
            mx_cache[edomain] = has_mx_record(edomain)
        mx_ok = mx_cache[edomain]

        inserted = db.insert_lead(
            email=email,
            source_domain="linkedin.com",
            source_url="https://linkedin.com",
            source_type="linkedin",
            category=category,
            city=city,
            business_name=None,
            mx_valid=1 if mx_ok else 0,
        )
        if inserted:
            emails_inserted += 1
            log(f"  + {email}  (LinkedIn, mx_valid={mx_ok})")

    # Then, scrape web sites for more emails
    for url in urls:
        sites_checked += 1
        domain = urlparse(url).netloc
        try:
            found_emails, business_name = emails_from_site(url)
        except Exception as e:
            log(f"  [skip] {domain}: {e}")
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
                log(f"  + {email}  ({domain}, mx_valid={mx_ok})")

        db.update_scrape_job(
            job_id,
            sites_checked=sites_checked,
            emails_found=emails_found,
            emails_inserted=emails_inserted,
        )
        time.sleep(PAGE_FETCH_DELAY)

    from datetime import datetime
    conn_log_row = (category, city, f"{category} {city or ''}".strip(), len(urls), emails_found, datetime.utcnow())
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO scrape_log (category, city, query, urls_found, emails_found, run_at) VALUES (%s,%s,%s,%s,%s,%s)",
            conn_log_row,
        )

    db.update_scrape_job(job_id, status="done", finished_at=datetime.utcnow())
    log(f"Done. Checked LinkedIn ({linkedin_profiles_checked} profiles), web sites ({sites_checked}), found {emails_found} emails total, inserted {emails_inserted} new leads.")