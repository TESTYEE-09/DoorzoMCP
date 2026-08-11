"""Normalization and deal scoring for doorzo search items."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

# Verified live from MixSearch responses (Type -> shop name).
SHOP_TYPES: dict[int, str] = {
    1: "mercari",
    2: "rakuma",
    3: "paypay_mall",
    5: "paypay_flea",
    6: "rakuten",
    7: "yahoo_auction",
    9: "amazon",
    10: "lashinbang",
    12: "snkrdunk",
}

_HEX_ONLY = re.compile(r"^[0-9a-f]+$")
PRICE_SENTINELS = {9_999_999, 542_559_090}

# doorzo's backend localizes shop conditions to Chinese; map to English.
# Observed set is complete across all 9 shops; unknown strings pass through.
CONDITION_EN: dict[str, str] = {
    "未使用": "Unused",
    "没有明显的损伤或污渍": "No obvious damage or stains",
    "有些许损伤或污渍": "Minor damage or stains",
    "接近未使用": "Nearly unused",
    "有损伤或污渍": "Damage or stains",
    "整体状态不佳": "Poor overall condition",
}


def decode_url(raw: str) -> str:
    """Item URLs arrive hex-encoded; some shops send raw ids instead."""
    if not raw:
        return ""
    if _HEX_ONLY.match(raw) and len(raw) % 2 == 0:
        try:
            decoded = bytes.fromhex(raw).decode(errors="replace")
        except ValueError:
            return raw
        if decoded.startswith(("http://", "https://")):
            return decoded
    return raw


DOORZO_ROUTES = {
    "mercari": "mercari",
    "rakuma": "rakuma",
    "paypay_mall": "paypay",
    "paypay_flea": "market",
    "rakuten": "rakuten",
    "yahoo_auction": "yahoo",
    "amazon": "amazon",
    "lashinbang": "lashinbang",
    "snkrdunk": "snkrdunk",
}


def doorzo_url(shop: str, item_id: Any) -> str:
    """Build Doorzo's native product-detail route for a normalized listing."""
    route = DOORZO_ROUTES.get(shop)
    if not route or not item_id:
        return "https://www.doorzo.com/en"
    return f"https://www.doorzo.com/en/mall/{route}/detail/{quote(str(item_id), safe='')}"


def _int_or_zero(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def normalize(item: dict) -> dict:
    """Map a raw MixSearch item to the normalized shape tools return."""
    price = _int_or_zero(item.get("JPYPrice"))
    bid = _int_or_zero(item.get("BidJPYPrice"))
    buy_now = _int_or_zero(item.get("BuyNowPrice"))
    origin = _int_or_zero(item.get("OriginPrice"))
    if bid in PRICE_SENTINELS:
        bid = 0  # no-price sentinel ("price on request")
    if buy_now in PRICE_SENTINELS:
        buy_now = 0  # sentinel for "no buy-now price set"
    if buy_now > 0:
        price = buy_now
    elif bid > 0:
        price = bid
    elif price in PRICE_SENTINELS:
        # Mercari-style "price on request" placeholder (¥9,999,999).
        price = 0
    shop = SHOP_TYPES.get(_int_or_zero(item.get("Type")), f"shop_{item.get('Type')}")
    original_url = decode_url(item.get("Url") or "")
    item_id = item.get("Asin") or original_url
    if not item_id:
        item_id = f"{shop}:{item.get('Name') or ''}:{price}:{item.get('ImageUrl') or ''}"
    if origin in PRICE_SENTINELS:
        origin = 0
    discount_pct = round(100 * (1 - price / origin)) if price > 0 and origin > 0 else 0
    out: dict = {
        "id": item_id,
        "name": item.get("Name") or "",
        "shop": shop,
        "price_jpy": price,
        "origin_jpy": origin,
        "discount_pct": discount_pct,
        "condition": CONDITION_EN.get(item.get("Condition") or "", item.get("Condition") or ""),
        "property": item.get("Property") or "",
        "image_url": item.get("ImageUrl") or "",
        "original_url": original_url,
        "doorzo_url": doorzo_url(shop, item.get("Url") or item_id),
        "auction": None,
    }
    if shop == "yahoo_auction" and (bid or buy_now):
        out["auction"] = {
            "bid_jpy": bid,
            "buy_now_jpy": buy_now,
            "remaining_time": item.get("RemainingTime") or "",
        }
    return out


def is_deal(
    item: dict, max_price_jpy: int | None = None, min_discount_pct: int = 0
) -> tuple[bool, str]:
    """Threshold + discount deal model.

    Threshold always applies. When an origin (list) price exists, a real
    discount below origin is required; min_discount_pct only applies when
    origin data exists. Without origin price and with min_discount_pct > 0
    the item is NOT a deal (discount cannot be verified).
    """
    price = item["price_jpy"]
    if price <= 0:
        return False, "no price"
    if max_price_jpy is not None and price > max_price_jpy:
        return False, f"over max ¥{max_price_jpy}"
    origin = item["origin_jpy"]
    if origin > 0:
        if price >= origin:
            return False, "no discount vs origin"
        disc = item["discount_pct"]
        if min_discount_pct > 0 and disc < min_discount_pct:
            return False, f"discount {disc}% < {min_discount_pct}%"
        return True, f"{disc}% off origin ¥{origin}"
    if min_discount_pct > 0:
        return False, "no origin price to verify discount"
    return True, "under max price"
