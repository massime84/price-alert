#!/usr/bin/env python3
"""
PriceAlert Scraper - Subito.it + eBay
- Legge config da GitHub (dashboard) o locale
- Ordina email: più recenti prima, evidenza annunci vicini al prezzo minimo
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

EMAIL_FROM     = os.environ.get("EMAIL_FROM", "")
EMAIL_TO       = os.environ.get("EMAIL_TO", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EBAY_APP_ID    = os.environ.get("EBAY_APP_ID", "")

GITHUB_CONFIG_URL = "https://raw.githubusercontent.com/massime84/price-alert/main/price-alert-config.json"
CONFIG_FILE    = "price-alert-config.json"
SEEN_FILE      = os.path.expanduser("~/price-alert/seen_listings.json")


def load_config():
    try:
        r = requests.get(GITHUB_CONFIG_URL, timeout=10)
        r.raise_for_status()
        data = r.json()
        print(f"[Config] Caricato da GitHub.")
    except Exception:
        print(f"[Config] Uso file locale.")
        if not os.path.exists(CONFIG_FILE):
            return []
        with open(CONFIG_FILE) as f:
            data = json.load(f)
    searches = [s for s in data.get("searches", []) if s.get("active", True)]
    print(f"[Config] {len(searches)} ricerche attive.")
    return searches


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def make_id(url):
    return hashlib.md5(url.encode()).hexdigest()


def search_ebay(query, price_min, price_max):
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
        "itemFilter(0).name": "MinPrice", "itemFilter(0).value": str(price_min),
        "itemFilter(0).paramName": "Currency", "itemFilter(0).paramValue": "EUR",
        "itemFilter(1).name": "MaxPrice", "itemFilter(1).value": str(price_max),
        "itemFilter(1).paramName": "Currency", "itemFilter(1).paramValue": "EUR",
        "itemFilter(2).name": "ListingType", "itemFilter(2).value": "AuctionWithBIN,FixedPrice",
        "itemFilter(3).name": "Condition", "itemFilter(3).value": "Used",
        "sortOrder": "StartTimeNewest",
        "outputSelector": "PictureURLSuperSize",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        items = (data.get("findItemsAdvancedResponse", [{}])[0]
                     .get("searchResult", [{}])[0]
                     .get("item", []))
        results = []
        for item in items:
            price_val = float(item.get("sellingStatus", [{}])[0]
                                  .get("currentPrice", [{}])[0]
                                  .get("__value__", 0))
            link = item.get("viewItemURL", [""])[0]
            if price_min <= price_val <= price_max and link:
                results.append({
                    "source": "eBay", "title": item.get("title", [""])[0],
                    "price": price_val, "url": link,
                    "image": item.get("pictureURLSuperSize", [""])[0] or item.get("galleryURL", [""])[0],
                    "location": item.get("location", ["Italia"])[0],
                    "date": item.get("listingInfo", [{}])[0].get("startTime", [""])[0],
                })
        print(f"[eBay] '{query}' → {len(results)} annunci")
        return results
    except Exception as e:
        print(f"[eBay] Errore: {e}")
        return []


def search_subito(query, price_min, price_max):
    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError:
        print("[Subito.it] Playwright/BS4 non installato.")
        return []

    query_enc = requests.utils.quote(query)
    url = (f"https://www.subito.it/annunci-italia/vendita/usato/"
           f"?q={query_enc}&qso=true&ps={int(price_min)}&pe={int(price_max)}&sort=datedesc")

    results = []
    try:
        with sync_playwright() as p:
            import shutil
            chrome_path = None
            for c in [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                shutil.which("google-chrome"), shutil.which("chromium"),
            ]:
                if c and os.path.exists(c):
                    chrome_path = c
                    break

            launch_opts = dict(headless=False, args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox", "--disable-infobars",
            ])
            if chrome_path:
                launch_opts["executable_path"] = chrome_path

            browser = p.chromium.launch(**launch_opts)
            context = browser.new_context(
                user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
                viewport={"width": 1280, "height": 800},
                locale="it-IT", timezone_id="Europe/Rome",
                extra_http_headers={"Accept-Language": "it-IT,it;q=0.9,en;q=0.8"},
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['it-IT','it','en'] });
                window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
            """)

            page = context.new_page()
            page.goto("https://www.subito.it/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2, 3))
            for btn in ["button:has-text('Accetta')", "button:has-text('Acconsento')"]:
                try:
                    page.click(btn, timeout=2000)
                    time.sleep(1)
                    break
                except Exception:
                    pass

            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2, 3))
            html = page.content()
            browser.close()

            if len(html) < 1000:
                print(f"[Subito.it] Pagina vuota per '{query}'")
                return []

            soup = BeautifulSoup(html, "html.parser")
            next_data = soup.find("script", {"id": "__NEXT_DATA__"})
            if not next_data:
                for script in soup.find_all("script"):
                    if script.string and '"pageName":"listing"' in (script.string or ""):
                        next_data = script
                        break

            if next_data and next_data.string:
                data = json.loads(next_data.string)
                items_data = (data.get("props", {}).get("pageProps", {})
                                  .get("initialState", {}).get("items", {}))
                ads = items_data.get("list", []) or []

                for ad_wrapper in ads:
                    try:
                        ad = ad_wrapper.get("item", ad_wrapper)
                        if not ad or ad.get("kind") != "AdItem":
                            continue
                        features = ad.get("features") or {}
                        price_feat = features.get("/price", {})
                        if not price_feat:
                            continue
                        price_val = float(str(price_feat.get("values", [{}])[0].get("key", 0)).replace(",", "."))
                        if not (price_min <= price_val <= price_max):
                            continue
                        urls = ad.get("urls", {}) or {}
                        link = urls.get("default", "") or ad.get("url", "")
                        if not link:
                            continue
                        images = ad.get("images", []) or []
                        image = ""
                        if images:
                            base = images[0].get("cdnBaseUrl", "")
                            image = base + "?rule=400x300" if base else ""
                        geo = ad.get("geo", {}) or {}
                        city = geo.get("city", {}) or {}
                        region = geo.get("region", {}) or {}
                        location = city.get("value", "") or region.get("value", "") or "Italia"
                        results.append({
                            "source": "Subito.it",
                            "title": ad.get("subject", ""),
                            "price": price_val,
                            "url": link,
                            "image": image,
                            "location": location,
                            "date": ad.get("date", ""),
                        })
                    except Exception:
                        pass

        print(f"[Subito.it] '{query}' → {len(results)} annunci")
        return results
    except Exception as e:
        print(f"[Subito.it] Errore: {e}")
        return []


