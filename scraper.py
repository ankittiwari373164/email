"""
LEAD SCRAPER - Multi-backend web search + LinkedIn/Instagram via Startpage

IMPORTANT: Render's standard web service does NOT have Chrome installed,
so Selenium cannot work here without switching to a Docker deployment
(a bigger infra change). This version drops Selenium and instead:
  - Uses the search backend that's proven to return results (Startpage
    returns HTTP 200 reliably; DuckDuckGo/Mojeek get blocked with
    202/403 from Render's IP).
  - For LinkedIn/Instagram: searches site:linkedin.com / site:instagram.com
    via Startpage, then fetches each profile URL directly and extracts
    emails from whatever is in the page (meta description, visible bio
    text) — public profile pages often render this server-side even
    without JS.
  - For general web: same query-variant + directory-harvest approach
    that found 17 real leads in your last successful run.
"""
import re
import time
from urllib.parse import urlparse, quote_plus
from datetime import datetime

import requests
from bs4 import BeautifulSoup

import config
import db

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
REQUEST_TIMEOUT = 12
PAGE_FETCH_DELAY = 1.5
SEARCH_DELAY = 2.0

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
JUNK_DOMAINS = {"example.com", "sentry.io", "wixpress.com", "godaddy.com", "schema.org", "w3.org"}
JUNK_DOMAIN_SUBSTRINGS = ("sentry", "wixpress", "wix.com")
JUNK_LOCALPARTS = {"info@example", "test", "noreply", "no-reply", "donotreply"}
IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|gif|svg|webp)$", re.I)
HEX_HASH_LOCALPART_RE = re.compile(r"^[0-9a-f]{20,40}$", re.I)

