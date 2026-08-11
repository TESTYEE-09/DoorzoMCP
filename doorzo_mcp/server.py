"""MCP server: doorzo-deals — search doorzo.com for deals and alert on monitors.

Run: uv run doorzo-mcp  (stdio transport; register with `claude mcp add`).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastmcp import FastMCP

from doorzo_mcp import store
from doorzo_mcp.client import DoorzoClient, DoorzoError
from doorzo_mcp.deals import SHOP_TYPES, is_deal, normalize
from doorzo_mcp.notify import notify

mcp = FastMCP("doorzo-deals")

MAX_NOTIFICATIONS_PER_RUN = 5
VALID_SHOPS = sorted(SHOP_TYPES.values())


def _err(e: Exception) -> str:
    return json.dumps({"error": str(e)}, ensure_ascii=False)


def _check_shops(shops: list[str] | None) -> None:
    if shops is None:
        return
    invalid = [s for s in shops if s not in VALID_SHOPS]
    if invalid:
        raise ValueError(f"invalid shop(s) {invalid}; valid: {', '.join(VALID_SHOPS)}")


@mcp.tool()
def doorzo_search(
    keyword: str,
    max_price_jpy: int | None = None,
    shops: list[str] | None = None,
    sort: str = "recommended",
    only_in_stock: bool = True,
    min_discount_pct: int = 0,
    limit: int = 20,
) -> str:
    """Search doorzo.com across Japanese shops for a keyword.

    Args:
        keyword: search term (Japanese or English; the API translates).
        max_price_jpy: only items at or below this price (JPY).
        shops: restrict to shop names, e.g. ["mercari", "yahoo_auction"].
        sort: "recommended" (default), "price_asc", or "price_desc".
        only_in_stock: exclude sold-out items (default true).
        min_discount_pct: require at least this % off the origin price.
        limit: max items to return (default 20).

    Returns:
        JSON: {"query", "currency": "JPY", "items": [...]}; each item has
        id, name, shop, price_jpy, origin_jpy, discount_pct, condition,
        property, image_url, original_url, auction, deal, deal_reason.
    """
    try:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("keyword is required")
        if max_price_jpy is not None and max_price_jpy <= 0:
            raise ValueError("max_price_jpy must be greater than 0")
        if not 0 <= min_discount_pct <= 100:
            raise ValueError("min_discount_pct must be between 0 and 100")
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        if sort not in ("recommended", "price_asc", "price_desc"):
            raise ValueError(f"invalid sort '{sort}'; use recommended|price_asc|price_desc")
        _check_shops(shops)
        client = DoorzoClient()
        order_by = None if sort == "recommended" else sort
        items = client.search(keyword, only_in_stock=only_in_stock, order_by=order_by)
        out = []
        filters_active = max_price_jpy is not None or min_discount_pct > 0
        for raw in items:
            item = normalize(raw)
            if shops and item["shop"] not in shops:
                continue
            deal, reason = is_deal(item, max_price_jpy, min_discount_pct)
            item["deal"] = deal
            item["deal_reason"] = reason
            if filters_active and not deal:
                continue
            out.append(item)
        return json.dumps(
            {"query": keyword, "currency": "JPY", "items": out[:limit]},
            ensure_ascii=False,
        )
    except Exception as e:
        return _err(e)


@mcp.tool()
def doorzo_hot_searches() -> str:
    """Return doorzo's current hot/trending search keywords."""
    try:
        hot = DoorzoClient().hot_searches()
        return json.dumps(
            {"items": [{"keyword": h.get("T", ""), "value": h.get("V", "")} for h in hot]},
            ensure_ascii=False,
        )
    except Exception as e:
        return _err(e)


