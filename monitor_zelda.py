#!/usr/bin/env python3
import json, os, re, sys, time, argparse
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright

MAX_PRICE = 14999
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "cambia-esto-por-un-nombre-unico-zelda-123")

URLS = {
    "PalacioDeHierro": "https://www.elpalaciodehierro.com/nintendo-nintendo-switch-2-edicion-del-40.%C2%BA-aniversario-the-legend-of-zelda-45792124.html",
    "Soriana": "https://www.soriana.com/nintendo-switch-2-edicion-the-legend-of-zelda-40-aniversario/11948948.html",
    "Sears": "https://www.sears.com.mx/producto/4878020/consola-nintendo-switch-2-tloz-40th-anniversary",
    "Walmart": "https://www.walmart.com.mx/ip/Nintendo-Switch-2-Zelda-40th/00004549688543",
    "Amazon": "https://www.amazon.com.mx/Nintendo-SwitchTM-Legend-ZeldaTM-Anniversary/dp/B0HJ6F8L6V",
}

STATE_FILE = Path("estado_alertas.json")
OUT_WORDS = ["agotado", "sin stock", "no disponible", "out of stock", "no disponible por el momento"]
STRONG_OUT = ["producto no disponible", "producto agotado", "actualmente no disponible", "no disponible por el momento", "currently unavailable", "sin existencias", "temporalmente agotado", "out of stock"]
IN_WORDS = ["agregar al carrito", "añadir al carrito", "comprar ahora", "agregar a la bolsa", "add to cart"]


def parse_jsonld(html):
    prices, in_stock = [], None
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if "offers" in node:
                    offers = node["offers"]
                    offers = offers if isinstance(offers, list) else [offers]
                    for o in offers:
                        if not isinstance(o, dict):
                            continue
                        p = o.get("price") or o.get("lowPrice")
                        try:
                            prices.append(float(str(p).replace(",", "")))
                        except Exception:
                            pass
                        if "InStock" in str(o.get("availability", "")):
                            in_stock = True
                        elif "OutOfStock" in str(o.get("availability", "")) and in_stock is None:
                            in_stock = False
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
    return (min(prices) if prices else None), in_stock


def fallback_parse(text):
    low = text.lower()
    in_stock = None
    if any(w in low for w in IN_WORDS) and not any(w in low for w in OUT_WORDS):
        in_stock = True
    elif any(w in low for w in OUT_WORDS):
        in_stock = False
    nums = [float(n.replace(",", "")) for n in re.findall(r'\$\s?(\d{1,2},\d{3})(?:\.\d{2})?', text)]
    nums = [n for n in nums if 8000 <= n <= 25000]
    return (min(nums) if nums else None), in_stock


def check(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)
    html = page.content()
    price, stock = parse_jsonld(html)
    body = page.inner_text("body")
    if price is None or stock is None:
        p2, s2 = fallback_parse(body)
        price = price if price is not None else p2
        stock = stock if stock is not None else s2
    low = body.lower()
    if stock and any(w in low for w in OUT_WORDS) and not any(w in low for w in IN_WORDS):
        stock = False
    if stock and any(w in low for w in STRONG_OUT):
        stock = False
    if stock:
        hits = [m for m in IN_WORDS + ["agotado", "no disponible"] if m in low]
        print("   evidencia en la pagina:", hits)
    if price is None and stock is None:
        print("   (no pude leer la página; texto inicial:)", body[:200].replace("\n", " "))
    return price, stock


def notify(title, msg, url):
    r = requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=msg.encode("utf-8"),
        headers={"Title": title.encode("utf-8"), "Click": url, "Priority": "urgent", "Tags": "video_game"},
        timeout=15,
    )
    print("   ntfy respondio:", r.status_code, "| tema con", len(NTFY_TOPIC), "caracteres")


def run_once():
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(locale="es-MX", user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"))
        page = ctx.new_page()
        for store, url in URLS.items():
            try:
                price, stock = check(page, url)
            except Exception as e:
                print(f"[{store}] error: {e}")
                continue
            ok = bool(stock) and price is not None and price <= MAX_PRICE
            print(f"[{store}] precio={price} stock={stock} -> {'ALERTA' if ok else 'nada'}")
            if ok and not state.get(store):
                notify(f"Zelda Switch 2 en {store}", f"Hay stock a ${price:,.0f}. Entra y paga tú.", url)
            state[store] = ok
        browser.close()
    STATE_FILE.write_text(json.dumps(state))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int)
    args = ap.parse_args()
    if args.loop:
        while True:
            run_once()
            time.sleep(args.loop * 60)
    else:
        run_once()
