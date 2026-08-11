"""Normalization and deal scoring for doorzo search items."""

from __future__ import annotations

import re
from typing import Any

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
    if bid >= 9999999:
        bid = 0  # no-price sentinel ("price on request")
    if buy_now >= 9999999:
        buy_now = 0  # sentinel for "no buy-now price set"
    if buy_now > 0:
        price = buy_now
    elif bid > 0:
        price = bid
    elif price >= 9999999:
        # Mercari-style "price on request" placeholder (¥9,999,999).
        price = 0
    shop = SHOP_TYPES.get(_int_or_zero(item.get("Type")), f"shop_{item.get('Type')}")
    item_id = item.get("Asin") or decode_url(item.get("Url") or "")
    discount_pct = round(100 * (1 - price / origin)) if origin > 0 else 0
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
        "original_url": decode_url(item.get("Url") or ""),
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
