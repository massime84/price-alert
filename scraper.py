#!/usr/bin/env python3
"""
Price Alert Scraper - eBay + Subito.it
- AI-generated query variants (typos, spacing, abbreviations)
- Description search on Subito.it
"""

import os
import json
import smtplib
import requests
import hashlib
import time
import random
import re
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

# ── CONFIG ──────────────────────────────────────────────────────────
EMAIL_FROM     = os.environ.get("EMAIL_FROM", "")
EMAIL_TO       = os.environ.get("EMAIL_TO", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EBAY_APP_ID    = os.environ.get("EBAY_APP_ID", "")

CONFIG_FILE    = "price-alert-config.json"
SEEN_FILE      = "seen_listings.json"
# ────────────────────────────────────────────────────────────────────


def load_config() -> list[dict]:
    if not os.path.exists(CONFIG_FILE):
        print(f"[Config] {CONFIG_FILE} not found.")
        return []
    with open(CONFIG_FILE) as f:
        data = json.load(f)
    searches = [s for s in data.get("searches", []) if s.get("active", True)]
    print(f"[Config] Loaded {len(searches)} active searches.")
    return searches


def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


# ── QUERY VARIANTS (free, local rules) ──────────────────────────────
def generate_variants(query: str) -> list[str]:
    """Generate search variants using local rules — no API needed."""
    variants = set()
    q = query.strip().lower()
    variants.add(q)

    words = q.split()

    # 1. Remove all spaces → "macbookm1"
    variants.add("".join(words))

    # 2. Each word pair joined without space
    for i in range(len(words) - 1):
        joined = words[:i] + [words[i] + words[i+1]] + words[i+2:]
        variants.add(" ".join(joined))

    # 3. Add space inside each word (split at each char boundary)
    for i, word in enumerate(words):
        for j in range(1, len(word)):
            new_words = words[:i] + [word[:j], word[j:]] + words[i+1:]
            variants.add(" ".join(new_words))

    # 4. Common tech typo rules
    typo_map = {
        "macbook":  ["mac book", "macbok", "machbook", "macboo", "mac-book", "mcbook", "maccbook"],
        "mac":      ["mack", "mac "],
        "iphone":   ["i phone", "iphon", "ifone"],
        "ipad":     ["i pad", "ipd"],
        "samsung":  ["samsng", "samung", "samsun"],
        "playstation": ["play station", "playstaton", "playsation"],
        "nintendo": ["nitendo", "nintedo"],
        "airpods":  ["air pods", "airpod", "air pod"],
        "m1":       ["m 1", "m-1"],
        "m2":       ["m 2", "m-2"],
        "m3":       ["m 3", "m-3"],
        "pro":      ["pr0", "proe"],
        "air":      ["air "],
        "mini":     ["mni", "min1"],
        "plus":     ["plu", "pls"],
        "ultra":    ["ulta", "ultra "],
    }
    for word, typos in typo_map.items():
        if word in q:
            for typo in typos:
                variants.add(q.replace(word, typo).strip())

    # 5. Drop last character of each word (truncated search)
    truncated = " ".join(w[:-1] if len(w) > 3 else w for w in words)
    if truncated != q:
        variants.add(truncated)

    # 6. Original with capital first letter (some platforms are case sensitive)
    variants.add(query.strip())

    # Clean up and limit
    result = [v.strip() for v in variants if len(v.strip()) >= 3]
    result = list(dict.fromkeys(result))[:8]  # deduplicate, max 8

    print(f"[Variants] '{query}' → {result}")
    return result


# ── eBay SEARCH ──────────────────────────────────────────────────────
def search_ebay_single(query: str, price_min: float, price_max: float) -> list[dict]:
    if not EBAY_APP_ID:
        print("[eBay] EBAY_APP_ID not set, skipping.")
        return []
    url = "https://svcs.ebay.com/services/search/FindingService/v1"
    params = {
        "OPERATION-NAME": "findItemsAdvanced",
        "SERVICE-VERSION": "1.0.0",
        "SECURITY-APPNAME": EBAY_APP_ID,
        "RESPONSE-DATA-FORMAT": "JSON",
        "REST-PAYLOAD": "",
        "keywords": query,
        "paginationInput.entriesPerPage": "50",
        "itemFilter(0).name": "MinPrice",
        "itemFilter(0).value": str(price_min),
        "itemFilter(0).paramName": "Currency",
        "itemFilter(0).paramValue": "EUR",
        "itemFilter(1).name": "MaxPrice",
        "itemFilter(1).value": str(price_max),
        "itemFilter(1).paramName": "Currency",
        "itemFilter(1).paramValue": "EUR",
        "itemFilter(2).name": "ListingType",
        "itemFilter(2).value": "AuctionWithBIN,FixedPrice",
        "itemFilter(3).name": "Condition",
        "itemFilter(3).value": "Used",
        "sortOrder": "StartTimeNewest",
        "outputSelector": "PictureURLSuperSize",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        items = (data
                 .get("findItemsAdvancedResponse", [{}])[0]
                 .get("searchResult", [{}])[0]
                 .get("item", []))
        results = []
        for item in items:
            price_val = float(
                item.get("sellingStatus", [{}])[0]
                .get("currentPrice", [{}])[0]
                .get("__value__", 0)
            )
            link = item.get("viewItemURL", [""])[0]
            if price_min <= price_val <= price_max and link:
                results.append({
                    "source": "eBay",
                    "title": item.get("title", [""])[0],
                    "price": price_val,
                    "url": link,
                    "image": item.get("pictureURLSuperSize", [""])[0] or item.get("galleryURL", [""])[0],
                    "location": item.get("location", ["Italia"])[0],
                    "date": item.get("listingInfo", [{}])[0].get("startTime", [""])[0],
                    "matched_variant": query,
                })
        return results
    except Exception as e:
        print(f"[eBay] Error for '{query}': {e}")
        return []


def search_ebay(query: str, variants: list[str], price_min: float, price_max: float) -> list[dict]:
    """Search eBay with all variants, deduplicate by URL."""
    all_results = {}
    for v in variants:
        results = search_ebay_single(v, price_min, price_max)
        for r in results:
            uid = make_id(r["url"])
            if uid not in all_results:
                all_results[uid] = r
        if len(variants) > 1:
            time.sleep(0.5)
    print(f"[eBay] '{query}' → {len(all_results)} unique listings across {len(variants)} variants")
    return list(all_results.values())


# ── SUBITO.IT SEARCH ─────────────────────────────────────────────────
def search_subito_browser(query: str, price_min: float, price_max: float) -> list[dict]:
    """Search Subito.it using a real headless browser via Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[Subito.it] Playwright not installed, skipping.")
        return []

    query_enc = requests.utils.quote(query)
    url = (
        f"https://www.subito.it/annunci-italia/vendita/usato/"
        f"?q={query_enc}&qso=true&ps={int(price_min)}&pe={int(price_max)}&sort=datedesc"
    )

    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="it-IT",
                timezone_id="Europe/Rome",
                extra_http_headers={
                    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            # Mask automation fingerprints
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3] });
                window.chrome = { runtime: {} };
            """)

            page = context.new_page()
            time.sleep(random.uniform(1, 2))
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2, 3))

            # Accept cookie banner if present
            try:
                page.click("button:has-text('Accetta')", timeout=3000)
                time.sleep(1)
            except Exception:
                pass

            # Parse results from page content
            soup = BeautifulSoup(page.content(), "html.parser")
            browser.close()

            query_lower = query.lower()

            # Try JSON-LD
            for tag in soup.find_all("script", {"type": "application/ld+json"}):
                try:
                    data = json.loads(tag.string or "")
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if item.get("@type") not in ("Product", "Offer"):
                            continue
                        offers = item.get("offers", {})
                        price_val = float(offers.get("price", 0) or 0)
                        link = item.get("url", "")
                        if price_min <= price_val <= price_max and link:
                            results.append({
                                "source": "Subito.it",
                                "title": item.get("name", ""),
                                "price": price_val,
                                "url": link,
                                "image": (item.get("image", [""])[0]
                                          if isinstance(item.get("image"), list)
                                          else item.get("image", "")),
                                "location": offers.get("availableAtOrFrom", {}).get("name", "Italia"),
                                "date": "",
                                "matched_variant": query,
                                "found_in": None,
                            })
                except Exception:
                    pass

            # Fallback: HTML cards
            if not results:
                for card in soup.select("article[class*='item-card'], div[class*='AdItem'], [class*='item--']"):
                    try:
                        title_el = card.select_one("[class*='title'], h2, h3")
                        price_el = card.select_one("[class*='price']")
                        link_el  = card.select_one("a[href]")
                        img_el   = card.select_one("img")
                        if not (title_el and price_el and link_el):
                            continue
                        price_text = re.sub(r'[^\d,.]', '', price_el.get_text(strip=True).replace(".", "").replace(",", "."))
                        price_val = float(price_text or 0)
                        href = link_el.get("href", "")
                        if not href.startswith("http"):
                            href = "https://www.subito.it" + href
                        title = title_el.get_text(strip=True)
                        if price_min <= price_val <= price_max and href:
                            found_in = None
                            if query_lower not in title.lower():
                                found_in = "descrizione"
                            results.append({
                                "source": "Subito.it",
                                "title": title,
                                "price": price_val,
                                "url": href,
                                "image": img_el.get("src", "") if img_el else "",
                                "location": "Italia",
                                "date": "",
                                "matched_variant": query,
                                "found_in": found_in,
                            })
                    except Exception:
                        pass

        print(f"[Subito.it Browser] Found {len(results)} listings for '{query}'")
        return results

    except Exception as e:
        print(f"[Subito.it Browser] Error for '{query}': {e}")
        return []


