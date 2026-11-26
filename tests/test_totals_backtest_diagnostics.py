"""Offline tests for totals_backtest_diagnostics."""
import unittest
from totals_backtest_diagnostics import analyze, by_prediction, holdout, linear_fit, by_month, format_report


def rows(n=60, bias=3.0):
    out = []
    for i in range(n):
        actual = 200 + (i * 7) % 40
        pred = actual + bias + ((i % 5) - 2)
        out.append(dict(id=str(i), date="2026-%02d-%02dT00:00:00Z" % (11 if i < 30 else 12, i % 28 + 1),
                        actual=actual, baseline=pred, efficiency=pred + 0.5))
    return out


class DiagnosticTests(unittest.TestCase):
    def test_terciles_cover_all_rows(self):
        parts = by_prediction(rows())
        self.assertEqual(sum(p["n"] for p in parts), 60)
        self.assertEqual(len(parts), 3)
        self.assertLess(parts[0]["mean_pred"], parts[2]["mean_pred"])

    def test_months_split(self):
        self.assertEqual([m["label"] for m in by_month(rows())], ["2026-11", "2026-12"])

    def test_linear_fit_exact_and_degenerate(self):
        a, b = linear_fit([1, 2, 3], [3, 5, 7])
        self.assertAlmostEqual(b, 2.0)
        self.assertAlmostEqual(a, 1.0)
        self.assertIsNone(linear_fit([1, 1, 1], [1, 2, 3]))

    def test_offset_removes_constant_bias_on_holdout(self):
        h = holdout(rows(bias=3.0), "baseline")
        self.assertLess(h["offset_mae"], h["raw_mae"])
        self.assertAlmostEqual(h["offset"], -3.0, delta=0.6)

    def test_holdout_too_small(self):
        self.assertIsNone(holdout(rows(15), "baseline"))

    def test_analyze_and_report(self):
        result = analyze(dict(league="NBA", games=rows()))
        self.assertEqual(result["n"], 60)
        self.assertTrue(any("holdout" in line for line in format_report([result])))
        self.assertIn("note", analyze(dict(league="NFL", games=rows(5))))


if __name__ == "__main__":
    unittest.main()
