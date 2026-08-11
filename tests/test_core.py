import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from doorzo_mcp import store
from doorzo_mcp.client import DoorzoClient, DoorzoError
from doorzo_mcp.deals import doorzo_url, is_deal, normalize
from doorzo_mcp.server import (
    _check_one, doorzo_exchange_rate, doorzo_hot_searches, doorzo_monitor_add,
)
from doorzo_mcp.web import app


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.paths = patch.multiple(
            store,
            BASE_DIR=base,
            MONITORS_PATH=base / "monitors.json",
            SEEN_PATH=base / "seen.json",
            ALERTS_PATH=base / "alerts.jsonl",
        )
        self.paths.start()

    def tearDown(self):
        self.paths.stop()
        self.temp.cleanup()

    def test_duplicate_monitor_normalizes_shop_order_and_case(self):
        store.add_monitor("Games", "Mario", 3000, ["rakuma", "mercari"])
        with self.assertRaises(ValueError):
            store.add_monitor("games", "mario", 3000, ["mercari", "rakuma"])

    def test_seen_pruning_keeps_exact_limit_and_newest_ids(self):
        ids = {str(i): True for i in range(store.MAX_SEEN_PER_MONITOR + 1)}
        store.set_seen("monitor", ids)
        saved = store.get_seen("monitor")
        self.assertEqual(len(saved), store.MAX_SEEN_PER_MONITOR)
        self.assertNotIn("0", saved)
        self.assertIn(str(store.MAX_SEEN_PER_MONITOR), saved)


class DealTest(unittest.TestCase):
    def test_all_sentinel_prices_are_unpriced(self):
        item = normalize({"Type": 1, "JPYPrice": 9_999_999,
                          "OriginPrice": 542_559_090})
        self.assertEqual((item["price_jpy"], item["origin_jpy"]), (0, 0))
        self.assertEqual(is_deal(item, 5000), (False, "no price"))

    def test_minimum_discount_requires_origin(self):
        item = normalize({"Type": 1, "JPYPrice": 1000})
        self.assertFalse(is_deal(item, 2000, 10)[0])

    def test_product_link_routes_through_doorzo(self):
        raw_url = "68747470733a2f2f6578616d706c652e636f6d"
        item = normalize({"Type": 1, "Asin": "m123", "Url": raw_url})
        self.assertEqual(
            item["doorzo_url"],
            f"https://www.doorzo.com/en/mall/mercari/detail/{raw_url}",
        )
        self.assertEqual(
            doorzo_url("snkrdunk", "apparels/91385"),
            "https://www.doorzo.com/en/mall/snkrdunk/detail/apparels%2F91385",
        )

    def test_junk_listing_is_labeled(self):
        item = normalize({"Type": 1, "Name": "ゲーム機 ジャンク 部品取り"})
        self.assertTrue(item["junk"])
        self.assertEqual(item["junk_reason"], "Marked junk")


class ClientTest(unittest.TestCase):
    @patch("doorzo_mcp.client.time.sleep")
    @patch("doorzo_mcp.client.httpx.get")
    def test_retries_api_body_error_once(self, get, _sleep):
        first = unittest.mock.Mock(status_code=200)
        first.raise_for_status.return_value = None
        first.json.return_value = {"code": 500, "message": "busy"}
        second = unittest.mock.Mock(status_code=200)
        second.raise_for_status.return_value = None
        second.json.return_value = {"code": 200, "data": {}}
        get.side_effect = [first, second]
        client = object.__new__(DoorzoClient)
        client.device_id = "test"
        self.assertEqual(client._get("service")["code"], 200)
        self.assertEqual(get.call_count, 2)


class WebTest(unittest.TestCase):
    def test_validation_and_error_statuses(self):
        client = TestClient(app)
        self.assertEqual(client.get("/api/search?keyword=x&limit=0").status_code, 422)
        self.assertEqual(client.get("/api/rate?currency=dollars").status_code, 422)
        with patch("doorzo_mcp.web.mcp_tools.doorzo_monitor_remove",
                   return_value=json.dumps({"error": "monitor not found: x"})):
            self.assertEqual(client.delete("/api/monitors/x").status_code, 404)

    def test_listing_and_junk_filters(self):
        items = [
            {"id": "fixed", "auction": None, "junk": False},
            {"id": "junk", "auction": None, "junk": True},
            {"id": "bid", "auction": {"bid_jpy": 100, "buy_now_jpy": 0}, "junk": False},
            {"id": "both", "auction": {"bid_jpy": 100, "buy_now_jpy": 200}, "junk": False},
        ]
        payload = json.dumps({"query": "x", "currency": "JPY", "items": items})
        client = TestClient(app)
        with patch("doorzo_mcp.web.mcp_tools.doorzo_search", return_value=payload):
            auctions = client.get("/api/search?keyword=x&listing_type=auction").json()
            buy_now = client.get("/api/search?keyword=x&listing_type=buy_now").json()
            junk = client.get("/api/search?keyword=x&junk_filter=only").json()
            clean = client.get("/api/search?keyword=x&junk_filter=hide").json()
        self.assertEqual([item["id"] for item in auctions["items"]], ["bid", "both"])
        self.assertEqual([item["id"] for item in buy_now["items"]], ["fixed", "junk", "both"])
        self.assertEqual([item["id"] for item in junk["items"]], ["junk"])
        self.assertNotIn("junk", [item["id"] for item in clean["items"]])


class MonitorCheckTest(unittest.TestCase):
    def test_records_every_new_id_but_caps_notifications(self):
        raw = [{"Type": 1, "Asin": str(i), "Name": f"item {i}",
                "JPYPrice": 100, "OriginPrice": 200} for i in range(8)]
        client = unittest.mock.Mock()
        client.search.return_value = raw
        mon = {"id": "m", "name": "monitor", "keyword": "x",
               "max_price_jpy": 500, "notify": True}
        seen = {}
        with patch("doorzo_mcp.server.store.get_seen", return_value=seen), \
             patch("doorzo_mcp.server.store.set_seen") as set_seen, \
             patch("doorzo_mcp.server.store.append_alerts"), \
             patch("doorzo_mcp.server.store.update_monitor"), \
             patch("doorzo_mcp.server.notify") as notify:
            result = _check_one(client, mon, {"exchange": 0})
        self.assertEqual(len(result["new"]), 8)
        self.assertEqual(len(set_seen.call_args.args[1]), 8)
        self.assertEqual(notify.call_count, 5)
        self.assertIn("https://www.doorzo.com/", notify.call_args.args[1])

    def test_tool_entry_points_validate_without_name_errors(self):
        with patch("doorzo_mcp.server.DoorzoClient") as client:
            client.return_value.hot_searches.return_value = []
            client.return_value.exchange_rate.return_value = {"currency": "AUD"}
            self.assertEqual(json.loads(doorzo_hot_searches()), {"items": []})
            self.assertEqual(json.loads(doorzo_exchange_rate("aud"))["currency"], "AUD")
        self.assertIn("name and keyword are required",
                      json.loads(doorzo_monitor_add(" ", "x", 1))["error"])


if __name__ == "__main__":
    unittest.main()
