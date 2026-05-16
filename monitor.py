#!/usr/bin/env python3
"""
Hamburg Apartment Alert Monitor
- Scrapes Kleinanzeigen + SAGA Hamburg for new sub-650 EUR listings
- Filters out swaps, senior housing, holiday/short-term lets
- Sends instant push notifications via ntfy.sh
- Stores seen listings in seen.json for deduplication
"""

import json
import os
import re
import sys
import time
import random
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# Prefer curl_cffi for better bot-detection bypass (real Chrome TLS fingerprint).
# Falls back to plain requests if it's not installed.
try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

# ============================================================
# CONFIG  (edit these to your taste)
# ============================================================
MAX_RENT = 650                      # max EUR (warm or cold)
SEEN_FILE = "seen.json"             # state file - committed back to repo
RETENTION_DAYS = 30                 # how long to remember seen listings
NTFY_TOPIC = (os.environ.get("NTFY_TOPIC") or "").strip()
NTFY_SERVER = (os.environ.get("NTFY_SERVER") or "").strip() or "https://ntfy.sh"

# Optional Telegram (leave empty to disable)
TELEGRAM_TOKEN = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
TELEGRAM_CHAT  = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

# Browser-like headers to reduce bot detection
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Linux"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


def _make_session():
    """Create an HTTP session with realistic browser identity."""
    if HAS_CFFI:
        return cffi_requests.Session()
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch(url: str, timeout: int = 30, warmup: str = "") -> str:
    """
    Fetch a URL with a real-browser TLS fingerprint when curl_cffi is available.
    If `warmup` is given, hit that URL first to establish cookies/session,
    which bypasses some bot-detection 401/403 responses.
    """
    sess = _make_session()
    kwargs = {"timeout": timeout}
    if HAS_CFFI:
        kwargs["impersonate"] = "chrome124"

    if warmup:
        try:
            sess.get(warmup, **kwargs)
            time.sleep(random.uniform(0.6, 1.4))
        except Exception:
            pass  # warmup is best-effort

    r = sess.get(url, **kwargs)
    r.raise_for_status()
    return r.text

# ============================================================
# FILTERS - what to EXCLUDE
# ============================================================
EXCLUDE_PATTERNS = [
    # --- Wohnungstausch (apartment swap) ---
    r"\bwohnungstausch\b", r"\btauschwohnung\b", r"\btauschangebot\b",
    r"\btausche?\s+(wohnung|gegen)", r"\bbiete\s+tausch\b", r"\bsuche\s+tausch\b",
    r"\bnur\s+tausch\b", r"\bgegen\s+\d+[-\s]?zimmer", r"\bim\s+tausch\b",

    # --- Senior housing ---
    r"\bseniorenwohnung\b", r"\baltenwohnung\b", r"\bbetreutes\s+wohnen\b",
    r"\bseniorenresidenz\b", r"\baltersgerecht", r"\bfür\s+senioren\b",
    r"\bfür\s+rentner\b", r"\bab\s+60\s+jahre", r"\bab\s+65\s+jahre",
    r"\bab\s+50\s+jahre", r"(?<!\d)(50|60|65)\s?\+", r"\b(50|60|65)plus\b",
    r"\bservice[-\s]?wohnen\b", r"\bservicewohnen\b",

    # --- Holiday / short-term ---
    r"\bferienwohnung\b", r"\bferienappartement\b", r"\bferienapartment\b",
    r"\burlaubswohnung\b", r"\bferienhaus\b", r"\bmonteur",
    r"\bzwischenmiete\b", r"\bzwischenvermietung\b",
    r"\bauf\s+zeit\b", r"\btemporär", r"\btageweise\b", r"\bwochenweise\b",
    # Mon-Fri / weekday-only rentals (Wochenpendler / Monteur-style)
    r"\bmo(ntag)?\s*[-–bis]+\s*fr(eitag)?\b",
    r"\bvon\s+mo(ntag)?\s+bis\s+fr(eitag)?\b",
    r"\b(unter|nur)\s+der?\s+woche\b",
    # 1-5 month sublets (clearly under 6 months) - leaves 6+ alone
    r"\bfür\s+[1-5]\s+monate?\b", r"\bnur\s+[1-5]\s+monate?\b",
    r"\b[1-5]\s+monate?\s+(miete|zwischen|unter)",
]
EXCLUDE_REGEX = re.compile("|".join(EXCLUDE_PATTERNS), re.IGNORECASE)


