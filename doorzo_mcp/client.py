"""Doorzo sig.doorzo.com JSON API client.

The site's SPA loads everything from this endpoint. It accepts plain
server-side requests: a User-Agent header and a persistent hex deviceId
are the entire auth story (verified live; no cookies, no browser).
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

BASE = "https://sig.doorzo.com/"
DEVICE_ID_PATH = Path(os.environ.get("DOORZO_STATE_DIR", Path.home() / ".doorzo-mcp")) / "device_id"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class DoorzoError(RuntimeError):
    """Doorzo API returned a non-200 code or a transport failure persisted."""


def _device_id() -> str:
    DEVICE_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DEVICE_ID_PATH.exists():
        return DEVICE_ID_PATH.read_text().strip()
    dev_id = "pc_" + secrets.token_hex(16)
    try:
        fd = os.open(DEVICE_ID_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return DEVICE_ID_PATH.read_text().strip()
    with os.fdopen(fd, "w") as file:
        file.write(dev_id)
    return dev_id


class DoorzoClient:
    def __init__(self) -> None:
        self.device_id = _device_id()

    def _url(self, service: str, **params: Any) -> str:
        q = {
            "n": service,
            "from": "INTERNATIONAL",
            "isNew": "15",
            "language": "en",
            "deviceId": self.device_id,
        }
        q.update({k: str(v) for k, v in params.items() if v is not None and v != ""})
        return BASE + "?" + urlencode(q)

    def _get(self, service: str, **params: Any) -> dict:
        url = self._url(service, **params)
        for attempt in range(2):
            try:
                resp = httpx.get(
                    url, headers={"User-Agent": UA}, timeout=30, follow_redirects=True
                )
                resp.raise_for_status()
                body = resp.json()
                if body.get("code") != 200:
                    raise DoorzoError(f"doorzo {service} failed: {body}")
                return body
            except (httpx.TransportError, json.JSONDecodeError,
                    httpx.HTTPStatusError, DoorzoError) as e:
                if attempt == 0:
                    time.sleep(2)
                    continue
                raise DoorzoError(f"{service}: {e}") from e
        raise DoorzoError(f"{service}: request failed")

    def search(
        self,
        keyword: str,
        only_in_stock: bool = True,
        order_by: str | None = None,
        max_pages: int = 3,
    ) -> list[dict]:
        """Full search result pool (cursor-paginated; ~180 items per page)."""
        max_pages = min(max(int(max_pages), 1), 10)
        items: list[dict] = []
        token: str | None = None
        for _ in range(max_pages):
            body = self._get(
                "Sig.Front.SubSite.AppGlobal.MixSearch",
                keyword=keyword,
                onlyInStock=1 if only_in_stock else None,
                orderBy=order_by or None,
                nextPageToken=token or None,
            )
            data = body.get("data") or {}
            items.extend(data.get("items") or [])
            token = data.get("nextPageToken")
            if not token or len(items) >= 500:
                break
        return items

    def hot_searches(self) -> list[dict]:
        data = self._get("Sig.Front.SubSite.App.GetHotSearchV1", t=6, refresh=0)
        return data.get("data") or []

    def exchange_rate(self, currency: str = "AUD") -> dict:
        data = self._get("Sig.Front.Front.GetCurrencyExchangeRate", currency=currency)
        return data.get("data") or {}
