"""Loads config.yaml, the weekly product files, and the small JSON state files."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
OUTPUT_DIR = ROOT / "output"
WEEKS_DIR = ROOT / "weeks"
EASTERN = ZoneInfo("America/New_York")


def load_config() -> dict:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    # The tag in config.yaml wins: it is public in every link anyway, and keeping it in the file means
    # a new Associates store ID takes effect without touching the AMAZON_TAG secret (Nov 4 2026).
    cfg["amazon"]["tag"] = cfg["amazon"]["tag"] or os.environ.get("AMAZON_TAG", "")
    return cfg


def load_week(path: Path) -> list[dict]:
    """One week's products, each with an id and a timezone-aware posting time."""
    items = yaml.safe_load(path.read_text()) or []
    for item in items:
        when = datetime.strptime(str(item["slot"]), "%Y-%m-%d %H:%M").replace(tzinfo=EASTERN)
        item["when"] = when
        item["id"] = f"{when:%Y-%m-%d-%H%M}-{item['asin']}"
    return items


def load_all_weeks() -> list[dict]:
    return [item for path in sorted(WEEKS_DIR.glob("*.yaml")) for item in load_week(path)]


def read_state(name: str, default):
    path = STATE_DIR / f"{name}.json"
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_state(name: str, data) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / f"{name}.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def affiliate_link(cfg: dict, asin: str) -> str:
    """A Creator Connections campaign link when the ASIN has one (amazon.campaign_links),
    since only that link earns the brand's bonus commission; otherwise the tagged product link."""
    campaign = (cfg["amazon"].get("campaign_links") or {}).get(asin)
    if campaign:
        return campaign
    base = f"https://{cfg['amazon']['marketplace']}/dp/{asin}"
    tag = cfg["amazon"]["tag"]
    return f"{base}?tag={tag}" if tag else base


def retag(cfg: dict, text: str) -> str:
    """Rewrites links saved under a closed store ID (amazon.retired_tags) to the current tag, so
    reels rendered and products posted before a store ID change keep earning. A Creator Connections
    link from a retired store becomes the plain tagged product link, since its campaign died with it."""
    retired = cfg["amazon"].get("retired_tags") or []
    tag = cfg["amazon"]["tag"]
    if not text or not retired or not tag:
        return text
    old = "|".join(re.escape(t) for t in retired)
    text = re.sub(rf"https://[^\s\"']*?/dp/([A-Z0-9]{{10}})\?[^\s\"']*?campaignId=[^\s\"']*?tag=(?:{old})[^\s\"']*",
                  lambda m: affiliate_link(cfg, m.group(1)), text)
    return re.sub(rf"([?&]tag=)(?:{old})(?=&|$|[\s\"'<)])", rf"\g<1>{tag}", text)


def channel_link(cfg: dict, link: str, channel: str) -> str:
    """Swaps the base tag for the channel's own tracking ID (amazon.channel_tags), so the
    Associates reports show whether a sale came from the shop page, Facebook or YouTube.
    Channels without their own ID keep the base tag, so no link ever loses its tag.
    Campaign links are left exactly as Amazon issued them, so the bonus still tracks."""
    link = retag(cfg, link)
    tag = (cfg["amazon"].get("channel_tags") or {}).get(channel)
    base = cfg["amazon"]["tag"]
    if not tag or not base or link in (cfg["amazon"].get("campaign_links") or {}).values():
        return link
    return re.sub(rf"([?&]tag=){re.escape(base)}(?=&|$)", rf"\g<1>{tag}", link)
