#!/usr/bin/env python3
"""
Price Alert Scraper - eBay + Subito.it
Searches for listings within a price range and sends email notifications.
"""

import os
import json
import smtplib
import requests
import hashlib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
import time
import random

# ── CONFIG FROM ENVIRONMENT VARIABLES ──────────────────────────────────────────
SEARCH_QUERY    = os.environ.get("SEARCH_QUERY", "macbook m1")
PRICE_MIN       = float(os.environ.get("PRICE_MIN", "250"))
PRICE_MAX       = float(os.environ.get("PRICE_MAX", "350"))
EMAIL_FROM      = os.environ.get("EMAIL_FROM", "")
EMAIL_TO        = os.environ.get("EMAIL_TO", "")
EMAIL_PASSWORD  = os.environ.get("EMAIL_PASSWORD", "")   # Gmail App Password
EBAY_APP_ID     = os.environ.get("EBAY_APP_ID", "")
SEEN_FILE       = "seen_listings.json"
# ────────────────────────────────────────────────────────────────────────────────


def load_seen() -> set:
    """Load already-notified listing IDs."""
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    """Persist seen listing IDs."""
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


# ── eBay SEARCH ─────────────────────────────────────────────────────────────────
def search_ebay() -> list[dict]:
    """Search eBay via Finding API (free, official)."""
    if not EBAY_APP_ID:
        print("[eBay] EBAY_APP_ID not set, skipping.")
        return []

    url = "https://svcs.ebay.com/services/search/FindingService/v1"
    params = {
        "OPERATION-NAME":        "findItemsAdvanced",
        "SERVICE-VERSION":       "1.0.0",
        "SECURITY-APPNAME":      EBAY_APP_ID,
        "RESPONSE-DATA-FORMAT":  "JSON",
        "REST-PAYLOAD":          "",
        "keywords":              SEARCH_QUERY,
        "paginationInput.entriesPerPage": "50",
        "itemFilter(0).name":    "MinPrice",
        "itemFilter(0).value":   str(PRICE_MIN),
        "itemFilter(0).paramName":  "Currency",
        "itemFilter(0).paramValue": "EUR",
        "itemFilter(1).name":    "MaxPrice",
        "itemFilter(1).value":   str(PRICE_MAX),
        "itemFilter(1).paramName":  "Currency",
        "itemFilter(1).paramValue": "EUR",
        "itemFilter(2).name":    "ListingType",
        "itemFilter(2).value":   "AuctionWithBIN,FixedPrice",
        "itemFilter(3).name":    "Condition",
        "itemFilter(3).value":   "Used",
        "sortOrder":             "StartTimeNewest",
        "outputSelector":        "PictureURLSuperSize",
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
            title     = item.get("title", [""])[0]
            price_val = float(item.get("sellingStatus", [{}])[0]
                              .get("currentPrice", [{}])[0]
                              .get("__value__", 0))
            link      = item.get("viewItemURL", [""])[0]
            image     = item.get("pictureURLSuperSize", [""])[0] or item.get("galleryURL", [""])[0]
            location  = item.get("location", ["Italia"])[0]
            date_str  = item.get("listingInfo", [{}])[0].get("startTime", [""])[0]

            if PRICE_MIN <= price_val <= PRICE_MAX:
                results.append({
                    "source":   "eBay",
                    "title":    title,
                    "price":    price_val,
                    "url":      link,
                    "image":    image,
                    "location": location,
                    "date":     date_str,
                })
        print(f"[eBay] Found {len(results)} listings in range.")
        return results
    except Exception as e:
        print(f"[eBay] Error: {e}")
        return []


# ── SUBITO.IT SEARCH ─────────────────────────────────────────────────────────────
def search_subito() -> list[dict]:
    """Search Subito.it via their internal search API (reverse-engineered)."""
    query_slug = SEARCH_QUERY.replace(" ", "%20")
    url = (
        f"https://www.subito.it/annunci-italia/vendita/usato/"
        f"?q={query_slug}"
        f"&qso=true"
        f"&ps={int(PRICE_MIN)}&pe={int(PRICE_MAX)}"
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
        time.sleep(random.uniform(1, 2))  # polite delay
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Try JSON-LD structured data first
        results = []
        script_tags = soup.find_all("script", {"type": "application/ld+json"})
        for tag in script_tags:
            try:
                data = json.loads(tag.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") not in ("Product", "Offer"):
                        continue
                    offers = item.get("offers", {})
                    price_val = float(offers.get("price", 0) or 0)
                    if PRICE_MIN <= price_val <= PRICE_MAX:
                        results.append({
                            "source":   "Subito.it",
                            "title":    item.get("name", ""),
                            "price":    price_val,
                            "url":      item.get("url", ""),
                            "image":    item.get("image", [""])[0] if isinstance(item.get("image"), list) else item.get("image", ""),
                            "location": offers.get("availableAtOrFrom", {}).get("name", "Italia"),
                            "date":     offers.get("priceValidUntil", ""),
                        })
            except Exception:
                pass

        # Fallback: parse HTML cards
        if not results:
            cards = soup.select("article[class*='item-card'], div[class*='AdItem']")
            for card in cards:
                try:
                    title_el = card.select_one("[class*='title'], h2")
                    price_el = card.select_one("[class*='price']")
                    link_el  = card.select_one("a[href]")
                    img_el   = card.select_one("img")

                    if not (title_el and price_el and link_el):
                        continue

                    price_text = price_el.get_text(strip=True).replace(".", "").replace(",", ".").replace("€", "").strip()
                    price_val  = float("".join(c for c in price_text if c.isdigit() or c == ".") or 0)
                    href = link_el.get("href", "")
                    if not href.startswith("http"):
                        href = "https://www.subito.it" + href

                    if PRICE_MIN <= price_val <= PRICE_MAX:
                        results.append({
                            "source":   "Subito.it",
                            "title":    title_el.get_text(strip=True),
                            "price":    price_val,
                            "url":      href,
                            "image":    img_el.get("src", "") if img_el else "",
                            "location": "Italia",
                            "date":     "",
                        })
                except Exception:
                    pass

        print(f"[Subito.it] Found {len(results)} listings in range.")
        return results

    except Exception as e:
        print(f"[Subito.it] Error: {e}")
        return []


# ── EMAIL NOTIFICATION ──────────────────────────────────────────────────────────
def send_email(new_listings: list[dict]):
    """Send a single email with all new listings."""
    if not all([EMAIL_FROM, EMAIL_TO, EMAIL_PASSWORD]):
        print("[Email] Missing credentials, skipping.")
        return

    subject = f"🔔 {len(new_listings)} nuovi annunci: {SEARCH_QUERY} ({PRICE_MIN}€–{PRICE_MAX}€)"

    # Build HTML body
    cards_html = ""
    for item in new_listings:
        img_tag = f'<img src="{item["image"]}" width="120" style="border-radius:8px;margin-right:16px;" />' if item.get("image") else ""
        cards_html += f"""
        <div style="border:1px solid #e0e0e0;border-radius:12px;padding:16px;margin-bottom:16px;display:flex;align-items:center;font-family:Arial,sans-serif;">
            {img_tag}
            <div>
                <span style="background:{'#0064D2' if item['source']=='eBay' else '#e63f19'};color:white;border-radius:4px;padding:2px 8px;font-size:12px;">{item['source']}</span>
                <h3 style="margin:8px 0 4px;">{item['title']}</h3>
                <p style="font-size:22px;font-weight:bold;color:#2ecc71;margin:0;">€{item['price']:.2f}</p>
                <p style="color:#888;margin:4px 0;">📍 {item['location']}</p>
                <a href="{item['url']}" style="display:inline-block;margin-top:8px;background:#333;color:white;padding:8px 16px;border-radius:6px;text-decoration:none;">Vedi annuncio →</a>
            </div>
        </div>"""

    body = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px;">
        <h2>🔔 Nuovi annunci trovati!</h2>
        <p>Ricerca: <strong>{SEARCH_QUERY}</strong> &nbsp;|&nbsp; Prezzo: <strong>€{PRICE_MIN} – €{PRICE_MAX}</strong></p>
        <p style="color:#888;font-size:13px;">Trovati il {datetime.now().strftime('%d/%m/%Y alle %H:%M')}</p>
        {cards_html}
        <hr style="margin-top:32px;" />
        <p style="font-size:12px;color:#aaa;">Notifica automatica via GitHub Actions</p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"[Email] Sent! ({len(new_listings)} listings)")
    except Exception as e:
        print(f"[Email] Error: {e}")


# ── MAIN ─────────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*60}")
    print(f"Searching: '{SEARCH_QUERY}' | €{PRICE_MIN} – €{PRICE_MAX}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    seen = load_seen()

    all_listings = search_ebay() + search_subito()

    new_listings = []
    for listing in all_listings:
        uid = make_id(listing["url"])
        if uid not in seen and listing["url"]:
            new_listings.append(listing)
            seen.add(uid)

    print(f"\n→ New listings to notify: {len(new_listings)}")

    if new_listings:
        send_email(new_listings)

    save_seen(seen)
    print("\nDone ✓")


if __name__ == "__main__":
    main()
