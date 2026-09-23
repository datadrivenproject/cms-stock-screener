import unittest
from datetime import date

from prune_stock_daily import prune, range_to_delete


class Response:
    def __init__(self, rows=None, error=None):
        self.rows, self.error = rows or [], error

    def raise_for_status(self):
        if self.error:
            raise RuntimeError(self.error)

    def json(self):
        return self.rows


class FakeSession:
    def __init__(self, oldest="2025-09-20", latest="2026-09-22", delete_error=None):
        self.oldest, self.latest, self.delete_error = oldest, latest, delete_error
        self.deletions = []

    def get(self, url, headers, params, timeout):
        day = self.oldest if params["order"].endswith("asc") else self.latest
        return Response([{"trade_date": day}])

    def delete(self, url, headers, params, timeout):
        self.deletions.append((url, params))
        if not self.delete_error:
            self.oldest = params["and"].split("trade_date.lt.")[1].split(")")[0]
        return Response(error=self.delete_error)


class RetentionTests(unittest.TestCase):
    def test_strict_cutoff_excludes_exactly_one_year_old(self):
        windows = list(range_to_delete(date(2025, 9, 20), date(2026, 9, 22)))
        self.assertEqual(windows, [(date(2025, 9, 20), date(2025, 9, 22))])
        fake = FakeSession()
        prune(fake, "https://example.supabase.co", "test-key", date(2026, 9, 22))
        self.assertEqual(fake.deletions, [(
            "https://example.supabase.co/rest/v1/stock_daily",
            {"trade_date": "gte.2025-09-20", "and": "(trade_date.lt.2025-09-22)"},
        )])

    def test_stale_data_never_triggers_deletion(self):
        fake = FakeSession(latest="2026-09-01")
        with self.assertRaises(RuntimeError):
            prune(fake, "https://example.supabase.co", "test-key", date(2026, 9, 22))
        self.assertEqual(fake.deletions, [])

    def test_failed_delete_stops_next_window(self):
        fake = FakeSession(oldest="2025-08-01", delete_error="permission denied")
        with self.assertRaises(RuntimeError):
            prune(fake, "https://example.supabase.co", "test-key", date(2026, 9, 22))
        self.assertEqual(len(fake.deletions), 1)


if __name__ == "__main__":
    unittest.main()
