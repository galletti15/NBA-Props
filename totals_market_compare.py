"""Market comparison from published history. Read-only; no Odds API calls.

Mines git history of docs/totals.json for each game's last pre-game snapshot
(sportsbook quotes + published projection), joins ESPN final scores, and
compares model vs consensus line. Lines are once-daily snapshots, not closing
lines, and samples are small. Shadow analysis only.
"""
import json
import random
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROUTES = {"NBA": "basketball/nba", "NFL": "football/nfl"}
GAPS = {"NBA": 4.0, "NFL": 3.0}
PATH = "docs/totals.json"
OUTPUT = Path("data/totals-market-compare.json")


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def mean(values):
    return sum(values) / len(values)


def median(values):
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def snapshots():
    for sha in git("log", "--format=%H", "--", PATH).split():
        try:
            yield json.loads(git("show", sha + ":" + PATH))
        except Exception:
            continue


def collect(snaps, leagues=("NBA", "NFL"), min_books=3):
    best = {}
    for snap in snaps:
        for league in snap.get("leagues", []):
            if league.get("league") not in leagues:
                continue
            for game in league.get("games", []):
                quotes = game.get("game_quotes") or []
                if len(quotes) < min_books or not game.get("start"):
                    continue
                try:
                    start = parse(game["start"])
                    stamps = [parse(q["updated"]) for q in quotes]
                    lines = [float(q["line"]) for q in quotes]
                except (KeyError, ValueError, TypeError):
                    continue
                quote_time = sorted(stamps)[len(stamps) // 2]
                if quote_time >= start:
                    continue
                key = (league["league"], game["home"], game["away"], game["start"])
                if key not in best or quote_time > best[key]["quote_time"]:
                    projection = (game.get("projection") or {}).get("total")
                    best[key] = dict(league=key[0], home=key[1], away=key[2], start=key[3],
                                     quote_time=quote_time, line=median(lines), books=len(lines),
                                     model=projection)
    rows = list(best.values())
    for r in rows:
        r["lead_hours"] = round((parse(r["start"]) - r["quote_time"]).total_seconds() / 3600, 1)
        r["quote_time"] = r["quote_time"].isoformat()
    return sorted(rows, key=lambda r: r["start"])


def parse_finals(data):
    finals = []
    for event in data.get("events", []):
        try:
            comp = event["competitions"][0]
            if not comp["status"]["type"]["completed"]:
                continue
            teams = {c["homeAway"]: c for c in comp["competitors"]}
            finals.append(dict(start=parse(event["date"]), home=teams["home"]["team"]["name"],
                               away=teams["away"]["team"]["name"],
                               total=float(teams["home"]["score"]) + float(teams["away"]["score"])))
        except (KeyError, ValueError, TypeError, IndexError):
            continue
    return finals


def match(game, finals):
    start = parse(game["start"])
    for f in finals:
        if game["home"].endswith(f["home"]) and game["away"].endswith(f["away"]) and abs(f["start"] - start) < timedelta(hours=6):
            return f["total"]
    return None


def pick_record(rows, min_gap):
    wins = losses = pushes = 0
    for r in rows:
        gap = r["model"] - r["line"]
        if gap == 0 or abs(gap) < min_gap:
            continue
        if r["actual"] == r["line"]:
            pushes += 1
        elif (gap > 0) == (r["actual"] > r["line"]):
            wins += 1
        else:
            losses += 1
    return dict(wins=wins, losses=losses, pushes=pushes)


def summarize(rows, min_gap, seed=7, resamples=2000):
    out = dict(n=len(rows))
    if not rows:
        return out
    errs = [r["line"] - r["actual"] for r in rows]
    out["market"] = dict(mae=round(mean([abs(e) for e in errs]), 2), bias=round(mean(errs), 2))
    modeled = [r for r in rows if r.get("model") is not None]
    out["modeled"] = len(modeled)
    if not modeled:
        return out
    merrs = [r["model"] - r["actual"] for r in modeled]
    same = [r["line"] - r["actual"] for r in modeled]
    gains = [abs(a) - abs(b) for a, b in zip(same, merrs)]
    rng = random.Random(seed)
    boots = sorted(sum(rng.choices(gains, k=len(gains))) / len(gains) for _ in range(resamples))
    out["model"] = dict(mae=round(mean([abs(e) for e in merrs]), 2), bias=round(mean(merrs), 2))
    out["market_same_rows"] = dict(mae=round(mean([abs(e) for e in same]), 2))
    out["edge_vs_market"] = round(mean(gains), 3)
    out["ci95"] = [round(boots[int(0.025 * resamples)], 3), round(boots[int(0.975 * resamples) - 1], 3)]
    out["picks_all"] = pick_record(modeled, 0)
    out["picks_big_gap"] = dict(min_gap=min_gap, **pick_record(modeled, min_gap))
    return out


def format_report(results):
    lines = []
    for r in results:
        s = r["summary"]
        lines.append("== " + r["league"] + " games " + str(s["n"]) + " modeled " + str(s.get("modeled", 0)))
        if s["n"] == 0:
            continue
        lines.append("market MAE " + str(s["market"]["mae"]) + " bias " + str(s["market"]["bias"]))
        if "model" in s:
            lines.append("model MAE " + str(s["model"]["mae"]) + " bias " + str(s["model"]["bias"]) + " | market same rows " + str(s["market_same_rows"]["mae"]))
            lines.append("edge vs market " + str(s["edge_vs_market"]) + " CI " + str(s["ci95"]))
            lines.append("picks all " + json.dumps(s["picks_all"], sort_keys=True))
            lines.append("picks gap>=" + str(s["picks_big_gap"]["min_gap"]) + " " + json.dumps({k: v for k, v in s["picks_big_gap"].items() if k != "min_gap"}, sort_keys=True))
    return lines


def main():
    from totals_backtest import make_get
    get = make_get()
    now = datetime.now(timezone.utc)
    games = collect(snapshots())
    results = []
    for league, route in ROUTES.items():
        mine = [g for g in games if g["league"] == league and parse(g["start"]) < now - timedelta(hours=5)]
        dates = sorted({d.strftime("%Y%m%d") for g in mine for d in (parse(g["start"]), parse(g["start"]) - timedelta(days=1))})
        finals = []
        for date in dates:
            try:
                finals += parse_finals(get("https://site.api.espn.com/apis/site/v2/sports/" + route + "/scoreboard", dates=date, limit=300))
            except Exception:
                continue
        rows = []
        for g in mine:
            actual = match(g, finals)
            if actual is not None:
                rows.append(dict(g, actual=actual))
        results.append(dict(league=league, unmatched=len(mine) - len(rows), summary=summarize(rows, GAPS[league]), games=rows))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(dict(updated=now.isoformat(), odds_requests=0, results=results), allow_nan=False))
    print("\n".join(format_report(results)))
    for r in results:
        print(r["league"] + " unmatched " + str(r["unmatched"]))


if __name__ == "__main__":
    main()
