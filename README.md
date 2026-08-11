# DoorzoMCP — Doorzo Deal Monitor

Find good-priced items on [doorzo.com](https://www.doorzo.com) (Japanese proxy-shopping aggregator) across **Mercari, Rakuma, PayPay Flea/Mall, Rakuten, Yahoo Auctions, Amazon JP, Lashinbang, and SNKRDUNK** — with deal alerts.

Two surfaces in one project:

1. **MCP server** (`doorzo-deals`) — exposes search / hot searches / exchange rate / persistent deal monitors to Claude Code (or any MCP client).
2. **Web UI** (`doorzo-web`) — the same engine behind a zero-build single-file web app: search, trending keywords, monitors, and an alert log.

The doorzo site is a Nuxt SPA; this project talks directly to its internal JSON API (`sig.doorzo.com`) — plain HTTP, no browser, no scraping.

## Features

- **Search across 9 shops** with price ceiling, minimum discount %, in-stock filter, and price sort.
- **Deal model**: threshold always applies; when a list (origin) price exists, a real discount below it is required; Yahoo Auctions use the buy-now price (else current bid); "price on request" listings are excluded.
- **Monitors**: watch a keyword, get macOS notifications + an `alerts.jsonl` log when new items match. Re-checks never re-alert the same item (seen-diff).
- **Hot searches** from doorzo, and live **JPY → any-currency** exchange rate.

## Quickstart

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run doorzo-web        # web UI at http://127.0.0.1:8756
uv run doorzo-mcp        # MCP server over stdio (for Claude Code / MCP clients)
```

State lives in `~/.doorzo-mcp/` (`monitors.json`, `seen.json`, `alerts.jsonl`, `device_id`) — shared by both surfaces.

### Register the MCP server with Claude Code

```bash
claude mcp add doorzo-deals -- uv run --directory /path/to/DoorzoMCP doorzo-mcp
```

Tools: `doorzo_search`, `doorzo_hot_searches`, `doorzo_exchange_rate`, `doorzo_monitor_add`, `doorzo_monitor_remove`, `doorzo_monitor_list`, `doorzo_check_monitors` (one-shot or `watch_minutes` loop).

### Web UI

```bash
DOORZO_WEB_HOST=0.0.0.0 DOORZO_WEB_PORT=8756 uv run doorzo-web
```

| Endpoint | Description |
| --- | --- |
| `GET /` | Web UI |
| `GET /api/search?keyword=&max_price_jpy=&shops=&sort=&min_discount_pct=&limit=` | Search (shops = comma-separated) |
| `GET /api/hot` | Trending keywords |
| `GET /api/rate?currency=AUD` | JPY → currency |
| `GET /api/monitors` · `POST /api/monitors` · `DELETE /api/monitors/{id}` | Monitor CRUD |
| `POST /api/check` | Run one monitor check (`{"monitor_id": "…"}` or all) |
| `GET /api/alerts` | Recent alert log |

## Project layout

```
doorzo_mcp/
  client.py   # sig.doorzo.com HTTP client (deviceId + UA; cursor pagination)
  deals.py    # shop map, item normalization, deal scoring
  store.py    # monitors / seen / alerts persistence (~/.doorzo-mcp)
  notify.py   # macOS notifications
  server.py   # MCP tools
  web.py      # FastAPI + JSON API
  static/     # single-file web UI (no build step)
```

## Notes & limitations

- Prices are marketplace prices **before** doorzo's proxy fee and international shipping — the deal signal is the listing price.
- Condition text passes through untranslated (the API only localizes via a paid endpoint).
- The API is an internal endpoint of an unaffiliated site; it may change or add bot protection at any time. This project sends plain requests with a stable deviceId and no auth.
- MIT licensed — use at your own risk; this is not affiliated with or endorsed by doorzo.com.

---

made entirely with deepseek v4 flash 0731
