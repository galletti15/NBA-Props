"""NBA prop projection pipeline. Run: python pipeline.py  (needs ODDS_API_KEY env)"""
import os, json, math, datetime as dt, requests, numpy as np, pandas as pd
from scipy import stats as st
from nba_api.stats.endpoints import playergamelogs, leaguedashteamstats
from nba_api.stats.static import teams as nbateams

SEASON, PREV = "2026-27", ["2025-26", "2024-25"]
KEY = os.environ.get("ODDS_API_KEY", "")
BASE = "https://api.the-odds-api.com/v4/sports/basketball_nba"
MARKETS = {"player_points":"PTS","player_rebounds":"REB","player_assists":"AST",
           "player_threes":"FG3M","player_steals":"STL","player_blocks":"BLK"}
OUT = "docs/data.json"
HDR = {"User-Agent": "Mozilla/5.0"}
P_PLAY = {"out":0.0,"doubtful":0.1,"questionable":0.5,"day-to-day":0.7,"probable":0.9}
K_PRIOR, W_LAST = 400.0, 0.35   # tune with backtest.py

def logs(season):
    df = playergamelogs.PlayerGameLogs(season_nullable=season, timeout=60).get_data_frames()[0]
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"]); return df

def team_ctx(season):
    d = leaguedashteamstats.LeagueDashTeamStats(season=season, measure_type_detailed="Advanced",
                                                timeout=60).get_data_frames()[0]
    lg_d, lg_p = d.DEF_RATING.mean(), d.PACE.mean()
    abbr = {t["id"]: t["abbreviation"] for t in nbateams.get_teams()}
    return {abbr.get(r.TEAM_ID): (r.DEF_RATING/lg_d, r.PACE/lg_p) for r in d.itertuples()}

def injuries():
    j = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries",
                     headers=HDR, timeout=30).json()
    return {i["athlete"]["displayName"]: i.get("status", "")
            for t in j.get("injuries", []) for i in t.get("injuries", [])}

def play_prob(inj, name):
    s = inj.get(name, "").lower()
    return next((v for k, v in P_PLAY.items() if k in s), 1.0)

def odds_events():
    r = requests.get(f"{BASE}/events", params={"apiKey":KEY}, timeout=30).json()
    cutoff = dt.datetime.utcnow() + dt.timedelta(hours=30)
    return [e for e in r if pd.to_datetime(e["commence_time"]).tz_localize(None) < cutoff]

def spreads():
    """Home-team median spread per event id (negative = home favored)."""
    r = requests.get(f"{BASE}/odds", params={"apiKey":KEY,"regions":"us","markets":"spreads",
                     "oddsFormat":"american"}, timeout=30).json()
    out = {}
    for e in r:
        pts = [o["point"] for b in e.get("bookmakers", []) for m in b["markets"]
               for o in m["outcomes"] if o["name"] == e["home_team"]]
        if pts: out[e["id"]] = float(np.median(pts))
    return out

def props(ev):
    r = requests.get(f"{BASE}/events/{ev['id']}/odds", params={"apiKey":KEY,"regions":"us",
        "markets":",".join(MARKETS),"oddsFormat":"american"}, timeout=30).json()
    rows = []
    for b in r.get("bookmakers", []):
        for m in b["markets"]:
            by = {}
            for o in m["outcomes"]:
                by.setdefault((o["description"], o["point"]), {})[o["name"]] = o["price"]
            for (p, line), s in by.items():
                if "Over" in s and "Under" in s:
                    rows.append(dict(player=p, market=m["key"], line=line, book=b["title"],
                                     over=s["Over"], under=s["Under"], game=ev))
    return rows

def teammate_boost(cur, team, player, inj):
    """Usage/minutes uplift when high-usage teammates are out or doubtful."""
    t = cur[cur.TEAM_ABBREVIATION == team]
    g = t.groupby("PLAYER_NAME").agg(mn=("MIN","mean"), n=("MIN","size"),
        fga=("FGA","mean"), fta=("FTA","mean"), tov=("TOV","mean"))
    g = g[(g.mn >= 15) & (g.n >= 5)]
    g["u"] = (g.fga + 0.44*g.fta + g.tov) * g.mn / 36
    tot = g.u.sum()
    if tot <= 0: return 0.0
    missing = sum((row.u/tot) * (1 - play_prob(inj, nm)) for nm, row in g.iterrows() if nm != player)
    missing = min(missing, 0.6)
    return float(min(0.25, 0.5 * missing / (1 - missing)))

def imp(a): return 100/(a+100) if a > 0 else -a/(-a+100)
def novig(o, u): po, pu = imp(o), imp(u); return po/(po+pu)
def wavg(x, w): x, w = np.asarray(x, float), np.asarray(w, float); return (x*w).sum()/w.sum()

