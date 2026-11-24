"""Pure NBA/NFL ESPN adapters and shadow-only history loader. No odds calls."""
from datetime import datetime
from math import isfinite


def number(value):
    if isinstance(value, dict):
        value = value.get("value", value.get("displayValue"))
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def attempts(value):
    parts = value.split("-") if isinstance(value, str) else []
    if len(parts) != 2:
        return None
    made, total = map(number, parts)
    if made is None or total is None or not made.is_integer() or not total.is_integer() or made > total:
        return None
    return total


def adapt_espn(summary, league):
    if league not in ("NBA", "NFL"):
        raise ValueError("Only NBA and NFL supported")
    header = summary.get("header") or {}
    games = header.get("competitions") or []
    if len(games) != 1:
        raise ValueError("Expected one competition")
    game = games[0]
    if not game.get("status", {}).get("type", {}).get("completed"):
        raise ValueError("Completed game required")
    event = header.get("id") or game.get("id")
    date = game.get("date") or header.get("date")
    dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
    if not event or dt.tzinfo is None:
        raise ValueError("Event ID and timezone-aware date required")
    teams = game.get("competitors") or []
    ids = [str(t.get("team", {}).get("id") or "") for t in teams]
    scores = [number(t.get("score")) for t in teams]
    if len(ids) != 2 or not all(ids) or len(set(ids)) != 2 or any(s is None for s in scores):
        raise ValueError("Two distinct teams and final scores required")
    boxes = {}
    for box in summary.get("boxscore", {}).get("teams", []):
        tid = str(box.get("team", {}).get("id") or "")
        if tid in boxes:
            raise ValueError("Duplicate boxscore team")
        boxes[tid] = {s["name"]: s.get("displayValue") if s.get("displayValue") is not None else s.get("value")
                      for s in box.get("statistics", []) if s.get("name")}
    counts = []
    for tid in ids:
        stats = boxes.get(tid, {})
        if league == "NBA":
            fga = attempts(stats.get("fieldGoalsMade-fieldGoalsAttempted"))
            fta = attempts(stats.get("freeThrowsMade-freeThrowsAttempted"))
            orb, tov = number(stats.get("offensiveRebounds")), number(stats.get("turnovers"))
            count = fga + .44*fta - orb + tov if all(v is not None for v in (fga, fta, orb, tov)) else None
        else:
            count = number(stats.get("totalDrives"))
            if count is not None and not count.is_integer():
                count = None
        counts.append(count if count is not None and count > 0 else None)
    shared = sum(counts)/2 if all(c is not None for c in counts) else None
    records = {}
    for i, tid in enumerate(ids):
        j = 1-i
        periods = [number(p) for p in teams[i].get("linescores", [])]
        reconciles = len(periods) >= 4 and all(p is not None for p in periods)
        reg = sum(periods[:4]) if reconciles and abs(sum(periods)-scores[i]) < .01 else None
        records[tid] = dict(id=str(event), date=date, scored=scores[i], allowed=scores[j],
                            team_id=tid, opponent_id=ids[j], opportunity_scope="final",
                            opportunities=shared if league == "NBA" else counts[i],
                            opponent_opportunities=shared if league == "NBA" else counts[j],
                            raw_opportunities=counts[i], regulation_scored_metadata=reg,
                            raw_stats=boxes.get(tid, {}),
                            input_warnings=[] if all(c is not None for c in counts) else ["Missing opportunity inputs"],
                            opportunity_method="estimated_possessions" if league == "NBA" else "team_totalDrives")
    return dict(league=league, event_id=str(event), records_by_team=records)


def adapt_nba(summary):
    return adapt_espn(summary, "NBA")


def adapt_nfl(summary):
    return adapt_espn(summary, "NFL")


def load_history(league, route, tid, count, now, get, cache):
    """Manual-shadow ESPN schedule + summary loading; per-run response cache.

    Summary failures preserve schedule scores and explicitly trigger fallback.
    Regular-season selection matches the existing provider. Scores include
    defensive/special-teams scoring; this is not offensive-only efficiency.
    """
    tid = str(tid)
    key = ("adapter_history", league, tid, count, now.isoformat())
    if key in cache:
        return cache[key]
    root = "https://site.api.espn.com/apis/site/v2/sports/" + route
    season = now.year + (1 if league == "NBA" and now.month >= 7 else 0)
    if league == "NFL" and now.month < 3:
        season -= 1
    selected, schedule_warnings = {}, []
    successes = 0
    for year in (season, season-1):
        try:
            data = get(root + "/teams/" + tid + "/schedule", season=year, seasontype=2)
            successes += 1
        except Exception as exc:
            schedule_warnings.append("Schedule unavailable: " + type(exc).__name__)
            continue
        for event in data.get("events", []):
            try:
                comp = event["competitions"][0]
                if not comp.get("status", event.get("status", {})).get("type", {}).get("completed"):
                    continue
                dt = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
                if dt >= now:
                    continue
                teams = comp.get("competitors", [])
                own = [t for t in teams if str(t.get("team", {}).get("id")) == tid]
                opp = [t for t in teams if str(t.get("team", {}).get("id")) != tid]
                if len(own) != 1 or len(opp) != 1:
                    continue
                scored, allowed = number(own[0].get("score")), number(opp[0].get("score"))
                if scored is None or allowed is None:
                    continue
                eid = str(event["id"])
                selected[eid] = dict(id=eid, date=dt.isoformat(), scored=scored, allowed=allowed)
            except (KeyError, ValueError, TypeError, IndexError):
                schedule_warnings.append("Malformed schedule event skipped")
    if successes == 0:
        raise ValueError("No ESPN schedules available")
    result = []
    for base in sorted(selected.values(), key=lambda r: r["date"])[-count:]:
        row = dict(base, input_warnings=list(schedule_warnings))
        ck = ("summary", league, base["id"])
        if ck not in cache:
            try:
                cache[ck] = (get(root + "/summary", event=base["id"]), None)
            except Exception as exc:
                cache[ck] = (None, type(exc).__name__)
        payload, error = cache[ck]
        try:
            if error:
                raise ValueError(error)
            adapted = adapt_espn(payload, league)["records_by_team"][tid]
            if adapted["id"] != base["id"] or datetime.fromisoformat(adapted["date"].replace("Z", "+00:00")) != datetime.fromisoformat(base["date"]):
                raise ValueError("Summary identity mismatch")
            if (adapted["scored"], adapted["allowed"]) != (base["scored"], base["allowed"]):
                raise ValueError("Summary scores mismatch")
            row.update(adapted)
            row["input_warnings"] = schedule_warnings + adapted["input_warnings"]
        except (ValueError, KeyError, TypeError, AttributeError):
            row["input_warnings"].append("Summary unavailable/invalid; score-only fallback")
        result.append(row)
    cache[key] = result
    return result
