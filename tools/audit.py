"""Social link audit: dumps Instagram and Facebook profile and post data, then checks every link.

Read-only. Prints a JSON report between AUDIT-JSON markers so it can be read from the run log.
"""

import json
import os
import re
import sys

import requests

IG = "https://graph.instagram.com/v23.0"
FB = "https://graph.facebook.com/v23.0"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")


def get(url, **params):
    try:
        r = requests.get(url, params=params, timeout=60)
        return r.json() if r.headers.get("content-type", "").startswith(("application/json", "text/javascript")) else {"raw": r.text[:300], "status": r.status_code}
    except Exception as e:
        return {"error": str(e)}


def paged(url, **params):
    out, data = [], get(url, **params)
    while True:
        if "error" in data:
            out.append({"_error": data["error"]})
            return out
        out += data.get("data", [])
        nxt = data.get("paging", {}).get("next")
        if not nxt or len(out) > 300:
            return out
        data = get(nxt)


def check(url):
    try:
        r = requests.get(url, headers=UA, timeout=30, allow_redirects=True)
        return {"status": r.status_code, "final": r.url, "title": (re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I) or [None, ""])[1].strip()[:120]}
    except Exception as e:
        return {"status": None, "error": str(e)[:200]}


def main():
    report = {}
    ig_user, ig_tok = os.environ.get("IG_USER_ID"), os.environ.get("IG_ACCESS_TOKEN")
    if ig_tok:
        report["ig_profile"] = get(f"{IG}/me", fields="user_id,username,name,account_type,biography,website,followers_count,follows_count,media_count,profile_picture_url", access_token=ig_tok)
        if "error" in report["ig_profile"]:
            report["ig_profile_basic"] = get(f"{IG}/me", fields="user_id,username,name,account_type,followers_count,media_count", access_token=ig_tok)
        report["ig_media"] = paged(f"{IG}/{ig_user}/media", fields="id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count", limit=50, access_token=ig_tok)

    page, ftok = os.environ.get("FB_PAGE_ID"), os.environ.get("FB_PAGE_TOKEN")
    if page and ftok:
        pt = get(f"{FB}/{page}", fields="access_token", access_token=ftok).get("access_token") or ftok
        report["fb_page"] = get(f"{FB}/{page}", fields="name,username,about,description,website,link,category,fan_count,followers_count,emails,phone,verification_status,instagram_business_account,connected_instagram_account", access_token=pt)
        if "error" in report["fb_page"]:
            report["fb_page_basic"] = get(f"{FB}/{page}", fields="name,about,website,link,category,fan_count,followers_count", access_token=pt)
        report["fb_posts"] = paged(f"{FB}/{page}/posts", fields="id,message,permalink_url,created_time,status_type", limit=50, access_token=pt)
        report["fb_videos"] = paged(f"{FB}/{page}/videos", fields="id,description,permalink_url,created_time", limit=50, access_token=pt)
        report["fb_cta"] = get(f"{FB}/{page}/call_to_actions", fields="type,web_url,status", access_token=pt)

    pages = {u: None for u in ["https://beacons.ai/dailytechdrops", "https://kevingalus.github.io/daily-tech-drops/"]}
    for u in list(pages):
        try:
            r = requests.get(u, headers=UA, timeout=30)
            pages[u] = {"status": r.status_code, "links": sorted(set(URL_RE.findall(r.text))), "len": len(r.text)}
        except Exception as e:
            pages[u] = {"error": str(e)}
    report["pages"] = pages

    text = json.dumps({k: v for k, v in report.items() if k != "pages"})
    urls = set(URL_RE.findall(text.replace("\\n", " ").replace("\\/", "/")))
    for p in pages.values():
        urls |= {u for u in p.get("links", []) if not re.search(r"\.(js|css|png|jpg|jpeg|webp|svg|woff2?|ico)(\?|$)|fonts\.g|cdn|static|googletagmanager|schema\.org|w3\.org", u)}
    urls = {u.rstrip(".,!") for u in urls if "fbcdn" not in u and "cdninstagram" not in u and "graph." not in u}
    report["link_checks"] = {u: check(u) for u in sorted(urls)}

    print("AUDIT-JSON-START")
    print(json.dumps(report, indent=1, ensure_ascii=False))
    print("AUDIT-JSON-END")


if __name__ == "__main__":
    sys.exit(main())
