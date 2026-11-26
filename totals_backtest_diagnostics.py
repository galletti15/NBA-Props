"""Diagnostics for data/totals-backtest.json. Read-only analysis; shadow only.

Splits errors by predicted-total tercile and by month, then checks on a
time-ordered holdout whether a bias offset or linear shrink fitted on the
earlier half helps the later half. Descriptive only; samples overlap.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

METHODS = ("baseline", "efficiency")


def when(row):
    return datetime.fromisoformat(row["date"].replace("Z", "+00:00"))


def mean(values):
    return sum(values) / len(values)


def stats(rows, key):
    errors = [r[key] - r["actual"] for r in rows]
    return dict(bias=round(mean(errors), 2), mae=round(mean([abs(e) for e in errors]), 2))


def bucket(rows, label):
    return dict(label=label, n=len(rows),
                mean_pred=round(mean([r["efficiency"] for r in rows]), 1),
                mean_actual=round(mean([r["actual"] for r in rows]), 1),
                baseline=stats(rows, "baseline"), efficiency=stats(rows, "efficiency"))


def by_prediction(rows, parts=3):
    ordered = sorted(rows, key=lambda r: r["efficiency"])
    size = len(ordered) // parts
    if size == 0:
        return []
    chunks = [ordered[i * size:(i + 1) * size] for i in range(parts - 1)] + [ordered[(parts - 1) * size:]]
    return [bucket(c, "pred tercile " + str(i + 1)) for i, c in enumerate(chunks)]


def by_month(rows):
    months = {}
    for r in rows:
        months.setdefault(when(r).strftime("%Y-%m"), []).append(r)
    return [bucket(v, k) for k, v in sorted(months.items())]


def linear_fit(xs, ys):
    mx, my = mean(xs), mean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
    return my - slope * mx, slope


def holdout(rows, key):
    ordered = sorted(rows, key=when)
    half = len(ordered) // 2
    train, test = ordered[:half], ordered[half:]
    if len(train) < 10 or len(test) < 10:
        return None
    raw = mean([abs(r[key] - r["actual"]) for r in test])
    offset = mean([r["actual"] - r[key] for r in train])
    shifted = mean([abs(r[key] + offset - r["actual"]) for r in test])
    out = dict(train=len(train), test=len(test), raw_mae=round(raw, 2),
               offset=round(offset, 2), offset_mae=round(shifted, 2))
    fit = linear_fit([r[key] for r in train], [r["actual"] for r in train])
    if fit:
        a, b = fit
        out.update(slope=round(b, 3), intercept=round(a, 1),
                   linear_mae=round(mean([abs(a + b * r[key] - r["actual"]) for r in test]), 2))
    return out


def analyze(league_result):
    rows = league_result.get("games", [])
    if len(rows) < 30:
        return dict(league=league_result.get("league"), n=len(rows), note="too few games")
    return dict(league=league_result["league"], n=len(rows),
                mean_actual=round(mean([r["actual"] for r in rows]), 1),
                by_prediction=by_prediction(rows), by_month=by_month(rows),
                holdout={k: holdout(rows, k) for k in METHODS})


def format_report(results):
    lines = []
    for r in results:
        lines.append("== " + str(r["league"]) + " n " + str(r["n"]))
        if "note" in r:
            lines.append(r["note"])
            continue
        lines.append("mean actual " + str(r["mean_actual"]))
        for b in r["by_prediction"] + r["by_month"]:
            lines.append(b["label"] + " n" + str(b["n"]) + " pred " + str(b["mean_pred"]) + " act " + str(b["mean_actual"])
                         + " | bias old " + str(b["baseline"]["bias"]) + " new " + str(b["efficiency"]["bias"])
                         + " | MAE old " + str(b["baseline"]["mae"]) + " new " + str(b["efficiency"]["mae"]))
        for k in METHODS:
            h = r["holdout"][k]
            if h is None:
                lines.append("holdout " + k + " too few")
                continue
            lines.append("holdout " + k + " test " + str(h["test"]) + " raw " + str(h["raw_mae"]) + " offset(" + str(h["offset"]) + ") " + str(h["offset_mae"])
                         + (" linear(slope " + str(h["slope"]) + ") " + str(h["linear_mae"]) if "slope" in h else ""))
    return lines


def main(path="data/totals-backtest.json"):
    data = json.loads(Path(path).read_text())
    results = [analyze(r) for r in data["leagues"] if "error" not in r]
    print("\n".join(format_report(results)))
    Path("data/totals-backtest-diagnostics.json").write_text(json.dumps(results, allow_nan=False))


if __name__ == "__main__":
    main(*sys.argv[1:])