DIRECTORY_SITES = ["justdial.com", "indiamart.com", "sulekha.com", "yellowpages.in"]
DIRECTORY_LINK_JUNK = ("facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "wa.me", "whatsapp.com", "googleusercontent.com", "gstatic.com", "google.com")


def _clean_emails(raw_text):
    found = set()
    for m in EMAIL_RE.findall(raw_text):
        email = m.strip().strip(".,;:").lower()
        localpart, domain = email.split("@", 1)
        if domain in JUNK_DOMAINS or any(s in domain for s in JUNK_DOMAIN_SUBSTRINGS):
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
        if r.status_code == 200:
            return r.text
    except requests.RequestException:
        pass
    return None


# ============================================================
# SEARCH BACKENDS — Startpage first since it's the one that
# reliably returns HTTP 200 from Render's IP in your logs.
# ============================================================

def search_startpage(query, max_results=15, log_fn=None):
    urls = []
    try:
        resp = requests.post("https://www.startpage.com/sp/search", data={"query": query},
                              headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if log_fn:
            log_fn(f"    Startpage -> HTTP {resp.status_code}")
        resp.raise_for_status()
    except Exception as e:
        if log_fn:
            log_fn(f"    Startpage -> FAIL: {str(e)[:60]}")
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


def search_bing(query, max_results=15, log_fn=None):
    urls = []
    try:
        resp = requests.get(f"https://www.bing.com/search?q={quote_plus(query)}&count=30",
                             headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if log_fn:
            log_fn(f"    Bing -> HTTP {resp.status_code}")
        resp.raise_for_status()
    except Exception as e:
        if log_fn:
            log_fn(f"    Bing -> FAIL: {str(e)[:60]}")
        return urls

    soup = BeautifulSoup(resp.text, "html.parser")
    for li in soup.select("li.b_algo h2 a"):
        href = li.get("href")
        if href and href.startswith("http"):
            urls.append(href)
        if len(urls) >= max_results:
            break
    if log_fn:
        log_fn(f"    Bing -> {len(urls)} result(s)")
    return urls[:max_results]


def search_duckduckgo(query, max_results=15, log_fn=None):
    urls = []
    try:
        resp = requests.post("https://html.duckduckgo.com/html/", data={"q": query},
                              headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if log_fn:
            log_fn(f"    DDG -> HTTP {resp.status_code}")
    except Exception as e:
        if log_fn:
            log_fn(f"    DDG -> FAIL: {str(e)[:60]}")
        return urls

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.select("a.result__a"):
        href = a.get("href")
        if href:
            urls.append(href)
        if len(urls) >= max_results:
            break
    if log_fn:
        log_fn(f"    DDG -> {len(urls)} result(s)")
    return urls[:max_results]


# Startpage FIRST — it's the backend that's proven to work from Render.
SEARCH_BACKENDS = [search_startpage, search_bing, search_duckduckgo]


# ============================================================
# LINKEDIN / INSTAGRAM — find profile URLs via Startpage,
# fetch each directly, extract whatever email text is present
# (meta description / visible bio — no JS execution possible
# without Chrome, so this only catches server-rendered content).
# ============================================================

PLATFORM_DOMAINS = {
    "LinkedIn": "linkedin.com",
    "Instagram": "instagram.com",
    "JustDial": "justdial.com",
    "Facebook": "facebook.com",
}


def find_platform_urls(category, city, log_fn=None):
    """The site: operator returns 0 results on every backend we've tried
    (Startpage/Bing/DDG all confirmed empty for site:-filtered category+
    city combos), while plain queries reliably return 10 results on
    Startpage. So: run broad queries (no site: filter), collect every
    URL, then bucket by domain into linkedin/instagram/justdial/facebook.
    This reuses the search path that's actually proven to work."""
    base = f"{category} {city}" if city else category
    queries = [
        f"{base} linkedin",
        f"{base} instagram",
        f"{base} justdial",
        f"{base} facebook",
        f"{base} contact email",
    ]

    buckets = {name: [] for name in PLATFORM_DOMAINS}
    seen = set()

    for query in queries:
        if log_fn:
            log_fn(f"  Query: {query}")
        results = search_startpage(query, max_results=15, log_fn=log_fn)
        if not results:
            results = search_bing(query, max_results=15, log_fn=log_fn)

        for url in results:
            if url in seen:
                continue
            seen.add(url)
            domain = urlparse(url).netloc.lower()
            for name, plat_domain in PLATFORM_DOMAINS.items():
                if plat_domain in domain:
                    buckets[name].append(url)
                    break
        time.sleep(SEARCH_DELAY)

    if log_fn:
        for name, urls in buckets.items():
            log_fn(f"  {name}: {len(urls)} URL(s) matched")

    return buckets


def emails_from_profile_page(url, log_fn=None):
    """Fetch a profile/post/listing page directly and pull emails from
    meta description + visible text. Public pages often render a text
    snippet server-side for SEO even without login/JS."""
    html = _fetch(url)
    if not html:
        if log_fn:
            log_fn(f"      [fetch failed] {url}")
        return set()

    soup = BeautifulSoup(html, "html.parser")
    text_parts = [soup.get_text()]
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        text_parts.append(meta_desc["content"])
    og_desc = soup.find("meta", attrs={"property": "og:description"})
    if og_desc and og_desc.get("content"):
        text_parts.append(og_desc["content"])

    emails = _clean_emails(" ".join(text_parts))
    if log_fn:
        if emails:
            log_fn(f"      {url} -> {len(emails)} email(s)")
        else:
            log_fn(f"      {url} -> no emails")
    return emails


# ============================================================
# DIRECTORY HARVEST — proven to work (found IndiaMART links)
# ============================================================

def _slugify(text):
    return re.sub(r"[^a-zA-Z0-9]+", "-", text.strip()).strip("-")


def build_directory_urls(category, city):
    cat_slug = _slugify(category)
    city_slug = _slugify(city) if city else ""
    urls = []
    if city_slug:
        urls.append(f"https://www.justdial.com/{city_slug}/{cat_slug}")
        urls.append(f"https://dir.indiamart.com/search.mp?ss={quote_plus(category + ' ' + city)}")
        urls.append(f"https://www.sulekha.com/{cat_slug}/{city_slug}")
    else:
        urls.append(f"https://dir.indiamart.com/search.mp?ss={quote_plus(category)}")
    return urls


def harvest_directory_links(directory_url, max_results=10, log_fn=None):
    html = _fetch(directory_url)
    if not html:
        if log_fn:
            log_fn(f"    Directory fetch failed: {directory_url}")
        return []
    soup = BeautifulSoup(html, "html.parser")
    directory_domain = urlparse(directory_url).netloc.replace("www.", "")
    found, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        link_domain = urlparse(href).netloc.replace("www.", "")
        if not link_domain or link_domain == directory_domain:
            continue
        if any(j in link_domain for j in DIRECTORY_LINK_JUNK) or link_domain in seen:
            continue
        seen.add(link_domain)
        found.append(href)
        if len(found) >= max_results:
            break
    if log_fn:
        log_fn(f"    Directory {directory_domain}: harvested {len(found)} link(s)")
    return found


def emails_from_site(url):
    html = _fetch(url)
    if not html:
        return set(), None
    soup = BeautifulSoup(html, "html.parser")
    domain = urlparse(url).netloc
    emails = _clean_emails(html)
    business_name = None
    if soup.title and soup.title.string:
        business_name = soup.title.string.strip().split("|")[0].split("-")[0].strip()[:120]
    site_root = domain.replace("www.", "")
    kept = {e for e in emails if site_root in e.split("@")[-1]}
    if not kept and emails:
        kept = emails if any(d in site_root for d in ["justdial", "indiamart", "sulekha"]) else set(list(emails)[:2])
    return kept, business_name


def has_mx_record(domain):
    try:
        import dns.resolver
        dns.resolver.resolve(domain, "MX", lifetime=5)
        return True
    except Exception:
        try:
            import socket
            socket.gethostbyname(domain)
            return True
        except Exception:
            return False


def build_query_variants(category, city=None, keywords=None):
    base = category
    if city:
        base = f"{category} {city}"
    variants = [
        f"{base} contact email",
        f"{base} email address",
        f"best {base}",
        f"{base} contact us",
        base,
    ]
    for d in DIRECTORY_SITES:
        variants.append(f"{base} site:{d}")
    if keywords:
        variants.append(f"{base} {keywords}")
    return variants


def collect_candidate_urls(category, city, keywords, max_results, log_fn=None):
    collected, seen_domains = [], set()

    if log_fn:
        log_fn("  Harvesting from business directories...")
    for durl in build_directory_urls(category, city):
        if len(collected) >= max_results:
            break
        links = harvest_directory_links(durl, max_results=max_results - len(collected), log_fn=log_fn)
        for u in links:
            dom = urlparse(u).netloc
            if dom and dom not in seen_domains:
                seen_domains.add(dom)
                collected.append(u)
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
            for u in results:
                dom = urlparse(u).netloc
                if dom and dom not in seen_domains:
                    seen_domains.add(dom)
                    collected.append(u)
                    new_count += 1
            time.sleep(SEARCH_DELAY)
            if new_count > 0:
                break

    return collected[:max_results]


# ============================================================
# MAIN ORCHESTRATION
# ============================================================

def run_scrape_job(job_id, category, city=None, keywords=None, max_results=20):
    db.update_scrape_job(job_id, status="running")
    log = lambda msg: db.append_scrape_job_log(job_id, msg)
    log(f"Starting scrape: category='{category}' city='{city or ''}'")
    log("=" * 70)

    # Phase 1: LinkedIn/Instagram/JustDial/Facebook via domain-bucketed
    # broad search (site: filter proven to return 0 everywhere — see
    # notes on find_platform_urls). Broad queries reliably return
    # results on Startpage, so we filter by domain after the fact.
    log("\nPhase 1: LinkedIn / Instagram / JustDial / Facebook")
    log("-" * 70)
    buckets = find_platform_urls(category, city, log_fn=log)

    platform_emails = {}
    for name, urls in buckets.items():
        emails = set()
        if urls:
            log(f"\n  Extracting from {name} ({len(urls)} URL(s))...")
            for u in urls:
                found = emails_from_profile_page(u, log_fn=log)
                emails.update(found)
                time.sleep(PAGE_FETCH_DELAY)
        platform_emails[name] = emails
        log(f"  {name} result: {len(emails)} emails")

    # Phase 2: Web + directories (proven working)
    log("\nPhase 2: Web Search + Directories")
    log("-" * 70)
    urls = collect_candidate_urls(category, city, keywords, max_results, log_fn=log)
    log(f"Web search collected {len(urls)} candidate sites")

    web_emails = set()
    mx_cache = {}
    sites_checked = 0
    for url in urls:
        sites_checked += 1
        domain = urlparse(url).netloc
        try:
            found, business_name = emails_from_site(url)
        except Exception as e:
            log(f"  [skip] {domain}: {e}")
            found, business_name = set(), None
        if found:
            web_emails.update(found)
            log(f"  + {domain}: {len(found)} email(s)")
        time.sleep(PAGE_FETCH_DELAY)
    log(f"Web result: {len(web_emails)} emails from {sites_checked} sites")

    # Insert
    log("\nInserting leads...")
    total_inserted = 0
    all_sources = dict(platform_emails)
    all_sources["web"] = web_emails
    for source, emails in all_sources.items():
        for email in emails:
            domain = email.split("@")[-1]
            if domain not in mx_cache:
                mx_cache[domain] = has_mx_record(domain)
            if db.insert_lead(
                email=email,
                source_domain=domain,
                source_url="",
                source_type=source.lower(),
                category=category,
                city=city,
                business_name=None,
                mx_valid=1 if mx_cache[domain] else 0,
            ):
                total_inserted += 1
                log(f"  ✓ {email}  ({source})")

    total_found = sum(len(e) for e in all_sources.values())
    log("\n" + "=" * 70)
    log("SCRAPE COMPLETE")
    for source, emails in all_sources.items():
        log(f"{source}: {len(emails)} emails")
    log(f"TOTAL: {total_found} found, {total_inserted} inserted")
    log("=" * 70)

    db.update_scrape_job(job_id, status="done", finished_at=datetime.utcnow())