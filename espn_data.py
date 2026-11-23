"""Game-log history from ESPN's public JSON (works from GitHub's cloud IPs; no key)."""
import os, datetime as dt, unicodedata, re, requests, pandas as pd
from concurrent.futures import ThreadPoolExecutor

B = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
HIST_START = dt.date(2025, 10, 21)
PATH, DATES = "data/games.csv", "data/dates.txt"
FIX = {"GS":"GSW","NY":"NYK","SA":"SAS","NO":"NOP","UTAH":"UTA","WSH":"WAS"}
COLS = ["GAME_ID","GAME_DATE","PLAYER_NAME","TEAM_ABBREVIATION","OPP","MIN","PTS","REB","AST",
        "FG3M","STL","BLK","FGA","FTA","TOV"]

def norm(n):
    n = unicodedata.normalize("NFKD", str(n)).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[^a-z ]", "", n)
    return re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", n).replace("  ", " ").strip()

def _get(url, **kw):
    for _ in range(3):
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"}, **kw)
            if r.ok: return r.json()
        except Exception: pass
    return {}

def _day(d):
    j = _get(f"{B}/scoreboard", params={"dates": d.strftime("%Y%m%d"), "limit": 100})
    return d, [(e["id"], e["date"][:10]) for e in j.get("events", [])
               if e.get("status", {}).get("type", {}).get("completed")]

def _pair(v):
    try: return [float(x) for x in str(v).split("-")]
    except Exception: return [0.0, 0.0]

def parse_game(gid, date):
    j = _get(f"{B}/summary", params={"event": gid})
    teams = j.get("boxscore", {}).get("players", [])
    if len(teams) != 2: return []
    abbr = [FIX.get(t["team"]["abbreviation"], t["team"]["abbreviation"]) for t in teams]
    rows = []
    for i, t in enumerate(teams):
        for blk in t.get("statistics", []):
            keys = blk.get("keys", [])
            for a in blk.get("athletes", []):
                if a.get("didNotPlay") or not a.get("stats"): continue
                d = dict(zip(keys, a["stats"]))
                try: mn = float(d.get("minutes", 0))
                except Exception: continue
                if mn <= 0: continue
                f = lambda k: float(d.get(k) or 0)
                rows.append(dict(GAME_ID=gid, GAME_DATE=date, PLAYER_NAME=a["athlete"]["displayName"],
                    TEAM_ABBREVIATION=abbr[i], OPP=abbr[1-i], MIN=mn, PTS=f("points"), REB=f("rebounds"),
                    AST=f("assists"), STL=f("steals"), BLK=f("blocks"), TOV=f("turnovers"),
                    FG3M=_pair(d.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "0-0"))[0],
                    FGA=_pair(d.get("fieldGoalsMade-fieldGoalsAttempted", "0-0"))[1],
                    FTA=_pair(d.get("freeThrowsMade-freeThrowsAttempted", "0-0"))[1]))
    return rows

def update_history(cap=400):
    os.makedirs("data", exist_ok=True)
    hist = pd.read_csv(PATH) if os.path.exists(PATH) else pd.DataFrame(columns=COLS)
    have = set(hist.GAME_ID.astype(str))
    scanned = set(open(DATES).read().split()) if os.path.exists(DATES) else set()
    today = dt.date.today()
    days = [HIST_START + dt.timedelta(n) for n in range((today - HIST_START).days + 1)]
    todo = [d for d in days if d.isoformat() not in scanned or d >= today - dt.timedelta(days=2)]
    games = {}
    with ThreadPoolExecutor(8) as ex:
        for d, evs in ex.map(_day, todo):
            for gid, date in evs: games[gid] = date
            if d < today - dt.timedelta(days=2): scanned.add(d.isoformat())
    missing = sorted([(dt_, g) for g, dt_ in games.items() if g not in have], reverse=True)[:cap]
    new = []
    with ThreadPoolExecutor(8) as ex:
        for rows in ex.map(lambda x: parse_game(x[1], x[0]), missing): new += rows
    print(f"games found {len(games)}, fetched {len(missing)}, player rows {len(new)}")
    if new: hist = pd.concat([hist, pd.DataFrame(new)], ignore_index=True)
    hist = hist.drop_duplicates(["GAME_ID", "PLAYER_NAME"])
    hist.to_csv(PATH, index=False); open(DATES, "w").write("\n".join(sorted(scanned)))
    return load_history()

def load_history():
    h = pd.read_csv(PATH)
    h["GAME_DATE"] = pd.to_datetime(h["GAME_DATE"]); h["KEY"] = h.PLAYER_NAME.map(norm)
    return h
