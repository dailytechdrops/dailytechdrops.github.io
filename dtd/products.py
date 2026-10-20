"""Picks the next product to post, rotating lanes and never repeating."""

from .config import load_products, read_state


def next_product(cfg: dict) -> dict | None:
    history = read_state("history", [])
    posted = {h["asin"] for h in history}
    queue = [p for p in load_products() if p["asin"] not in posted]
    if not queue:
        return None

    # Prefer a different lane than yesterday so the feed stays varied.
    last_lane = history[-1]["lane"] if history else None
    for product in queue:
        if product.get("lane") != last_lane:
            return product
    return queue[0]