def is_excluded(text: str) -> bool:
    """Returns True if listing text matches any exclusion pattern."""
    if not text:
        return False
    return bool(EXCLUDE_REGEX.search(text))


def parse_price(text: str) -> int:
    """Extract first EUR amount from text. Returns 0 if none found."""
    if not text:
        return 0
    # Look for "XXX €" or "X.XXX €" or "X.XXX,XX €"
    m = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+)\s*€", text)
    if not m:
        return 0
    num = m.group(1).replace(".", "").replace(",", ".")
    try:
        return int(float(num))
    except ValueError:
        return 0


# ============================================================
# STATE
# ============================================================
def load_seen() -> dict:
    if not os.path.exists(SEEN_FILE):
        return {}
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_seen(seen: dict) -> None:
    # Prune old entries
    cutoff = (datetime.utcnow() - timedelta(days=RETENTION_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v.get("date", "") > cutoff}
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False, sort_keys=True)


# ============================================================
# NOTIFICATIONS
# ============================================================
def notify(listing: dict) -> None:
    """Send push notification(s). Tries ntfy first, then Telegram if configured."""
    title = f"🏠 {listing['source']} • {listing['price_text']}"
    body  = listing["title"]
    if listing.get("location"):
        body += f"\n📍 {listing['location']}"
    if listing.get("size"):
        body += f"\n📐 {listing['size']}"
    url = listing["url"]

    # --- ntfy.sh (free, no account) ---
    if NTFY_TOPIC:
        try:
            requests.post(
                f"{NTFY_SERVER}/{NTFY_TOPIC}",
                data=body.encode("utf-8"),
                headers={
                    "Title": title.encode("utf-8"),
                    "Click": url,
                    "Tags": "house",
                    "Priority": "high",
                    "Actions": f"view, Open listing, {url}, clear=true",
                },
                timeout=15,
            )
        except requests.RequestException as e:
            print(f"  ntfy error: {e}", file=sys.stderr)

    # --- Telegram (optional fallback) ---
    if TELEGRAM_TOKEN and TELEGRAM_CHAT:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT,
                    "text": f"*{title}*\n{body}\n\n{url}",
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False,
                },
                timeout=15,
            )
        except requests.RequestException as e:
            print(f"  telegram error: {e}", file=sys.stderr)

    if not NTFY_TOPIC and not (TELEGRAM_TOKEN and TELEGRAM_CHAT):
        print(f"  [DRY RUN] {title}\n  {body}\n  {url}")


# ============================================================
# SCRAPERS
# ============================================================
def scrape_kleinanzeigen() -> list[dict]:
    """Hamburg Wohnung mieten, sorted newest first, price <= 650."""
    url = ("https://www.kleinanzeigen.de/s-wohnung-mieten/hamburg/"
           f"preis::{MAX_RENT}/c203l9409")
    listings = []
    try:
        html = fetch(url)
    except Exception as e:
        print(f"[kleinanzeigen] fetch failed: {e}", file=sys.stderr)
        return listings

    soup = BeautifulSoup(html, "html.parser")
    for art in soup.select("article.aditem"):
        ad_id = art.get("data-adid")
        if not ad_id:
            continue

        link = art.select_one("a.ellipsis")
        if not link:
            continue
        title = link.get_text(" ", strip=True)
        href  = link.get("href", "")
        if href.startswith("/"):
            href = "https://www.kleinanzeigen.de" + href
        if not href:
            continue

        # Filter ads that are SEARCH posts (Gesuch), not OFFERS
        gesuch = art.select_one(".aditem-main--top--right .simpletag, .badge")
        gesuch_text = (gesuch.get_text(strip=True).lower() if gesuch else "")
        if "gesuch" in art.get_text(" ", strip=True).lower()[:80]:
            # Heuristic: 'Gesuch' appears early in tile when it's a wanted-ad
            continue

        desc_el  = art.select_one(".aditem-main--middle--description")
        desc     = desc_el.get_text(" ", strip=True) if desc_el else ""

        price_el = art.select_one(
            ".aditem-main--middle--price-shipping--price, "
            ".aditem-main--middle--price"
        )
        price_text = price_el.get_text(strip=True) if price_el else ""
        price = parse_price(price_text)

        loc_el = art.select_one(".aditem-main--top--left")
        location = loc_el.get_text(" ", strip=True) if loc_el else "Hamburg"

        # size + rooms (e.g. "45 m² · 1 Zi.")
        size_el = art.select_one(".text-module-end, .simpletag.tag-small")
        size = ""
        tags = art.select(".simpletag.tag-small")
        if tags:
            size = " · ".join(t.get_text(strip=True) for t in tags[:3])

        full_text = f"{title} {desc}"
        if is_excluded(full_text):
            continue
        if price > MAX_RENT:
            continue

        listings.append({
            "id":         f"ka-{ad_id}",
            "title":      title[:200],
            "price_text": f"{price} €" if price else (price_text or "Preis n.a."),
            "price":      price,
            "location":   location[:80],
            "size":       size,
            "url":        href,
            "source":     "Kleinanzeigen",
        })
    print(f"[kleinanzeigen] found {len(listings)} valid listings")
    return listings


