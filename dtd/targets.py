"""Comment targets: a daily list of other accounts' recent reels worth a comment.

Instagram rewards accounts that join conversations in their niche, so each morning this picks
config.yaml comment_targets.per_day recent reels from tech, desk setup and gadget accounts and
gives each a comment from the rotating list. Kevin opens each reel and pastes the comment.
Nothing is posted from here: automated comments on other accounts are an Instagram spam signal.

Reels come from Business Discovery (named creator and business accounts) and hashtag search,
both on the Facebook Graph API through the Facebook Page linked to @daily_tech_drops
(FB_PAGE_ID, FB_PAGE_TOKEN). If neither works, the page still lists accounts to visit.

Writes docs/comments.html (on GitHub Pages next to the shop page) and state/comment_targets.json.
"""

import html
import json
import re
from datetime import datetime, timedelta, timezone

import requests

from .config import EASTERN, ROOT, env, read_state, write_state
from .facebook import API, page_token

MEDIA_FIELDS = "permalink,media_type,media_product_type,timestamp,like_count,comments_count,caption"
SKIP_WORDS = re.compile(r"\b(giveaway|contest|win a|sweepstakes|cyber ?security|hacker|malware)\b", re.I)
KEEP_DAYS = 14        # a reel is never listed twice; an account rests a day after being listed


class TargetsError(RuntimeError):
    pass


def _get(url: str, **params) -> dict:
    r = requests.get(url, params=params, timeout=60)
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", r.text)
        except ValueError:
            msg = r.text
        raise TargetsError(f"{r.status_code}: {msg[:300]}")
    return r.json()


def _connect() -> tuple[str, str]:
    """The Instagram account id behind the Facebook Page, and a token that can query it."""
    page, token = env("FB_PAGE_ID"), env("FB_PAGE_TOKEN")
    if not (page and token):
        raise TargetsError("FB_PAGE_ID and FB_PAGE_TOKEN are not set")
    token = page_token(page, token)
    ig = _get(f"{API}/{page}", fields="instagram_business_account", access_token=token).get("instagram_business_account", {}).get("id")
    if not ig:
        raise TargetsError("the Facebook Page has no linked Instagram account visible to this token")
    return ig, token


def _account(ig: str, token: str, username: str) -> dict:
    fields = f"business_discovery.username({username}){{username,name,followers_count,media.limit(12){{{MEDIA_FIELDS}}}}}"
    return _get(f"{API}/{ig}", fields=fields, access_token=token)["business_discovery"]


def _hashtag(ig: str, token: str, tag: str) -> list[dict]:
    found = _get(f"{API}/ig_hashtag_search", user_id=ig, q=tag, access_token=token).get("data") or []
    if not found:
        return []
    return _get(f"{API}/{found[0]['id']}/recent_media", user_id=ig, fields=MEDIA_FIELDS.replace(",media_product_type", ""),
                limit=30, access_token=token).get("data") or []


def _is_reel(m: dict) -> bool:
    return m.get("media_product_type") == "REELS" or (m.get("media_product_type") is None and m.get("media_type") == "VIDEO")


