"""Offline tests for league game caps and windows in totals_pipeline."""
import time
import unittest
from datetime import datetime, timedelta
import totals_pipeline as tp


def events(n, step_hours):
    return [dict(id="e%d" % i, home_team="Home %d" % i, away_team="Away %d" % i,
                 commence_time=(tp.NOW + timedelta(hours=1 + i * step_hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 bookmakers=[]) for i in range(n)]


class CapTests(unittest.TestCase):
    def setUp(self):
        self.saved = (tp.odds, tp.team_index, tp.history, tp.START, tp.BUDGET)
        tp.BUDGET = 100
        tp.team_index = lambda route: {}

    def tearDown(self):
        tp.odds, tp.team_index, tp.history, tp.START, tp.BUDGET = self.saved

    def run_league(self, label, evs):
        tp.odds = lambda sport, path, **p: evs if path == "/odds" else {"bookmakers": []}
        return tp.build_league(label, tp.SPORTS[label])

    def test_nba_still_capped_at_eight(self):
        result = self.run_league("NBA", events(30, 5))
        self.assertEqual(len(result["games"]), 8)

    def test_ncaaf_includes_all_games_in_seven_days(self):
        result = self.run_league("NCAAF", events(40, 4))
        self.assertEqual(len(result["games"]), 40)
        self.assertEqual(result["available_games"], 40)

    def test_ncaab_includes_all_games_in_next_24_hours_only(self):
        result = self.run_league("NCAAB", events(40, 4))
        self.assertEqual(len(result["games"]), 6)
        self.assertEqual(result["available_games"], 6)
        self.assertTrue(all(datetime.fromisoformat(g["start"].replace("Z", "+00:00")) < tp.NOW + timedelta(days=1) for g in result["games"]))

    def test_time_budget_skips_history_but_keeps_games_and_lines(self):
        calls = []
        tp.history = lambda *a: calls.append(a) or []
        tp.team_index = lambda route: {tp.key("Home %d" % i): str(i) for i in range(5)} | {tp.key("Away %d" % i): str(100 + i) for i in range(5)}
        tp.START = time.monotonic() - tp.HISTORY_SECONDS - 5
        result = self.run_league("NCAAB", events(5, 1))
        self.assertEqual(len(result["games"]), 5)
        self.assertEqual(calls, [])
        self.assertTrue(all(g["model_status"].startswith("Skipped") for g in result["games"]))

    def test_history_runs_within_budget(self):
        calls = []
        tp.history = lambda route, tid, count: calls.append(tid) or []
        tp.team_index = lambda route: {tp.key("Home 0"): "1", tp.key("Away 0"): "2"}
        tp.START = time.monotonic()
        result = self.run_league("NCAAB", events(1, 1))
        self.assertEqual(sorted(calls), ["1", "2"])
        self.assertEqual(result["games"][0]["model_status"], "Insufficient completed-game history")


if __name__ == "__main__":
    unittest.main()