def search_subito(query: str, variants: list[str], price_min: float, price_max: float) -> list[dict]:
    """Search Subito.it via headless browser with all variants, deduplicate by URL."""
    all_results = {}
    for v in variants:
        results = search_subito_browser(v, price_min, price_max)
        for r in results:
            uid = make_id(r["url"])
            if uid not in all_results:
                all_results[uid] = r
        if len(variants) > 1:
            time.sleep(random.uniform(1, 2))
    print(f"[Subito.it] '{query}' → {len(all_results)} unique listings across {len(variants)} variants")
    return list(all_results.values())


# ── EMAIL ────────────────────────────────────────────────────────────
def send_email(new_listings: list[dict], search_query: str):
    if not all([EMAIL_FROM, EMAIL_TO, EMAIL_PASSWORD]):
        print("[Email] Missing credentials.")
        return

    subject = f"🔔 {len(new_listings)} nuovi annunci: {search_query}"

    cards_html = ""
    for item in new_listings:
        img_tag = f'<img src="{item["image"]}" width="110" style="border-radius:8px;margin-right:16px;object-fit:cover;" />' if item.get("image") else ""
        found_badge = ""
        if item.get("found_in") == "descrizione":
            found_badge = '<span style="background:#ff9800;color:#fff;border-radius:4px;padding:1px 7px;font-size:11px;margin-left:6px;">trovato in descrizione</span>'
        variant_badge = ""
        if item.get("matched_variant") and item["matched_variant"].lower() != search_query.lower():
            variant_badge = f'<span style="background:#555;color:#ccc;border-radius:4px;padding:1px 7px;font-size:11px;margin-left:6px;">variante: {item["matched_variant"]}</span>'
        color = "#0064D2" if item["source"] == "eBay" else "#e63f19"
        cards_html += f"""
        <div style="border:1px solid #e0e0e0;border-radius:12px;padding:16px;margin-bottom:14px;display:flex;align-items:flex-start;font-family:Arial,sans-serif;">
            {img_tag}
            <div style="flex:1">
                <div style="margin-bottom:6px;">
                    <span style="background:{color};color:white;border-radius:4px;padding:2px 8px;font-size:12px;">{item['source']}</span>
                    {found_badge}{variant_badge}
                </div>
                <h3 style="margin:6px 0 4px;font-size:15px;">{item['title']}</h3>
                <p style="font-size:22px;font-weight:bold;color:#2ecc71;margin:0;">€{item['price']:.2f}</p>
                <p style="color:#888;margin:4px 0;font-size:13px;">📍 {item['location']}</p>
                <a href="{item['url']}" style="display:inline-block;margin-top:8px;background:#333;color:white;padding:7px 14px;border-radius:6px;text-decoration:none;font-size:13px;">Vedi annuncio →</a>
            </div>
        </div>"""

    body = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px;">
        <h2 style="margin-bottom:4px;">🔔 Nuovi annunci trovati!</h2>
        <p style="color:#555;">Ricerca: <strong>{search_query}</strong></p>
        <p style="color:#888;font-size:12px;">Trovati il {datetime.now().strftime('%d/%m/%Y alle %H:%M')}</p>
        <hr style="margin:16px 0;"/>
        {cards_html}
        <p style="font-size:11px;color:#aaa;margin-top:24px;">Notifica automatica · PriceAlert via GitHub Actions</p>
    </body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(EMAIL_FROM, EMAIL_PASSWORD)
            srv.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"[Email] Sent: {len(new_listings)} listings for '{search_query}'")
    except Exception as e:
        print(f"[Email] Error: {e}")


