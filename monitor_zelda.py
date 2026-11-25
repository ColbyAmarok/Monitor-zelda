#!/usr/bin/env python3
"""
Monitor Switch 2 Zelda 40 aniversario.
Alerta (push al celular vía ntfy) cuando una tienda tiene STOCK y precio <= MAX_PRICE.
Las dos condiciones se combinan: stock a 14,999 o menos = alerta.
NO compra nada: el pago lo haces tú.

Instalación:
    pip install playwright requests
    playwright install chromium

Uso:
    python monitor_zelda.py            # revisa una vez (úsalo con cron)
    python monitor_zelda.py --loop 10  # revisa cada 10 minutos
"""
import json, os, re, sys, time, argparse
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright

# ---------------- CONFIGURACIÓN ----------------
MAX_PRICE = 14999
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "cambia-esto-por-un-nombre-unico-zelda-123")  # en GitHub se toma del Secret NTFY_TOPIC

# Pega aquí el link EXACTO de la consola en cada tienda.
URLS = {
    "PalacioDeHierro": "https://www.elpalaciodehierro.com/nintendo-nintendo-switch-2-edicion-del-40.%C2%BA-aniversario-the-legend-of-zelda-45792124.html",
    "Soriana": "https://www.soriana.com/nintendo-switch-2-edicion-the-legend-of-zelda-40-aniversario/11948948.html",
    "Liverpool":     "PEGA_AQUI_LINK_LIVERPOOL",
    "Sears":         "https://www.sears.com.mx/producto/4878020/consola-nintendo-switch-2-tloz-40th-anniversary",
    "Coppel":        "PEGA_AQUI_LINK_COPPEL",
    "Sanborns":      "PEGA_AQUI_LINK_SANBORNS",
    "Walmart":       "https://www.walmart.com.mx/ip/Nintendo-Switch-2-Zelda-40th/00004549688543",
    "Amazon":        "https://www.amazon.com.mx/Nintendo-SwitchTM-Legend-ZeldaTM-Anniversary/dp/B0HJ6F8L6V",
    "MercadoLibre":  "PEGA_AQUI_LINK_MERCADOLIBRE",
}

STATE_FILE = Path("estado_alertas.json")
OUT_WORDS = ["agotado", "sin stock", "no disponible", "out of stock", "no disponible por el momento"]
IN_WORDS = ["agregar al carrito", "añadir al carrito", "comprar ahora", "agregar a la bolsa", "add to cart"]
# ------------------------------------------------


def parse_jsonld(html):
    """Intenta leer precio y disponibilidad desde schema.org (JSON-LD)."""
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
    """Plan B: busca texto de botones y un precio tipo $13,299."""
    low = text.lower()
    in_stock = None
    if any(w in low for w in IN_WORDS) and not any(w in low for w in OUT_WORDS):
        in_stock = True
    elif any(w in low for w in OUT_WORDS):
        in_stock = False
    nums = [float(n.replace(",", "")) for n in re.findall(r'\$\s?(\d{1,2},\d{3})(?:\.\d{2})?', text)]
    nums = [n for n in nums if 8000 <= n <= 25000]  # filtra ruido (accesorios, meses sin intereses)
    return (min(nums) if nums else None), in_stock


def check(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)
    html = page.content()
    price, stock = parse_jsonld(html)
    if price is None or stock is None:
        p2, s2 = fallback_parse(page.inner_text("body"))
        price = price if price is not None else p2
        stock = stock if stock is not None else s2
    return price, stock


def notify(title, msg, url):
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=msg.encode("utf-8"),
        headers={"Title": title.encode("utf-8"), "Click": url, "Priority": "urgent", "Tags": "video_game"},
        timeout=15,
    )


def run_once():
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(locale="es-MX", user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"))
        page = ctx.new_page()
        for store, url in URLS.items():
            if url.startswith("PEGA_AQUI"):
                continue
            try:
                price, stock = check(page, url)
            except Exception as e:
                print(f"[{store}] error: {e}")
                continue
            ok = bool(stock) and price is not None and price <= MAX_PRICE
            print(f"[{store}] precio={price} stock={stock} -> {'ALERTA' if ok else 'nada'}")
            # Solo avisa cuando pasa de "no cumple" a "cumple" (evita spam)
            if ok and not state.get(store):
                notify(f"Zelda Switch 2 en {store}", f"Hay stock a ${price:,.0f}. Entra y paga tú.", url)
            state[store] = ok
        browser.close()
    STATE_FILE.write_text(json.dumps(state))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, help="minutos entre revisiones")
    args = ap.parse_args()
    if args.loop:
        while True:
            run_once()
            time.sleep(args.loop * 60)
    else:
        run_once()
      
