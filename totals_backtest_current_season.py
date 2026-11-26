"""Current-season shadow backtest. Read-only; no odds, no publishing.

Same method as totals_backtest, but every game dated before Aug 1 of the
current season year is dropped from both the tested games and each team's
history, so prior-season games cannot feed projections. Early-season games
with too little current-season history are skipped.
"""
import json
from datetime import datetime, timezone

from espn_totals_adapters import load_history
from totals_backtest import COUNTS, OUTPUT, ROUTES, evaluate, format_summary, make_get, summarize, team_ids
from totals_model_v2 import timestamp


def season_start(now):
    year = now.year if now.month >= 8 else now.year - 1
    return datetime(year, 8, 1, tzinfo=timezone.utc)


def restrict(histories, since):
    return {tid: [r for r in rows if timestamp(r["date"]) >= since] for tid, rows in histories.items()}


def run(league, get, now):
    route, cache, histories, failures = ROUTES[league], {}, {}, 0
    for tid in team_ids(get, route):
        try:
            histories[tid] = load_history(league, route, tid, COUNTS[league], now, get, cache)
        except Exception:
            failures += 1
    since = season_start(now)
    rows, skipped = evaluate(league, restrict(histories, since))
    return dict(league=league, season_start=since.isoformat(), teams_loaded=len(histories),
                team_failures=failures, tested=len(rows), skipped=skipped,
                summary=summarize(rows), games=rows)


def main():
    now = datetime.now(timezone.utc)
    get = make_get()
    output = dict(updated=now.isoformat(), backtest=True, current_season_only=True,
                  shadow_only=True, odds_requests=0, leagues=[])
    for league in ("NBA", "NFL"):
        try:
            output["leagues"].append(run(league, get, now))
        except Exception as exc:
            output["leagues"].append(dict(league=league, error=type(exc).__name__))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(output, allow_nan=False))
    temporary.replace(OUTPUT)
    print("\n".join(format_summary(output)))
    if not any(r.get("tested") for r in output["leagues"]):
        raise SystemExit("No games could be backtested")


if __name__ == "__main__":
    main()
