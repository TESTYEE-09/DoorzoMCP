"""FastAPI web UI for the Doorzo deal monitor.

Runs the same search/deal/monitor logic as the MCP server behind a small
JSON API plus a single-file vanilla-JS frontend (no build step, no CDN).

Run: uv run doorzo-web   (binds 127.0.0.1:8756 by default; override with
DOORZO_WEB_HOST / DOORZO_WEB_PORT).
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from doorzo_mcp import store
from doorzo_mcp.client import DoorzoError
from doorzo_mcp.deals import SHOP_TYPES
from doorzo_mcp import server as mcp_tools

app = FastAPI(title="Doorzo Deal Monitor", version="1.0.0")

STATIC_DIR = Path(__file__).parent / "static"
VALID_SHOPS = sorted(SHOP_TYPES.values())


def _unpack(payload: str) -> dict:
    """Parse a tool's JSON-string result, mapping tool errors to HTTP."""
    data = json.loads(payload)
    if isinstance(data, dict) and "error" in data:
        message = str(data["error"])
        if "monitor not found" in message:
            status = 404
        elif "already exists" in message:
            status = 409
        elif message.startswith(("Sig.", "doorzo ")) or "HTTP status" in message:
            status = 502
        else:
            status = 400
        raise HTTPException(status_code=status, detail=message)
    return data


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# --- search ---------------------------------------------------------------

@app.get("/api/search")
def api_search(
    keyword: str = Query(min_length=1, max_length=200),
    max_price_jpy: int | None = Query(default=None, gt=0),
    shops: str | None = None,  # comma-separated shop names
    sort: str = "recommended",
    listing_type: Literal["all", "buy_now", "auction"] = "all",
    junk_filter: Literal["hide", "all", "only"] = "all",
    only_in_stock: bool = True,
    min_discount_pct: int = Query(default=0, ge=0, le=100),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict:
    shop_list = None
    if shops:
        shop_list = [s.strip() for s in shops.split(",") if s.strip()]
        bad = [s for s in shop_list if s not in VALID_SHOPS]
        if bad:
            raise HTTPException(
                status_code=400,
                detail=f"invalid shop(s) {bad}; valid: {', '.join(sorted(VALID_SHOPS))}",
            )
    try:
        data = _unpack(
            mcp_tools.doorzo_search(
                keyword=keyword,
                max_price_jpy=max_price_jpy,
                shops=shop_list,
                sort=sort,
                only_in_stock=only_in_stock,
                min_discount_pct=min_discount_pct,
                limit=200 if listing_type != "all" or junk_filter != "all" else limit,
            )
        )
        if listing_type == "auction":
            data["items"] = [item for item in data["items"] if item.get("auction")]
        elif listing_type == "buy_now":
            data["items"] = [
                item for item in data["items"]
                if not item.get("auction") or item["auction"].get("buy_now_jpy", 0) > 0
            ]
        if junk_filter == "hide":
            data["items"] = [item for item in data["items"] if not item.get("junk")]
        elif junk_filter == "only":
            data["items"] = [item for item in data["items"] if item.get("junk")]
        data["items"] = data["items"][:limit]
        return data
    except DoorzoError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/hot")
def api_hot() -> dict:
    try:
        return _unpack(mcp_tools.doorzo_hot_searches())
    except DoorzoError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/rate")
def api_rate(currency: str = "AUD") -> dict:
    currency = currency.strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise HTTPException(status_code=422, detail="currency must be a 3-letter code")
    try:
        return _unpack(mcp_tools.doorzo_exchange_rate(currency=currency))
    except DoorzoError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# --- monitors -------------------------------------------------------------

class MonitorIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    keyword: str = Field(min_length=1, max_length=200)
    max_price_jpy: int = Field(gt=0)
    shops: list[str] | None = None
    min_discount_pct: int = Field(default=0, ge=0, le=100)
    notify_enabled: bool = True


@app.get("/api/monitors")
def api_monitors() -> dict:
    return {"monitors": store.load_monitors()}


@app.post("/api/monitors")
def api_monitor_add(body: MonitorIn) -> dict:
    body.name, body.keyword = body.name.strip(), body.keyword.strip()
    if not body.name or not body.keyword:
        raise HTTPException(status_code=422, detail="name and keyword cannot be blank")
    bad = [s for s in (body.shops or []) if s not in VALID_SHOPS]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"invalid shop(s) {bad}; valid: {', '.join(sorted(VALID_SHOPS))}",
        )
    try:
        return _unpack(
            mcp_tools.doorzo_monitor_add(
                name=body.name,
                keyword=body.keyword,
                max_price_jpy=body.max_price_jpy,
                shops=body.shops,
                min_discount_pct=body.min_discount_pct,
                notify_enabled=body.notify_enabled,
            )
        )
    except DoorzoError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.delete("/api/monitors/{monitor_id}")
def api_monitor_remove(monitor_id: str) -> dict:
    try:
        return _unpack(mcp_tools.doorzo_monitor_remove(monitor_id))
    except DoorzoError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


class CheckIn(BaseModel):
    monitor_id: str | None = None


@app.post("/api/check")
async def api_check(body: CheckIn) -> dict:
    """One-shot monitor check (the MCP agent tool additionally supports a
    watch loop; the web API intentionally runs a single pass)."""
    try:
        return _unpack(
            await mcp_tools.doorzo_check_monitors(monitor_id=body.monitor_id, watch_minutes=0)
        )
    except DoorzoError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/alerts")
def api_alerts(limit: int = 200) -> dict:
    limit = min(max(limit, 1), 1000)
    alerts: list[dict] = []
    path = store.ALERTS_PATH
    if path.exists():
        try:
            with path.open() as file:
                lines = deque(file, maxlen=limit)
        except OSError as exc:
            raise HTTPException(status_code=500, detail="could not read alerts") from exc
        for line in reversed(lines):
            try:
                alerts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {"alerts": alerts}


def main() -> None:
    import os
    import uvicorn

    host = os.environ.get("DOORZO_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("DOORZO_WEB_PORT", "8756"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
