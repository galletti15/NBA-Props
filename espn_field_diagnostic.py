"""Manual ESPN field diagnostic. Read-only: no odds API, no secrets, no repo writes."""
import json, sys
from datetime import datetime, timedelta, timezone
import requests

BASE = "https://site.api.espn.com/apis/site/v2/sports/"
LEAGUES = {"NBA": "basketball/nba", "NCAAB": "basketball/mens-college-basketball",
           "NFL": "football/nfl", "NCAAF": "football/college-football"}

def fetch(url, **params):
    r = requests.get(url, params=params, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()

def shape(summary):
    box = summary.get("boxscore", {})
    comps = (summary.get("header", {}).get("competitions") or [{}])[0].get("competitors", [])
    teams = box.get("teams", [])
    drives = summary.get("drives", {})
    first = (drives.get("previous") or [{}])[0] if isinstance(drives, dict) else {}
    return {
        "period_scores": [[str(p.get("displayValue", p.get("value"))) for p in c.get("linescores", [])] for c in comps],
        "final_scores": [c.get("score") for c in comps],
        "team_stat_names": [[s.get("name") for s in t.get("statistics", [])] for t in teams][:1],
        "team_stat_sample": [{s.get("name"): s.get("displayValue") for s in t.get("statistics", [])} for t in teams][:1],
        "drive_count": len(drives.get("previous", [])) if isinstance(drives, dict) else 0,
        "drive_keys": sorted(first.keys()),
        "summary_keys": sorted(summary.keys()),
    }

def main():
    out, today = {}, datetime.now(timezone.utc).date()
    for label, route in LEAGUES.items():
        found, errors = [], []
        for back in range(1, 15):
            if len(found) >= 2:
                break
            day = (today - timedelta(days=back)).strftime("%Y%m%d")
            try:
                events = fetch(BASE + route + "/scoreboard", dates=day, limit=50).get("events", [])
                for e in events:
                    if len(found) < 2 and e.get("status", {}).get("type", {}).get("completed"):
                        found.append({"event": e["id"], "date": e["date"], **shape(fetch(BASE + route + "/summary", event=e["id"]))})
            except Exception as exc:
                errors.append(day + ": " + type(exc).__name__)
        out[label] = {"games": found, "errors": errors[:5]}
    text = json.dumps(out, indent=1)
    open("espn-field-report.json", "w").write(text)
    print(text)
    if not any(v["games"] for v in out.values()):
        sys.exit("No completed games retrieved")

if __name__ == "__main__":
    main()