def project(cur, prev, stat, opp_def, opp_pace, own_pace, b2b, spread, usage_boost):
    """Per-minute rate (Bayesian blend of history, season, last 10) x projected minutes x matchup."""
    cur = cur.sort_values("GAME_DATE"); pri = prev.sort_values("GAME_DATE")
    n = len(cur)
    pw = 0.97 ** np.arange(len(pri))[::-1]
    prior = wavg(pri[stat]/pri.MIN.clip(lower=1), pri.MIN*pw) if len(pri) >= 15 else np.nan
    cur_rate = cur[stat].sum()/max(cur.MIN.sum(), 1) if n else np.nan
    last = cur.tail(10)
    last_rate = wavg(last[stat]/last.MIN.clip(lower=1), last.MIN*np.linspace(.5, 1, len(last))) if n else np.nan
    base = prior if not np.isnan(prior) else cur_rate
    m = cur.MIN.sum() if n else 0
    season_est = (m*cur_rate + K_PRIOR*base)/(m + K_PRIOR) if n else base
    rate = (1-W_LAST)*season_est + W_LAST*(last_rate if n >= 5 else season_est)
    mh = cur.MIN.tail(10).values if n >= 5 else pri.MIN.tail(20).values
    mins = wavg(mh, np.linspace(.5, 1, len(mh))); sd = max(np.std(mh), 2.0)
    if b2b: mins *= 0.97
    if abs(spread) > 11: mins *= 1 - min(0.08, (abs(spread)-11)*0.01)
    mins *= 1 + usage_boost*0.5
    mu = rate*mins*(opp_pace*own_pace)**0.5*opp_def**0.6*(1 + usage_boost*0.6)
    return mu, (sd/max(mins, 1))**2

def p_over(mu, line, var_extra, stat):
    if mu <= 0: return 0.0
    k = math.floor(line)
    if stat in ("PTS","REB","AST","FG3M"):
        var = max(mu*(1.15 + var_extra*mu*0.5), mu*1.05)
        p = mu/var; n = mu*p/(1-p)
        return float(st.nbinom.sf(k, n, p))
    return float(st.poisson.sf(k, mu))

def main():
    cur = logs(SEASON)
    prev = pd.concat([logs(s) for s in PREV])
    ctx = team_ctx(SEASON); inj = injuries(); sp = spreads()
    rows = []
    for ev in odds_events():
        try: rows += props(ev)
        except Exception as e: print("odds fail", e)
    teams = {t["full_name"]: t["abbreviation"] for t in nbateams.get_teams()}
    df = pd.DataFrame(rows); out = []
    if not df.empty:
        for (player, mkt), g in df.groupby(["player","market"]):
            stat = MARKETS[mkt]
            c = cur[cur.PLAYER_NAME == player]; p = prev[prev.PLAYER_NAME == player]
            if len(c) + len(p) < 15: continue
            pp = play_prob(inj, player)
            if pp == 0: continue
            ev = g.iloc[0]["game"]
            team = (c if len(c) else p).sort_values("GAME_DATE").iloc[-1].TEAM_ABBREVIATION
            home, away = teams.get(ev["home_team"]), teams.get(ev["away_team"])
            opp = away if team == home else home
            od, op = ctx.get(opp, (1, 1)); _, own = ctx.get(team, (1, 1))
            b2b = bool(len(c) and (pd.Timestamp(ev["commence_time"]).tz_localize(None) - c.GAME_DATE.max()).days <= 1)
            usage = teammate_boost(cur, team, player, inj)
            hs = sp.get(ev["id"], 0.0); spread = hs if team == home else -hs
            mu, ve = project(c, p, stat, od, op, own, b2b, spread, usage)
            line = float(g.line.median())
            bo = g.loc[g.over.idxmax()]; bu = g.loc[g.under.idxmax()]
            po = p_over(mu, line, ve, stat)
            fair = float(np.mean([novig(r.over, r.under) for r in g.itertuples()]))
            out.append(dict(player=player, team=team, opp=opp, market=stat, proj=round(mu, 2), line=line,
                p_over=round(po, 3), mkt_p_over=round(fair, 3), edge=round((po-fair)*pp, 3),
                play_prob=pp, usage_boost=round(usage, 3), spread=spread,
                pick="OVER" if po > fair else "UNDER", best_over=f"{bo.over:+d} {bo.book}",
                best_under=f"{bu.under:+d} {bu.book}", status=inj.get(player, "").lower() or "healthy",
                tip=ev["commence_time"]))
        out.sort(key=lambda r: -abs(r["edge"]))
    json.dump({"updated": dt.datetime.utcnow().isoformat()+"Z", "props": out}, open(OUT, "w"))
    print(len(out), "props written")

if __name__ == "__main__": main()
