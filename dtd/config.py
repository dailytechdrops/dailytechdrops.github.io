"""Loads config.yaml, the product queue, and the small JSON state files."""

import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
OUTPUT_DIR = ROOT / "output"


def load_config() -> dict:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    # Secrets override file values when present.
    cfg["amazon"]["tag"] = os.environ.get("AMAZON_TAG") or cfg["amazon"]["tag"]
    return cfg


def load_products() -> list[dict]:
    return yaml.safe_load((ROOT / "products.yaml").read_text()) or []


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
    base = f"https://{cfg['amazon']['marketplace']}/dp/{asin}"
    tag = cfg["amazon"]["tag"]
    return f"{base}?tag={tag}" if tag else base
