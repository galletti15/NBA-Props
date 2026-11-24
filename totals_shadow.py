"""Shadow totals integration. Run manually; never writes published totals.
Uses existing ESPN history only. Advanced inputs remain unavailable.
No Odds API calls, new subscriptions, workflow edits, or live activation.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from totals_model_v2 import project, timestamp

OUTPUT = Path("data/totals-shadow.json")

def records(history):
    return [dict(date=row[0], scored=row[1], allowed=row[2]) for row in history]

def build(saved, provider, engine=project, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    provider.NOW = now
    provider.CACHE.clear()
    output = dict(updated=now.isoformat(), source_updated=saved.get("updated"),
                  shadow_only=True, backtested=False, odds_requests=0, leagues=[])
    for league in saved.get("leagues", []):
        label = league["league"]
        result = dict(league=label, games=[], errors=[])
        output["leagues"].append(result)
        if label not in provider.SPORTS:
            result["errors"].append("Unsupported league")
            continue
        _, route, _, count = provider.SPORTS[label]
        upcoming = []
        for game in league.get("games", []):
            try:
                if timestamp(game["start"]) > now:
                    upcoming.append(game)
            except (ValueError, KeyError, TypeError):
                result["errors"].append("Invalid game start")
        if not upcoming:
            continue
        try:
            index = provider.team_index(route)
        except Exception as exc:
            result["errors"].append("Team index unavailable: " + type(exc).__name__)
            continue
        for game in upcoming[:8]:
            row = {field: game[field] for field in ("home", "away", "start")}
            row.update(published_projection=game.get("projection"), shadow=None)
            try:
                hi, ai = index.get(provider.key(game["home"])), index.get(provider.key(game["away"]))
                if not hi or not ai:
                    raise ValueError("Team match unavailable")
                home = records(provider.history(route, hi, count))
                away = records(provider.history(route, ai, count))
                row["shadow"] = engine(label, home, away, now.isoformat())
            except Exception as exc:
                row["error"] = "Shadow projection unavailable: " + type(exc).__name__
            result["games"].append(row)
    return output

def main():
    import totals_pipeline as provider
    saved = json.loads(Path("docs/totals.json").read_text())
    output = build(saved, provider)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(output, allow_nan=False))
    temporary.replace(OUTPUT)

if __name__ == "__main__":
    main()