# ── MAIN ─────────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*60}")
    print(f"PriceAlert Scraper — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    searches = load_config()
    if not searches:
        print("No active searches found. Exiting.")
        return

    seen = load_seen()
    total_new = 0

    for search in searches:
        query     = search.get("query", "")
        price_min = float(search.get("min", 0))
        price_max = float(search.get("max", 9999))
        platforms = search.get("platforms", ["ebay", "subito"])

        print(f"\n── Searching: '{query}' | €{price_min}–€{price_max} | {platforms}")

        # Generate AI variants
        variants = generate_variants(query)

        all_listings = []
        if "ebay" in platforms:
            all_listings += search_ebay(query, variants, price_min, price_max)
        if "subito" in platforms:
            all_listings += search_subito(query, variants, price_min, price_max)

        # Filter new
        new_listings = []
        for listing in all_listings:
            uid = make_id(listing["url"])
            if uid not in seen and listing["url"]:
                new_listings.append(listing)
                seen.add(uid)

        print(f"→ New listings: {len(new_listings)}")
        total_new += len(new_listings)

        if new_listings:
            send_email(new_listings, query)

        time.sleep(2)  # polite delay between searches

    save_seen(seen)
    print(f"\n{'='*60}")
    print(f"Done. Total new listings found: {total_new}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
