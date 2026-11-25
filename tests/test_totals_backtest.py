"""Offline tests for totals_backtest."""
import copy
import unittest
from totals_backtest import evaluate, summarize, baseline_records


def histories(n=10, league="NBA"):
    a, b = [], []
    for i in range(n):
        s, t, opp = 100 + i + (i % 3), 98 + (i % 4), 95 + (i % 4)
        base = dict(id="g%d" % i, date="2026-11-%02dT00:00:00Z" % (i + 1), opportunity_scope="final")
        a.append(dict(base, scored=s, allowed=t, opportunities=opp, opponent_opportunities=opp))
        b.append(dict(base, scored=t, allowed=s, opportunities=opp, opponent_opportunities=opp))
    return {"A": a, "B": b}


class BacktestTests(unittest.TestCase):
    def test_counts_and_skips(self):
        rows, skipped = evaluate("NBA", histories())
        self.assertEqual(len(rows), 5)
        self.assertEqual(skipped, {"insufficient_history": 5})
        self.assertTrue(all(r["actual"] == r["actual"] and r["baseline"] and r["efficiency"] for r in rows))

    def test_no_future_leakage(self):
        first, _ = evaluate("NBA", histories())
        changed = histories()
        for team in changed.values():
            team[9]["scored"], team[9]["allowed"] = 150, 150
        second, _ = evaluate("NBA", changed)
        by_id = lambda rows: {r["id"]: r for r in rows}
        a, b = by_id(first), by_id(second)
        for gid in ("g5", "g6", "g7", "g8", "g9"):
            self.assertEqual((a[gid]["baseline"], a[gid]["efficiency"]), (b[gid]["baseline"], b[gid]["efficiency"]))
        self.assertNotEqual(a["g9"]["actual"], b["g9"]["actual"])

    def test_missing_opportunity_skips_efficiency(self):
        data = histories()
        data["A"][3].pop("opportunities")
        rows, skipped = evaluate("NBA", data)
        self.assertEqual(rows, [])
        self.assertEqual(skipped["efficiency_unavailable"], 5)

    def test_inconsistent_pair_skipped(self):
        data = histories()
        data["B"][7]["allowed"] += 1
        rows, skipped = evaluate("NBA", data)
        self.assertEqual(skipped["inconsistent_pair"], 1)
        self.assertEqual(len(rows), 4)

    def test_unpaired_game_ignored(self):
        data = histories()
        data.pop("B")
        rows, skipped = evaluate("NBA", data)
        self.assertEqual((rows, skipped), ([], {}))

    def test_baseline_records_strip_inputs_without_mutation(self):
        original = histories()["A"]
        before = copy.deepcopy(original)
        stripped = baseline_records(original)
        self.assertNotIn("opportunities", stripped[0])
        self.assertEqual(original, before)

    def test_summary_math(self):
        s = summarize([dict(actual=200, baseline=210, efficiency=205)])
        self.assertEqual((s["baseline"]["mae"], s["efficiency"]["mae"], s["mean_error_reduction"]), (10.0, 5.0, 5.0))
        self.assertEqual((s["efficiency_closer"], s["baseline_closer"], s["ties"]), (1, 0, 0))
        self.assertEqual(s["ci95"], [5.0, 5.0])

    def test_summary_mixed_and_empty(self):
        rows = [dict(actual=200, baseline=210, efficiency=205), dict(actual=200, baseline=202, efficiency=206)]
        s = summarize(rows)
        self.assertEqual((s["efficiency_closer"], s["baseline_closer"]), (1, 1))
        self.assertEqual(s["mean_error_reduction"], 0.5)
        self.assertEqual(summarize([]), {"n": 0})


if __name__ == "__main__":
    unittest.main()
