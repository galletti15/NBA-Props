"""Offline tests for totals_backtest_current_season."""
import unittest
from datetime import datetime, timezone
from totals_backtest_current_season import restrict, season_start


def histories():
    rows = [dict(id="g%d" % i, date="2026-11-%02dT00:00:00Z" % (i + 1)) for i in range(10)]
    return {"A": rows, "B": list(rows)}


class SeasonTests(unittest.TestCase):
    def test_season_start(self):
        utc = timezone.utc
        self.assertEqual(season_start(datetime(2026, 11, 26, tzinfo=utc)), datetime(2026, 8, 1, tzinfo=utc))
        self.assertEqual(season_start(datetime(2027, 2, 1, tzinfo=utc)), datetime(2026, 8, 1, tzinfo=utc))
        self.assertEqual(season_start(datetime(2026, 8, 1, tzinfo=utc)), datetime(2026, 8, 1, tzinfo=utc))
        self.assertEqual(season_start(datetime(2026, 7, 31, tzinfo=utc)), datetime(2025, 8, 1, tzinfo=utc))

    def test_restrict_drops_old_games_without_mutation(self):
        data = histories()
        before = {k: list(v) for k, v in data.items()}
        kept = restrict(data, datetime(2026, 11, 6, tzinfo=timezone.utc))
        self.assertEqual([r["id"] for r in kept["A"]], ["g5", "g6", "g7", "g8", "g9"])
        self.assertEqual(data, before)


if __name__ == "__main__":
    unittest.main()
