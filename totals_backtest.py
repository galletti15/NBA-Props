"""Manual shadow backtest: score-average baseline vs possession/drive efficiency.

Replays completed NBA/NFL games using only each team's earlier games. Compares
projections with ACTUAL FINAL totals (overtime included). No sportsbook lines,
no Odds API calls, no publishing. Games are not independent (shared teams and
overlapping windows), so intervals are optimistic. Not calibrated or live.
"""
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from espn_totals_adapters import load_history
from totals_model_v2 import project, timestamp

ROUTES = {"NBA": "basketball/nba", "NFL": "football/nfl"}
COUNTS = {"NBA": 24, "NFL": 14}
EFFICIENCY = {"NBA": "possessions_efficiency", "NFL": "drives_efficiency"}
STRIP = ("opportunities", "opponent_opportunities")
OUTPUT = Path("data/totals-backtest.json")


def baseline_records(rows):
    return [{k: v for k, v in row.items() if k not in STRIP} for row in rows]


def collect_games(histories):
    games = {}
    for tid, rows in histories.items():
        for row in rows:
            games.setdefault(row["id"], {})[tid] = row
    return {gid: teams for gid, teams in games.items() if len(teams) == 2}


def evaluate(league, histories, engine=project):
    rows, skipped = [], {}

    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    for gid, teams in sorted(collect_games(histories).items()):
        (t1, r1), (t2, r2) = sorted(teams.items())
        try:
            same_time = timestamp(r1["date"]) == timestamp(r2["date"])
        except (ValueError, KeyError, TypeError, AttributeError):
            same_time = False
        if not same_time or (r1["scored"], r1["allowed"]) != (r2["allowed"], r2["scored"]):
            skip("inconsistent_pair")
            continue
        cutoff = r1["date"]
        try:
            new = engine(league, histories[t1], histories[t2], cutoff)
            base = engine(league, baseline_records(histories[t1]), baseline_records(histories[t2]), cutoff)
        except (ValueError, KeyError, TypeError):
            skip("engine_error")
            continue
        if new.get("projection") is None or base.get("projection") is None:
            skip("insufficient_history")
            continue
        if new["method"] != EFFICIENCY[league]:
            skip("efficiency_unavailable")
            continue
        if base["method"] != "score_average_fallback":
            skip("baseline_unexpected")
            continue
        rows.append(dict(id=gid, date=cutoff, teams=[t1, t2],
                         actual=r1["scored"] + r1["allowed"],
                         baseline=base["projection"]["total"],
                         efficiency=new["projection"]["total"]))
    return rows, skipped


def error_stats(errors):
    n = len(errors)
    return dict(mae=round(sum(abs(e) for e in errors)/n, 2),
                rmse=round((sum(e*e for e in errors)/n) ** 0.5, 2),
                bias=round(sum(errors)/n, 2))


def summarize(rows, seed=7, resamples=2000):
    if not rows:
        return dict(n=0)
    base = [r["baseline"] - r["actual"] for r in rows]
    eff = [r["efficiency"] - r["actual"] for r in rows]
    gains = [abs(b) - abs(e) for b, e in zip(base, eff)]
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(gains, k=len(gains)))/len(gains) for _ in range(resamples))
    return dict(n=len(rows), baseline=error_stats(base), efficiency=error_stats(eff),
                mean_error_reduction=round(sum(gains)/len(gains), 3),
                ci95=[round(means[int(0.025*resamples)], 3), round(means[int(0.975*resamples)-1], 3)],
                efficiency_closer=sum(g > 1e-9 for g in gains),
                baseline_closer=sum(g < -1e-9 for g in gains),
                ties=sum(abs(g) <= 1e-9 for g in gains))


def make_get(retries=2):
    import requests

    def get(url, **params):
        last = None
        for attempt in range(retries + 1):
            try:
                response = requests.get(url, params=params, timeout=25)
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last = exc
                time.sleep(1 + attempt)
        raise last
    return get


def team_ids(get, route):
    data = get("https://site.api.espn.com/apis/site/v2/sports/" + route + "/teams", limit=1000)
    ids = sorted({str(t["team"]["id"]) for s in data.get("sports", [])
                  for league in s.get("leagues", []) for t in league.get("teams", [])})
    if not ids:
        raise RuntimeError("No ESPN teams returned")
    return ids


def run(league, get, now):
    route, cache, histories, failures = ROUTES[league], {}, {}, 0
    for tid in team_ids(get, route):
        try:
            histories[tid] = load_history(league, route, tid, COUNTS[league], now, get, cache)
        except Exception:
            failures += 1
    rows, skipped = evaluate(league, histories)
    return dict(league=league, teams_loaded=len(histories), team_failures=failures,
                tested=len(rows), skipped=skipped, summary=summarize(rows), games=rows)


def format_summary(output):
    lines = []
    for result in output["leagues"]:
        if "error" in result:
            lines.append(result["league"] + " ERROR " + result["error"])
            continue
        s = result["summary"]
        lines.append("== " + result["league"] + " tested " + str(result["tested"]) + " teams " + str(result["teams_loaded"]) + " failed " + str(result["team_failures"]))
        lines.append("skipped " + json.dumps(result["skipped"], sort_keys=True))
        if s["n"]:
            lines.append("MAE old " + str(s["baseline"]["mae"]) + " new " + str(s["efficiency"]["mae"]))
            lines.append("RMSE old " + str(s["baseline"]["rmse"]) + " new " + str(s["efficiency"]["rmse"]))
            lines.append("bias old " + str(s["baseline"]["bias"]) + " new " + str(s["efficiency"]["bias"]))
            lines.append("gain " + str(s["mean_error_reduction"]) + " CI " + str(s["ci95"]))
            lines.append("closer new " + str(s["efficiency_closer"]) + " old " + str(s["baseline_closer"]) + " tie " + str(s["ties"]))
    return lines


def main():
    now = datetime.now(timezone.utc)
    get = make_get()
    output = dict(updated=now.isoformat(), backtest=True, shadow_only=True, odds_requests=0, leagues=[])
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
