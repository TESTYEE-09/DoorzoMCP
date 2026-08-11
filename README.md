# Doorzo Deal Monitor

A tool that finds **good deals on Japanese shopping sites** and alerts you when something worth buying shows up.

It searches **doorzo.com** — a proxy-shopping service that combines 9 Japanese marketplaces: **Mercari, Rakuma, PayPay Flea, PayPay Mall, Rakuten, Yahoo Auctions, Amazon Japan, Lashinbang, and SNKRDUNK**.

> No AI needed to use it. No browser automation or scraping either — it talks to doorzo's own API directly.

---

## What it does

- **Search** for a keyword (e.g. `マリオパーティ` or `nintendo switch`) across all 9 marketplaces at once.
- **Filter by price** — set a ceiling in Australian dollars in the web UI.
- **Spot discounts** — shows the list price vs. the sale price and the % off.
- **Monitor keywords** — tell it "alert me when a Mario Party game appears for under A$30". It checks in the background and notifies you (macOS notification + a log file).
- **Trending searches** — see what people are hunting for right now.
- **Live AUD prices** — the web UI converts Doorzo's JPY prices and price ceilings using Doorzo's current AUD rate.
- **Open via Doorzo** — product and alert links stay inside Doorzo instead of sending you to the underlying marketplace.
- **Choose how to buy** — narrow results to Buy It Now listings or auctions.
- **Avoid junk listings** — hide likely junk, broken, untested, or parts-only items by default; show or isolate them when wanted. Flagged results carry a clear `JUNK / PARTS` label and reason.

## Two ways to use it

| | Web UI | AI (MCP) |
|---|---|---|
| Who uses it | You, in a browser | An AI assistant like Claude Code |
| How it looks | A website at `http://127.0.0.1:8756` | Tools the AI can call |
| Best for | Browsing, adding monitors, checking alerts | Asking the AI to find/watch deals for you |

Both share the same data and the same monitors.

---

## Getting started (3 steps)

**1. Install.** You need Python 3.11+ and [uv](https://docs.astral.sh/uv/) (a Python tool installer).

```bash
git clone https://github.com/TESTYEE-09/DoorzoMCP.git
cd DoorzoMCP
uv sync
```

**2. Start the web UI.**

```bash
uv run doorzo-web
```

**3. Open your browser** at **http://127.0.0.1:8756** — done.

Search something, or add a monitor: give it a name, a keyword, and a max price. Click **Check all monitors** to check for new matches right now. New matches fire a macOS notification and appear in the Alerts list.

The web UI displays and accepts prices in **AUD**. Internally, monitor ceilings
are converted to JPY so the web UI and MCP server can continue sharing the same
backward-compatible state. Product links open through Doorzo, where you can
review or purchase the listing using Doorzo's proxy-shopping flow.

Your monitors and alerts are stored in `~/.doorzo-mcp/` and survive restarts.
Set `DOORZO_STATE_DIR` before starting either service only if you want to keep
that state somewhere else.

---

## Letting an AI use it (optional)

If you use Claude Code (or another MCP-compatible assistant), you can give it access to the same search and monitors:

```bash
claude mcp add doorzo-deals -- uv run --directory /path/to/DoorzoMCP doorzo-mcp
```

The AI then has these tools: `doorzo_search`, `doorzo_hot_searches`, `doorzo_exchange_rate`, `doorzo_monitor_add`, `doorzo_monitor_remove`, `doorzo_monitor_list`, and `doorzo_check_monitors`. Example: *"add a monitor for a Mario Party game under ¥3,000 and check it now"* — it will do that and tell you what it found.

The MCP tool parameters and returned price fields remain in **JPY**. This keeps
the public tool contract stable for existing agents; AUD conversion is a web UI
feature.

---

## Project layout

```
doorzo_mcp/
  client.py   # talks to doorzo.com's API
  deals.py    # decides what counts as a deal
  store.py    # saves your monitors and alerts (~/.doorzo-mcp)
  notify.py   # macOS notifications
  server.py   # the AI (MCP) tools
  web.py      # the website and its API
  static/     # the web page itself (single file, no build step)
```

---

## Things to know

- **Prices are before proxy fees.** You still pay doorzo's service fee and international shipping. The tool finds cheap *listings*.
- **AUD amounts are estimates.** Doorzo's live rate is used, and the final amount may differ when Doorzo processes the purchase.
- **Condition text** comes from the sites in Chinese; this tool translates it to English (unknown labels pass through as-is).
- **The API could change.** doorzo.com is an unaffiliated third party; this project uses its internal API with no authentication, so it may break if they change things or add bot protection.
- **MIT licensed.** Use at your own risk. Not affiliated with or endorsed by doorzo.com.