def _age_h(m: dict, now: datetime) -> float:
    return (now - datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")).total_seconds() / 3600


def _first_line(caption: str | None) -> str:
    line = (caption or "").strip().split("\n")[0]
    return line if len(line) <= 90 else line[:87].rstrip() + "..."


def collect(tc: dict, now: datetime) -> tuple[list[dict], dict]:
    """Every recent reel found, plus notes on what could not be checked."""
    notes = {"api": None, "skipped_accounts": [], "hashtags": {}}
    try:
        ig, token = _connect()
    except TargetsError as e:
        notes["api"] = str(e)
        return [], notes
    max_h = tc["max_age_days"] * 24
    found = []
    for name in tc["accounts"]:
        try:
            acct = _account(ig, token, name)
        except TargetsError as e:
            notes["skipped_accounts"].append({"username": name, "why": str(e)[:160]})
            if len(notes["skipped_accounts"]) == len(tc["accounts"]):
                notes["api"] = str(e)
            continue
        followers = acct.get("followers_count") or 0
        if not tc["min_followers"] <= followers <= tc["max_followers"]:
            continue
        for m in (acct.get("media") or {}).get("data", []):
            if not _is_reel(m) or _age_h(m, now) > max_h or SKIP_WORDS.search(m.get("caption") or ""):
                continue
            found.append({**m, "username": acct["username"], "followers": followers, "source": "account"})
    for tag in tc.get("hashtags") or []:
        try:
            media = _hashtag(ig, token, tag)
        except TargetsError as e:
            notes["hashtags"][tag] = str(e)[:160]
            continue
        kept = [m for m in media if _is_reel(m) and _age_h(m, now) <= max_h and not SKIP_WORDS.search(m.get("caption") or "")]
        notes["hashtags"][tag] = f"{len(kept)} recent videos"
        found += [{**m, "username": None, "followers": None, "source": f"#{tag}"} for m in kept]
    return found, notes


def _score(m: dict, now: datetime) -> float:
    """Fresh reels with a lively but not crowded comment section first: a comment is seen
    there, while on a reel with thousands it sinks at once."""
    fresh = max(0.0, 1 - _age_h(m, now) / 72)
    comments = m.get("comments_count") or 0
    room = 1.0 if 3 <= comments <= 300 else 0.6 if comments < 3 else 0.4
    likes = m.get("like_count") or 0
    pull = min(1.0, likes / max(m.get("followers") or 20000, 1) * 20)
    return round(2 * fresh + room + pull, 3)


def pick(tc: dict, found: list[dict], history: dict, now: datetime) -> list[dict]:
    seen = set(history.get("permalinks", {}))
    rested = {u for u, day in history.get("accounts", {}).items() if day == f"{now - timedelta(days=1):%Y-%m-%d}"}
    pool = [m for m in found if m.get("permalink") and m["permalink"] not in seen]
    pool.sort(key=lambda m: (m.get("username") not in rested, _score(m, now)), reverse=True)
    picks, used = [], set()
    for m in pool:
        key = m["username"] or m["permalink"]
        if key in used:
            continue  # one reel per account a day
        used.add(key)
        picks.append(m)
        if len(picks) == tc["per_day"]:
            break
    # Rotate through the comment list, starting where yesterday stopped, so no line repeats within a day.
    start = history.get("next_comment", 0)
    lines = tc["comments"]
    for i, m in enumerate(picks):
        m["comment"] = lines[(start + i) % len(lines)]
    history["next_comment"] = (start + len(picks)) % len(lines)
    return picks


def fallback(tc: dict, history: dict, now: datetime) -> list[dict]:
    """Without the API: a rotating set of accounts to visit, newest reel first."""
    names = tc["accounts"]
    start = history.get("next_account", 0)
    chosen = [names[(start + i) % len(names)] for i in range(min(tc["per_day"], len(names)))]
    history["next_account"] = (start + len(chosen)) % len(names)
    lines, c = tc["comments"], history.get("next_comment", 0)
    out = [{"username": n, "permalink": f"https://www.instagram.com/{n}/reels/", "comment": lines[(c + i) % len(lines)],
            "source": "account", "fallback": True} for i, n in enumerate(chosen)]
    history["next_comment"] = (c + len(out)) % len(lines)
    return out


def page(data: dict) -> str:
    e = html.escape
    cards = []
    for i, t in enumerate(data["targets"], 1):
        who = f'@{e(t["username"])}' if t.get("username") else e(t["source"])
        facts = []
        if t.get("followers"):
            facts.append(f'{t["followers"]:,} followers')
        if t.get("age_h") is not None:
            facts.append(f'{t["age_h"]:.0f}h ago' if t["age_h"] >= 1 else "just posted")
        if t.get("comments_count") is not None:
            facts.append(f'{t["comments_count"]} comments')
        if t.get("fallback"):
            facts.append("open their newest reel")
        about = f'<p class="about">{e(t["about"])}</p>' if t.get("about") else ""
        cards.append(f"""<div class="item" data-key="{e(t['permalink'])}">
<div class="top"><span class="n">{i}</span><div><b>{who}</b><span class="sub">{e(' · '.join(facts))}</span></div>
<label class="done"><input type="checkbox"> Done</label></div>{about}
<p class="comment">{e(t['comment'])}</p>
<div class="btns"><button class="copy" data-text="{e(t['comment'])}">Copy comment</button>
<a class="open" href="{e(t['permalink'])}" target="_blank" rel="noopener">Open reel</a></div></div>""")
    if not cards:
        cards.append('<div class="item"><p class="comment">No new reels found today. The list refreshes tomorrow morning.</p></div>')
    note = ""
    if data.get("mode") == "accounts":
        note = '<p class="note">Instagram did not share reel links today, so each card opens the account\'s reels. Comment on the newest one.</p>'
    skipped = data["notes"].get("skipped_accounts") or []
    skipped_html = ""
    if skipped and data.get("mode") == "reels":
        skipped_html = '<p class="note">Could not be checked (personal accounts or renamed): ' + e(", ".join(s["username"] for s in skipped)) + "</p>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Comment list · Daily Tech Drops</title>
<link rel="icon" href="img/logo.png"><link rel="apple-touch-icon" href="img/logo.png"><meta name="theme-color" content="#FBF6EE">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;800&display=swap" rel="stylesheet">
<style>
:root {{ --bg:#FBF6EE; --ink:#3B2F27; --muted:#7A6A5D; --accent:#E8792B; --accent-soft:#FBE7D6; --card:#fff; --line:#F1E8DC; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 Inter, system-ui, sans-serif; -webkit-font-smoothing:antialiased; }}
main {{ max-width:520px; margin:0 auto; padding:28px 16px 48px; }}
h1 {{ font:800 26px/1.15 Inter, system-ui, sans-serif; letter-spacing:-.02em; margin:0; }}
p.sub, .note {{ color:var(--muted); margin:4px 0 0; font-size:14px; }}
.how {{ background:var(--accent-soft); border-radius:14px; padding:12px 14px; font-size:14px; margin:18px 0; }}
.how b {{ font-weight:600; }}
.item {{ background:var(--card); border-radius:18px; padding:14px; margin-bottom:12px; box-shadow:0 1px 2px rgba(59,47,39,.05), 0 6px 18px rgba(59,47,39,.06); }}
.item.is-done {{ opacity:.45; }}
.top {{ display:flex; gap:10px; align-items:flex-start; }}
.top > div {{ flex:1; min-width:0; }}
.n {{ flex:none; width:26px; height:26px; border-radius:50%; background:var(--accent-soft); color:var(--accent); font-weight:600; font-size:13px; display:grid; place-items:center; }}
.sub {{ display:block; color:var(--muted); font-size:13px; }}
.done {{ flex:none; font-size:13px; color:var(--muted); display:flex; gap:4px; align-items:center; }}
.about {{ color:var(--muted); font-size:13px; margin:8px 0 0; overflow-wrap:anywhere; }}
.comment {{ margin:10px 0; padding:10px 12px; background:var(--bg); border-radius:12px; }}
.btns {{ display:flex; gap:8px; }}
.btns > * {{ flex:1; text-align:center; font:600 15px Inter, system-ui, sans-serif; padding:11px; border-radius:12px; border:0; cursor:pointer; text-decoration:none; }}
.copy {{ background:var(--accent); color:#fff; }}
.open {{ background:var(--accent-soft); color:var(--ink); }}
</style></head><body><main>
<h1>Today's comment list</h1>
<p class="sub">{len(data['targets'])} reels for {e(data['day'])}. Refreshed every morning.</p>
<div class="how"><b>For each card:</b> tap <b>Copy comment</b>, tap <b>Open reel</b>, paste it as a comment, then tick Done.
Be logged in as <b>daily_tech_drops</b>. Space them out over the day if you can, and like the reel too.</div>
{note}
{''.join(cards)}
{skipped_html}
</main>
<script>
const day = {json.dumps(data['day'])};
let done = {{}};
try {{ done = JSON.parse(localStorage.getItem('dtd-comments-' + day) || '{{}}'); }} catch (e) {{}}
document.querySelectorAll('.item[data-key]').forEach(card => {{
  const box = card.querySelector('input'), key = card.dataset.key;
  const show = () => card.classList.toggle('is-done', box.checked);
  box.checked = !!done[key]; show();
  box.addEventListener('change', () => {{
    done[key] = box.checked; show();
    try {{ localStorage.setItem('dtd-comments-' + day, JSON.stringify(done)); }} catch (e) {{}}
  }});
}});
document.querySelectorAll('.copy').forEach(b => b.addEventListener('click', async () => {{
  try {{ await navigator.clipboard.writeText(b.dataset.text); }} catch (e) {{
    const t = document.createElement('textarea'); t.value = b.dataset.text; document.body.appendChild(t); t.select();
    document.execCommand('copy'); t.remove();
  }}
  const was = b.textContent; b.textContent = 'Copied'; setTimeout(() => b.textContent = was, 1500);
}}));
</script>
</body></html>
"""


def run(cfg: dict, dry_run: bool = False) -> int:
    tc = cfg["comment_targets"]
    now = datetime.now(timezone.utc)
    history = read_state("comment_targets", {})
    found, notes = collect(tc, now)
    targets = pick(tc, found, history, now) if found else []
    mode = "reels"
    if not targets and notes["api"]:
        targets, mode = fallback(tc, history, now), "accounts"
    for t in targets:
        if t.get("timestamp"):
            t["age_h"] = round(_age_h(t, now), 1)
        t["about"] = _first_line(t.pop("caption", None))
    day = f"{datetime.now(EASTERN):%A %B %-d}"
    data = {"day": day, "updated": f"{datetime.now(EASTERN):%Y-%m-%d %H:%M}", "mode": mode, "found": len(found),
            "targets": targets, "notes": notes}

    print(f"Mode: {mode}. Recent reels found: {len(found)}. Listed: {len(targets)}.")
    if notes["api"]:
        print(f"API: {notes['api']}")
    for tag, what in notes["hashtags"].items():
        print(f"#{tag}: {what}")
    for s in notes["skipped_accounts"]:
        print(f"Skipped @{s['username']}: {s['why']}")
    for t in targets:
        print(f"- @{t.get('username') or t['source']}  {t['permalink']}  ->  {t['comment']}")
    if dry_run:
        return 0

    today = f"{datetime.now(EASTERN):%Y-%m-%d}"
    cutoff = f"{datetime.now(EASTERN) - timedelta(days=KEEP_DAYS):%Y-%m-%d}"
    links = {k: v for k, v in history.get("permalinks", {}).items() if v >= cutoff}
    accounts = {k: v for k, v in history.get("accounts", {}).items() if v >= cutoff}
    for t in targets:
        if mode == "reels":
            links[t["permalink"]] = today
        if t.get("username"):
            accounts[t["username"]] = today
    history.update(permalinks=links, accounts=accounts, last=data)
    write_state("comment_targets", history)
    (ROOT / "docs" / "comments.html").write_text(page(data))
    return 0
