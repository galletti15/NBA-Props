"""Experimental totals engine. Explicit inputs only; no network or live activation.

History records require date, scored, allowed. Optional regulation_scored and
regulation_allowed must be supplied together. opportunities means possessions
for basketball or offensive drives for football, with matching score scope.
Context features are reported, not assigned invented point adjustments.
"""
from datetime import datetime
from math import isfinite

CONFIG = {"NBA": (5, 12), "NCAAB": (5, 12), "NFL": (3, 8), "NCAAF": (3, 8)}
CONTEXT = ("shooting_profile", "injuries", "lineups", "rest", "travel",
           "opponent_strength", "coaching", "roster_continuity", "location",
           "weather", "unusual_scoring")

def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamps must include a timezone")
    return result

def number(value, positive=False):
    if isinstance(value, bool):
        raise ValueError("Boolean is not a numeric observation")
    result = float(value)
    if not isfinite(result) or result < 0 or (positive and result == 0):
        raise ValueError("Invalid numeric observation")
    return result

def prepare(records, cutoff, limit):
    result = []
    seen = set()
    for record in records:
        row = dict(record)
        date = timestamp(row["date"])
        if date >= cutoff:
            continue
        identity = row.get("id", row["date"])
        if identity in seen:
            raise ValueError("Duplicate historical game")
        seen.add(identity)
        has_regulation = [row.get(k) is not None for k in
                          ("regulation_scored", "regulation_allowed")]
        if any(has_regulation) and not all(has_regulation):
            raise ValueError("Both regulation scores are required")
        row["normalized"] = all(has_regulation)
        row["scored"] = number(row["regulation_scored"] if all(has_regulation) else row["scored"])
        row["allowed"] = number(row["regulation_allowed"] if all(has_regulation) else row["allowed"])
        if row.get("opportunities") is not None:
            row["opportunities"] = number(row["opportunities"], positive=True)
        result.append((date, row))
    return [row for _, row in sorted(result, key=lambda item: item[0])[-limit:]]

def average(rows, field):
    weights = [0.9 ** (len(rows) - i - 1) for i in range(len(rows))]
    return sum(row[field] * w for row, w in zip(rows, weights)) / sum(weights)

def project(league, home, away, as_of, context=None):
    minimum, limit = CONFIG[league]
    cutoff = timestamp(as_of)
    home, away = prepare(home, cutoff, limit), prepare(away, cutoff, limit)
    context = context or {}
    coverage = {name: {"status": "provided_not_applied" if context.get(name) is not None
                       else "unavailable", "applied": False} for name in CONTEXT}
    result = {"version": "experimental-v2-foundation", "league": league,
              "sample": {"home": len(home), "away": len(away)},
              "coverage": coverage, "projection": None,
              "backtested": False, "calibrated_probabilities": False}
    if min(len(home), len(away)) < minimum:
        result["method"] = "insufficient_history"
        return result
    rows = home + away
    normalized = all(row["normalized"] for row in rows)
    coverage["regulation_scores"] = {"status": "applied" if normalized else "partial_or_unavailable",
                                      "applied": any(row["normalized"] for row in rows)}
    usable = all(row.get("opportunities") is not None and
                 row.get("opportunity_scope") == ("regulation" if row["normalized"] else "final")
                 for row in rows)
    if usable:
        expected = (average(home, "opportunities") + average(away, "opportunities")) / 2
        rates = []
        for team in (home, away):
            rates.append({field: average([{field: row[field] / row["opportunities"]}
                                         for row in team], field) for field in ("scored", "allowed")})
        hp = expected * (rates[0]["scored"] + rates[1]["allowed"]) / 2
        ap = expected * (rates[1]["scored"] + rates[0]["allowed"]) / 2
        result["method"] = "possessions_efficiency" if league in ("NBA", "NCAAB") else "drives_efficiency"
        result["expected_opportunities"] = round(expected, 3)
    else:
        hp = (average(home, "scored") + average(away, "allowed")) / 2
        ap = (average(away, "scored") + average(home, "allowed")) / 2
        result["method"] = "score_average_fallback"
    coverage["opportunity_efficiency"] = {"status": "applied" if usable else "unavailable_or_scope_mismatch",
                                           "applied": usable}
    hp, ap = round(hp, 1), round(ap, 1)
    result["projection"] = {"home": hp, "away": ap, "total": round(hp + ap, 1)}
    result["target"] = "regulation" if normalized else "final_or_mixed_score_scope"
    result["market_comparable"] = False
    result["warning"] = "Experimental; market overtime rules and data scope require verification."
    return result
