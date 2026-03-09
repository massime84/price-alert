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
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

# ── CONFIG ──────────────────────────────────────────────────────────
EMAIL_FROM     = os.environ.get("EMAIL_FROM", "")
EMAIL_TO       = os.environ.get("EMAIL_TO", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EBAY_APP_ID    = os.environ.get("EBAY_APP_ID", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
CONFIG_FILE    = "price-alert-config.json"
SEEN_FILE      = "seen_listings.json"
MAX_SUBITO_DESC_CHECKS = 30  # max annunci di cui leggere la descrizione per query
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


# ── AI QUERY VARIANTS ────────────────────────────────────────────────
def generate_variants(query: str) -> list[str]:
    """Use Claude AI to generate search variants including typos and abbreviations."""
    if not ANTHROPIC_KEY:
        print(f"[AI] No API key, using original query only: '{query}'")
        return [query]

    prompt = f"""Sei un esperto di ricerche su siti di annunci italiani come Subito.it ed eBay.
Per il prodotto "{query}", genera una lista di varianti di ricerca che includono:
- Errori di battitura comuni (es. "macbok", "machbook")
- Variazioni di spaziatura (es. "mac book", "macbook m 1")  
- Abbreviazioni comuni usate dai venditori italiani
- Varianti senza spazi o con spazi extra
- Eventuali nomi alternativi usati colloquialmente

Rispondi SOLO con un array JSON di stringhe, senza spiegazioni, senza markdown, senza backtick.
Massimo 8 varianti totali inclusa quella originale. Esempio formato: ["query1","query2","query3"]"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        r.raise_for_status()
        text = r.json()["content"][0]["text"].strip()
        # strip any accidental markdown fences
        text = text.replace("```json", "").replace("```", "").strip()
        variants = json.loads(text)
        if not isinstance(variants, list):
            raise ValueError("Not a list")
        # always include original
        if query not in variants:
            variants.insert(0, query)
        variants = list(dict.fromkeys(v.strip() for v in variants if v.strip()))[:8]
        print(f"[AI] Variants for '{query}': {variants}")
        return variants
    except Exception as e:
        print(f"[AI] Error generating variants: {e} — using original only")
        return [query]


# ── eBay SEARCH ──────────────────────────────────────────────────────
def search_ebay_single(query: str, price_min: float, price_max: float) -> list[dict]:
    if not EBAY_APP_ID:
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
        # Search in title AND description
        "itemFilter(4).name": "LocatedIn",
        "itemFilter(4).value": "IT",
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
def fetch_subito_description(url: str, headers: dict) -> str:
    """Fetch the full description of a Subito.it listing."""
    try:
        time.sleep(random.uniform(0.8, 1.5))
        r = requests.get(url, headers=headers, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        # Try common description selectors
        for sel in [
            "[class*='description']",
            "[class*='AdDescription']",
            "[class*='item-description']",
            "div[data-testid*='description']",
        ]:
            el = soup.select_one(sel)
            if el:
                return el.get_text(" ", strip=True).lower()
        return ""
    except Exception:
        return ""


def search_subito_single(query: str, price_min: float, price_max: float,
                          search_description: bool = True) -> list[dict]:
    query_enc = requests.utils.quote(query)
    url = (
        f"https://www.subito.it/annunci-italia/vendita/usato/"
        f"?q={query_enc}&qso=true"
        f"&ps={int(price_min)}&pe={int(price_max)}"
        f"&sort=datedesc"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "it-IT,it;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        time.sleep(random.uniform(1.5, 2.5))
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        results = []

        # Try JSON-LD first
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
                        })
            except Exception:
                pass

        # Fallback: parse HTML cards
        if not results:
            for card in soup.select("article[class*='item-card'], div[class*='AdItem']"):
                try:
                    title_el = card.select_one("[class*='title'], h2")
                    price_el = card.select_one("[class*='price']")
                    link_el  = card.select_one("a[href]")
                    img_el   = card.select_one("img")
                    if not (title_el and price_el and link_el):
                        continue
                    price_text = (price_el.get_text(strip=True)
                                  .replace(".", "").replace(",", ".")
                                  .replace("€", "").strip())
                    price_val = float("".join(c for c in price_text if c.isdigit() or c == ".") or 0)
                    href = link_el.get("href", "")
                    if not href.startswith("http"):
                        href = "https://www.subito.it" + href
                    if price_min <= price_val <= price_max and href:
                        results.append({
                            "source": "Subito.it",
                            "title": title_el.get_text(strip=True),
                            "price": price_val,
                            "url": href,
                            "image": img_el.get("src", "") if img_el else "",
                            "location": "Italia",
                            "date": "",
                            "matched_variant": query,
                        })
                except Exception:
                    pass

        # ── Description search ───────────────────────────────────────
        # Also search listings that might not match title but match description
        if search_description:
            query_lower = query.lower()
            checked = 0
            desc_results = []

            # Get ALL listings on page (without price filter for description check)
            all_cards = soup.select("article[class*='item-card'], div[class*='AdItem']")
            for card in all_cards:
                if checked >= MAX_SUBITO_DESC_CHECKS:
                    break
                try:
                    link_el  = card.select_one("a[href]")
                    price_el = card.select_one("[class*='price']")
                    title_el = card.select_one("[class*='title'], h2")
                    if not (link_el and price_el):
                        continue
                    price_text = (price_el.get_text(strip=True)
                                  .replace(".", "").replace(",", ".")
                                  .replace("€", "").strip())
                    price_val = float("".join(c for c in price_text if c.isdigit() or c == ".") or 0)
                    if not (price_min <= price_val <= price_max):
                        continue
                    href = link_el.get("href", "")
                    if not href.startswith("http"):
                        href = "https://www.subito.it" + href

                    # Skip if already found via title search
                    if any(r["url"] == href for r in results):
                        continue

                    # Fetch description
                    desc = fetch_subito_description(href, headers)
                    checked += 1
                    if query_lower in desc:
                        img_el = card.select_one("img")
                        desc_results.append({
                            "source": "Subito.it",
                            "title": (title_el.get_text(strip=True) if title_el else "Annuncio") + " 📝",
                            "price": price_val,
                            "url": href,
                            "image": img_el.get("src", "") if img_el else "",
                            "location": "Italia",
                            "date": "",
                            "matched_variant": query,
                            "found_in": "descrizione",
                        })
                except Exception:
                    pass

            if desc_results:
                print(f"[Subito.it] Found {len(desc_results)} extra listings via description for '{query}'")
            results.extend(desc_results)

        return results

    except Exception as e:
        print(f"[Subito.it] Error for '{query}': {e}")
        return []


def search_subito(query: str, variants: list[str], price_min: float, price_max: float) -> list[dict]:
    """Search Subito.it with all variants, deduplicate by URL."""
    all_results = {}
    for v in variants:
        results = search_subito_single(v, price_min, price_max, search_description=True)
        for r in results:
            uid = make_id(r["url"])
            if uid not in all_results:
                all_results[uid] = r
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
