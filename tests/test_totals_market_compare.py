"""Offline tests for totals_market_compare."""
import unittest
from datetime import datetime, timezone
from totals_market_compare import collect, match, parse_finals, pick_record, summarize, median


def quote(line, t):
    return dict(book="b", line=line, over=1.9, under=1.9, updated=t)


def snap(updated, line, t, proj=225.0, start="2026-11-26T01:10:00Z"):
    game = dict(home="Memphis Grizzlies", away="Los Angeles Clippers", start=start,
                projection=dict(total=proj), game_quotes=[quote(line, t)] * 3)
    return dict(updated=updated, leagues=[dict(league="NBA", games=[game])])


class MarketTests(unittest.TestCase):
    def test_median(self):
        self.assertEqual(median([3, 1, 2]), 2)
        self.assertEqual(median([1, 2, 3, 4]), 2.5)

    def test_collect_takes_latest_pregame_and_skips_postgame(self):
        snaps = [snap("a", 227.5, "2026-11-25T10:00:00Z"), snap("b", 228.5, "2026-11-25T16:40:00Z"),
                 snap("c", 230.0, "2026-11-26T02:00:00Z")]
        rows = collect(snaps)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["line"], 228.5)
        self.assertAlmostEqual(rows[0]["lead_hours"], 8.5, places=1)

    def test_collect_needs_enough_books(self):
        s = snap("a", 227.5, "2026-11-25T10:00:00Z")
        s["leagues"][0]["games"][0]["game_quotes"] = s["leagues"][0]["games"][0]["game_quotes"][:2]
        self.assertEqual(collect([s]), [])

    def test_missing_projection_kept_without_model(self):
        s = snap("a", 227.5, "2026-11-25T10:00:00Z")
        s["leagues"][0]["games"][0]["projection"] = None
        self.assertIsNone(collect([s])[0]["model"])

    def test_finals_and_matching_with_nickname(self):
        data = dict(events=[dict(date="2026-11-26T01:10Z", competitions=[dict(
            status=dict(type=dict(completed=True)),
            competitors=[dict(homeAway="home", score="110", team=dict(name="Grizzlies")),
                         dict(homeAway="away", score="118", team=dict(name="Clippers"))])]),
            dict(date="2026-11-26T01:10Z", competitions=[dict(status=dict(type=dict(completed=False)), competitors=[])])])
        finals = parse_finals(data)
        self.assertEqual(len(finals), 1)
        game = dict(home="Memphis Grizzlies", away="Los Angeles Clippers", start="2026-11-26T01:10:00Z")
        self.assertEqual(match(game, finals), 228.0)
        self.assertIsNone(match(dict(game, away="Boston Celtics"), finals))
        self.assertIsNone(match(dict(game, start="2026-11-28T01:10:00Z"), finals))

    def test_pick_record(self):
        rows = [dict(model=232, line=228.5, actual=235), dict(model=232, line=228.5, actual=220),
                dict(model=225, line=228.5, actual=228.5), dict(model=228.5, line=228.5, actual=200),
                dict(model=229, line=228.5, actual=230)]
        self.assertEqual(pick_record(rows, 0), dict(wins=2, losses=1, pushes=1))
        self.assertEqual(pick_record(rows, 3), dict(wins=1, losses=1, pushes=1))

    def test_summary_math(self):
        rows = [dict(model=230, line=225, actual=226), dict(model=210, line=220, actual=221)]
        s = summarize(rows, 4)
        self.assertEqual(s["market"]["mae"], 1.0)
        self.assertEqual(s["model"]["mae"], (4 + 11) / 2)
        self.assertEqual(s["edge_vs_market"], round(((1 - 4) + (1 - 11)) / 2, 3))
        self.assertEqual(summarize([], 4), dict(n=0))
        self.assertNotIn("model", summarize([dict(model=None, line=1, actual=2)], 4))


if __name__ == "__main__":
    unittest.main()
