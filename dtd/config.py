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
    # Secrets override file values when present.
    cfg["amazon"]["tag"] = os.environ.get("AMAZON_TAG") or cfg["amazon"]["tag"]
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


def channel_link(cfg: dict, link: str, channel: str) -> str:
    """Swaps the base tag for the channel's own tracking ID (amazon.channel_tags), so the
    Associates reports show whether a sale came from the shop page, Facebook or YouTube.
    Channels without their own ID keep the base tag, so no link ever loses its tag.
    Campaign links are left exactly as Amazon issued them, so the bonus still tracks."""
    tag = (cfg["amazon"].get("channel_tags") or {}).get(channel)
    base = cfg["amazon"]["tag"]
    if not tag or not base or link in (cfg["amazon"].get("campaign_links") or {}).values():
        return link
    return re.sub(rf"([?&]tag=){re.escape(base)}(?=&|$)", rf"\g<1>{tag}", link)