def scrape_saga() -> list[dict]:
    """SAGA Hamburg - immediately available apartments."""
    url = "https://www.saga.hamburg/immobiliensuche?type=wohnungen"
    listings = []
    try:
        html = fetch(url, warmup="https://www.saga.hamburg/")
    except Exception as e:
        print(f"[saga] fetch failed: {e}", file=sys.stderr)
        return listings

    soup = BeautifulSoup(html, "html.parser")

    # SAGA uses 'a' tags pointing to /immobiliensuche/immo-detail/{id}/wohnung
    detail_re = re.compile(r"/immobiliensuche/immo-detail/(\d+)")
    seen_ids = set()

    for a in soup.find_all("a", href=True):
        m = detail_re.search(a["href"])
        if not m:
            continue
        sid = m.group(1)
        if sid in seen_ids:
            continue
        seen_ids.add(sid)

        # Find the enclosing card to extract details
        card = a
        for _ in range(5):
            if card.parent is None:
                break
            card = card.parent
            txt = card.get_text(" ", strip=True)
            if len(txt) > 60:
                break
        card_text = card.get_text(" ", strip=True)

        # Title: first informative line from the card
        title_parts = [t.strip() for t in card_text.split("•") if t.strip()]
        title = " • ".join(title_parts[:3])[:200] or f"SAGA-Wohnung #{sid}"

        price = parse_price(card_text)
        if price == 0 or price > MAX_RENT:
            continue
        if is_excluded(card_text):
            continue

        # extract m² and rooms
        size_match = re.search(r"(\d+(?:[,.]\d+)?)\s*m²", card_text)
        room_match = re.search(r"(\d+(?:[,.]\d+)?)\s*Zimmer", card_text, re.IGNORECASE)
        size_bits = []
        if size_match: size_bits.append(f"{size_match.group(1)} m²")
        if room_match: size_bits.append(f"{room_match.group(1)} Zi.")
        size = " · ".join(size_bits)

        # location - SAGA usually shows street + Hamburg in card
        loc_match = re.search(r"(\d{5})\s+Hamburg[^\d€]*", card_text)
        location = loc_match.group(0).strip()[:80] if loc_match else "Hamburg"

        href = urljoin("https://www.saga.hamburg", a["href"])

        listings.append({
            "id":         f"saga-{sid}",
            "title":      title,
            "price_text": f"{price} €",
            "price":      price,
            "location":   location,
            "size":       size,
            "url":        href,
            "source":     "SAGA",
        })
    print(f"[saga] found {len(listings)} valid listings")
    return listings


# ============================================================
# MAIN
# ============================================================
SCRAPERS = [
    scrape_kleinanzeigen,
    scrape_saga,
]


def main() -> int:
    seen = load_seen()
    # First run = no listings remembered yet. This correctly handles an empty
    # seen.json committed to the repo as a placeholder.
    first_run = (len(seen) == 0)
    all_new = []
    total_seen = 0

    for scraper in SCRAPERS:
        # tiny random delay between sources to be polite
        time.sleep(random.uniform(1.0, 2.5))
        try:
            items = scraper()
        except Exception as e:
            print(f"  scraper {scraper.__name__} crashed: {e}", file=sys.stderr)
            items = []
        total_seen += len(items)
        for it in items:
            if it["id"] in seen:
                continue
            seen[it["id"]] = {
                "date": datetime.utcnow().isoformat(),
                "title": it["title"],
                "url":   it["url"],
                "price": it["price"],
            }
            all_new.append(it)

    print(f"Total fetched: {total_seen}  |  New: {len(all_new)}  |  "
          f"First run: {first_run}")

    if first_run:
        print("First run → recording baseline, NOT sending notifications.")
    else:
        # sort new listings newest first by source order, then notify
        for it in all_new:
            print(f"  NEW → {it['source']}: {it['price_text']} · {it['title']}")
            notify(it)
            time.sleep(0.4)  # be nice to ntfy

    save_seen(seen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