def send_email(new_listings, search):
    if not all([EMAIL_FROM, EMAIL_TO, EMAIL_PASSWORD]):
        print("[Email] Credenziali mancanti.")
        return

    query     = search.get("query", "")
    price_min = float(search.get("min", 0))
    price_max = float(search.get("max", 9999))

    # Ordina: più recenti prima
    def sort_key(item):
        try:
            dt = datetime.fromisoformat(item["date"].replace("Z","")) if item.get("date") else datetime.min
        except Exception:
            dt = datetime.min
        return (-dt.timestamp(), item["price"])

    sorted_listings = sorted(new_listings, key=sort_key)
    subject = f"🔔 {len(sorted_listings)} nuovi annunci: {query} (€{price_min:.0f}–€{price_max:.0f})"

    cards_html = ""
    for item in sorted_listings:
        price_val  = item["price"]
        price_range = price_max - price_min
        proximity  = (price_val - price_min) / price_range if price_range > 0 else 1

        if proximity <= 0.33:
            price_color = "#27ae60"
            price_badge = "🟢 Ottimo prezzo"
        elif proximity <= 0.66:
            price_color = "#f39c12"
            price_badge = "🟡 Prezzo medio"
        else:
            price_color = "#e74c3c"
            price_badge = "🔴 Prezzo alto"

        source_color = "#0064D2" if item["source"] == "eBay" else "#e63f19"
        img_tag = f'<img src="{item["image"]}" width="120" height="90" style="border-radius:8px;margin-right:16px;object-fit:cover;flex-shrink:0;"/>' if item.get("image") else ""

        date_str = ""
        if item.get("date"):
            try:
                dt = datetime.fromisoformat(item["date"].replace("Z",""))
                date_str = dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                date_str = item["date"]

        cards_html += f"""
        <div style="border:1px solid #e0e0e0;border-radius:12px;padding:16px;margin-bottom:14px;
                    display:flex;align-items:flex-start;font-family:Arial,sans-serif;
                    border-left:4px solid {price_color};background:white;">
            {img_tag}
            <div style="flex:1;min-width:0;">
                <div style="margin-bottom:6px;display:flex;flex-wrap:wrap;gap:4px;">
                    <span style="background:{source_color};color:white;border-radius:4px;padding:2px 8px;font-size:12px;">{item['source']}</span>
                    <span style="background:{price_color};color:white;border-radius:4px;padding:2px 8px;font-size:12px;">{price_badge}</span>
                </div>
                <h3 style="margin:6px 0 4px;font-size:15px;color:#222;">{item['title']}</h3>
                <p style="font-size:24px;font-weight:bold;color:{price_color};margin:4px 0;">
                    €{price_val:.0f}
                    <span style="font-size:13px;color:#999;font-weight:normal;">(min €{price_min:.0f} · max €{price_max:.0f})</span>
                </p>
                <p style="color:#888;margin:4px 0;font-size:13px;">📍 {item['location']}</p>
                {"<p style='color:#aaa;margin:2px 0;font-size:12px;'>🕐 " + date_str + "</p>" if date_str else ""}
                <a href="{item['url']}" style="display:inline-block;margin-top:8px;background:#333;color:white;padding:7px 16px;border-radius:6px;text-decoration:none;font-size:13px;">Vedi annuncio →</a>
            </div>
        </div>"""

    body = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:620px;margin:auto;padding:20px;background:#f9f9f9;">
        <div style="background:white;border-radius:16px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
            <h2 style="margin-bottom:4px;color:#222;">🔔 Nuovi annunci trovati!</h2>
            <p style="color:#555;margin:4px 0;">Ricerca: <strong>{query}</strong> · Range: <strong>€{price_min:.0f}–€{price_max:.0f}</strong></p>
            <p style="color:#aaa;font-size:12px;margin:4px 0;">Trovati il {datetime.now().strftime('%d/%m/%Y alle %H:%M')} · Ordinati dal più recente</p>
            <hr style="margin:16px 0;border:none;border-top:1px solid #eee;"/>
            {cards_html}
            <p style="font-size:11px;color:#ccc;margin-top:24px;text-align:center;">PriceAlert · Notifica automatica</p>
        </div>
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
        print(f"[Email] Inviata: {len(sorted_listings)} annunci per '{query}'")
    except Exception as e:
        print(f"[Email] Errore: {e}")


def main():
    print(f"\n{'='*60}")
    print(f"PriceAlert Scraper — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    searches = load_config()
    if not searches:
        print("Nessuna ricerca attiva.")
        return

    seen = load_seen()
    total_new = 0

    for search in searches:
        query     = search.get("query", "")
        price_min = float(search.get("min", 0))
        price_max = float(search.get("max", 9999))
        platforms = search.get("platforms", ["ebay", "subito"])

        print(f"\n── Ricerca: '{query}' | €{price_min}–€{price_max} | {platforms}")

        all_listings = []
        if "ebay" in platforms:
            all_listings += search_ebay(query, price_min, price_max)
        if "subito" in platforms:
            all_listings += search_subito(query, price_min, price_max)

        new_listings = []
        for listing in all_listings:
            uid = make_id(listing["url"])
            if uid not in seen and listing["url"]:
                new_listings.append(listing)
                seen.add(uid)

        print(f"→ Nuovi: {len(new_listings)}")
        total_new += len(new_listings)

        if new_listings:
            send_email(new_listings, search)

        time.sleep(2)

    save_seen(seen)
    print(f"\n{'='*60}")
    print(f"Totale nuovi annunci: {total_new}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