@mcp.tool()
def doorzo_exchange_rate(currency: str = "AUD") -> str:
    """Return the JPY -> currency exchange rate doorzo uses.

    Args:
        currency: ISO 4217 code, e.g. "AUD", "USD", "CNY".

    Returns:
        JSON: {"currency", "exchange", "symbol", "name", "Precision"}.
    """
    try:
        currency = currency.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a 3-letter code")
        rate = DoorzoClient().exchange_rate(currency)
        return json.dumps(rate, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def doorzo_monitor_add(
    name: str,
    keyword: str,
    max_price_jpy: int,
    shops: list[str] | None = None,
    min_discount_pct: int = 0,
    notify_enabled: bool = True,
) -> str:
    """Add a deal monitor: alert when items match keyword at/below price.

    Args:
        name: monitor label (e.g. "mario party").
        keyword: search term.
        max_price_jpy: price ceiling (JPY); items above it never alert.
        shops: optional shop restriction.
        min_discount_pct: require at least this % off origin price when an
            origin price exists; without origin data the item is skipped.
        notify_enabled: send macOS notifications on new matches (default true).

    Returns:
        JSON: the created monitor (id, name, keyword, ...).
    """
    try:
        name, keyword = name.strip(), keyword.strip()
        if not name or not keyword:
            raise ValueError("name and keyword are required")
        if max_price_jpy <= 0:
            raise ValueError("max_price_jpy must be greater than 0")
        if not 0 <= min_discount_pct <= 100:
            raise ValueError("min_discount_pct must be between 0 and 100")
        _check_shops(shops)
        mon = store.add_monitor(
            name=name,
            keyword=keyword,
            max_price_jpy=max_price_jpy,
            shops=shops,
            min_discount_pct=min_discount_pct,
            notify=notify_enabled,
        )
        return json.dumps(mon, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def doorzo_monitor_remove(monitor_id: str) -> str:
    """Remove a monitor by id (also drops its seen-item state)."""
    try:
        mon = store.remove_monitor(monitor_id)
        return json.dumps({"removed": mon["id"]}, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def doorzo_monitor_list() -> str:
    """List all monitors (id, keyword, price ceiling, last check stats)."""
    try:
        return json.dumps({"monitors": store.load_monitors()}, ensure_ascii=False)
    except Exception as e:
        return _err(e)


def _check_one(client: DoorzoClient, mon: dict, rate: dict) -> dict:
    items = client.search(
        mon["keyword"], only_in_stock=True, order_by="price_asc", max_pages=3
    )
    seen = store.get_seen(mon["id"])
    deals: list[dict] = []
    for raw in items:
        item = normalize(raw)
        if mon.get("shops") and item["shop"] not in mon["shops"]:
            continue
        ok, _reason = is_deal(item, mon["max_price_jpy"], mon.get("min_discount_pct", 0))
        if ok:
            deals.append(item)
    new = [d for d in deals if d["id"] not in seen]
    if new:
        for d in new:
            seen[d["id"]] = True
        store.set_seen(mon["id"], seen)
        store.append_alerts(mon["id"], mon["name"], new)
        aud = rate.get("exchange") or 0
        for d in new[:MAX_NOTIFICATIONS_PER_RUN]:
            if mon.get("notify", True):
                price = f"A${d['price_jpy'] * aud:.2f}" if aud else f"¥{d['price_jpy']:,}"
                notify(
                    f"{d['name'][:60]}",
                    f"{price} · {d['shop']}\n{d['doorzo_url']}",
                )
        store.update_monitor(
            mon["id"],
            last_checked_at=datetime.now(timezone.utc).isoformat(),
            last_new_count=len(new),
        )
    else:
        store.update_monitor(
            mon["id"],
            last_checked_at=datetime.now(timezone.utc).isoformat(),
            last_new_count=0,
        )
    return {
        "monitor": mon["name"],
        "monitor_id": mon["id"],
        "checked": len(items),
        "deals": len(deals),
        "new": new,
    }


@mcp.tool()
async def doorzo_check_monitors(
    monitor_id: str | None = None, watch_minutes: int = 0
) -> str:
    """Check monitors for NEW deals; notify and log matches.

    Args:
        monitor_id: check only this monitor (default: all).
        watch_minutes: if > 0, keep re-checking every 60s until this many
            minutes have elapsed (long-running call). Default 0 = one shot.

    Returns:
        JSON: {"checked_at", "rate_aud", "results": [per-monitor stats with
        "new" items]}. New matches are also sent as macOS notifications
        (max 5 per monitor run) and appended to ~/.doorzo-mcp/alerts.jsonl.
    """
    try:
        if not 0 <= watch_minutes <= 1440:
            raise ValueError("watch_minutes must be between 0 and 1440")
        client = DoorzoClient()
        rate = client.exchange_rate("AUD")
        monitors = store.load_monitors()
        if monitor_id is not None:
            try:
                monitors = [m for m in monitors if m["id"] == monitor_id]
                if not monitors:
                    raise KeyError(monitor_id)
            except KeyError:
                raise KeyError(f"monitor not found: {monitor_id}")
        if not monitors:
            raise ValueError("no monitors defined; add one with doorzo_monitor_add first")

        results: list[dict] = []
        import time as _time

        deadline = None if watch_minutes <= 0 else _time.monotonic() + watch_minutes * 60
        while True:
            run = await asyncio.to_thread(
                lambda: [_check_one(client, monitor, rate) for monitor in monitors]
            )
            results.extend(run)
            if deadline is None:
                break
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(60, remaining))
        return json.dumps(
            {
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "rate_aud": rate,
                "results": results,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return _err(e)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
