"""JSON persistence for monitors, seen items, and alerts under ~/.doorzo-mcp."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

BASE_DIR = Path(os.environ.get("DOORZO_STATE_DIR", Path.home() / ".doorzo-mcp"))
MONITORS_PATH = BASE_DIR / "monitors.json"
SEEN_PATH = BASE_DIR / "seen.json"
ALERTS_PATH = BASE_DIR / "alerts.jsonl"

MAX_SEEN_PER_MONITOR = 2000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


# --- monitors ---------------------------------------------------------------

def load_monitors() -> list[dict]:
    return _read_json(MONITORS_PATH, {"monitors": []}).get("monitors", [])


def save_monitors(monitors: list[dict]) -> None:
    _atomic_write(MONITORS_PATH, json.dumps({"monitors": monitors}, ensure_ascii=False, indent=2))


def add_monitor(
    name: str,
    keyword: str,
    max_price_jpy: int,
    shops: list[str] | None = None,
    min_discount_pct: int = 0,
    notify: bool = True,
) -> dict:
    monitors = load_monitors()
    shops = sorted(set(shops)) if shops else None
    signature = (name.casefold(), keyword.casefold(), int(max_price_jpy), shops,
                 int(min_discount_pct), bool(notify))
    for m in monitors:
        current = (
            str(m.get("name", "")).casefold(),
            str(m.get("keyword", "")).casefold(),
            int(m.get("max_price_jpy", 0)),
            sorted(set(m.get("shops") or [])) or None,
            int(m.get("min_discount_pct", 0)),
            bool(m.get("notify", True)),
        )
        if current == signature:
            raise ValueError(f"monitor already exists: '{name}' / '{keyword}' / ¥{max_price_jpy}")
    mon = {
        "id": str(uuid4()),
        "name": name,
        "keyword": keyword,
        "max_price_jpy": int(max_price_jpy),
        "shops": shops,
        "min_discount_pct": int(min_discount_pct),
        "notify": bool(notify),
        "created_at": _now(),
        "last_checked_at": None,
        "last_new_count": 0,
    }
    monitors.append(mon)
    save_monitors(monitors)
    return mon


def _get_monitor(monitors: list[dict], monitor_id: str) -> dict:
    for m in monitors:
        if m["id"] == monitor_id:
            return m
    raise KeyError(f"monitor not found: {monitor_id}")


def remove_monitor(monitor_id: str) -> dict:
    monitors = load_monitors()
    mon = _get_monitor(monitors, monitor_id)
    monitors.remove(mon)
    save_monitors(monitors)
    # Drop seen state for the removed monitor.
    seen = load_seen()
    if monitor_id in seen:
        del seen[monitor_id]
        save_seen(seen)
    return mon


def update_monitor(monitor_id: str, **fields: Any) -> dict:
    monitors = load_monitors()
    mon = _get_monitor(monitors, monitor_id)
    mon.update(fields)
    save_monitors(monitors)
    return mon


# --- seen items -------------------------------------------------------------

def load_seen() -> dict[str, dict[str, bool]]:
    return _read_json(SEEN_PATH, {})


def save_seen(seen: dict[str, dict[str, bool]]) -> None:
    _atomic_write(SEEN_PATH, json.dumps(seen, ensure_ascii=False))


def get_seen(monitor_id: str) -> dict[str, bool]:
    return load_seen().get(monitor_id, {})


def set_seen(monitor_id: str, ids: dict[str, bool]) -> None:
    seen = load_seen()
    if len(ids) > MAX_SEEN_PER_MONITOR:
        # dict preserves insertion order: drop oldest keys.
        ids = dict(list(ids.items())[-MAX_SEEN_PER_MONITOR:])
    seen[monitor_id] = ids
    save_seen(seen)


# --- alerts -----------------------------------------------------------------

def append_alerts(monitor_id: str, monitor_name: str, items: list[dict]) -> None:
    if not items:
        return
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    for it in items:
        lines.append(
            json.dumps(
                {
                    "ts": _now(),
                    "monitor_id": monitor_id,
                    "monitor_name": monitor_name,
                    "item_id": it["id"],
                    "name": it["name"],
                    "price_jpy": it["price_jpy"],
                    "shop": it["shop"],
                    "url": it.get("doorzo_url") or it["original_url"],
                },
                ensure_ascii=False,
            )
        )
    fd = os.open(ALERTS_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
        f.flush()
        os.fsync(f.fileno())
