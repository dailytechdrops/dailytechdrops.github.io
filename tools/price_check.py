"""One-off: print the live Amazon price, title and rating for a few ASINs."""
import re
import sys
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def grab(asin):
    r = requests.get(f"https://www.amazon.com/dp/{asin}",
                     headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                              "Accept": "text/html"}, timeout=30)
    html = r.text
    if "captcha" in html.lower() and "productTitle" not in html:
        return f"{asin} | {r.status_code} | CAPTCHA"
    title = re.search(r'id="productTitle"[^>]*>\s*([^<]+)', html)
    price = (re.search(r'class="a-price aok-align-center[^"]*"[^>]*>\s*<span class="a-offscreen">([^<]+)', html)
             or re.search(r'apex-pricetopay-value[^>]*>\s*<span class="a-offscreen">([^<]+)', html)
             or re.search(r'<span class="a-offscreen">(\$[\d.,]+)', html))
    rating = re.search(r'([\d.]+) out of 5 stars', html)
    count = re.search(r'id="acrCustomerReviewText"[^>]*>([^<]+)', html)
    avail = re.search(r'id="availability"[^>]*>\s*<span[^>]*>\s*([^<]+)', html)
    bought = re.search(r'([\dK+]+ bought in past month)', html)
    return " | ".join([asin, str(r.status_code),
                       price.group(1) if price else "no price",
                       rating.group(1) if rating else "-",
                       count.group(1).strip() if count else "-",
                       avail.group(1).strip() if avail else "-",
                       bought.group(1) if bought else "-",
                       (title.group(1).strip()[:90] if title else "no title")])


for a in sys.argv[1:]:
    try:
        print(grab(a), flush=True)
    except Exception as e:  # noqa: BLE001
        print(a, "ERROR", e)
    time.sleep(2)
