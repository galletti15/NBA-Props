"""Experimental score-based totals baseline; no betting probabilities."""
import json, os, re, time, unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

SPORTS = {
    'NBA': ('basketball_nba', 'basketball/nba', 5, 12),
    'NFL': ('americanfootball_nfl', 'football/nfl', 3, 8),
    'NCAAF': ('americanfootball_ncaaf', 'football/college-football', 3, 8),
    'NCAAB': ('basketball_ncaab', 'basketball/mens-college-basketball', 5, 12),
}
MAX_GAMES = {'NBA': 8, 'NFL': 8, 'NCAAF': None, 'NCAAB': None}
WINDOW_DAYS = {'NBA': 7, 'NFL': 7, 'NCAAF': 7, 'NCAAB': 1}
START = time.monotonic()
HISTORY_SECONDS = 900
NOW = datetime.now(timezone.utc)
CACHE = {}
BUDGET = 16
RESERVE = 250
NOTE = 'Experimental score-average baseline, not backtested. No pace, possession, injury, weather or strength-of-schedule adjustments. No calibrated probabilities. NBA/NFL: up to 8 upcoming games in the next 7 days. NCAAF: all games in the next 7 days. NCAAB: all games in the next 24 hours. Actual team-total odds checked for first 2 games per league. Other team lines are unavailable, not inferred. Odds refresh every 6 hours; decimal prices. History: latest 12 basketball or 8 football games, current plus prior season.'

def key(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii','ignore').decode().lower()
    return re.sub('[^a-z0-9]', '', s)

def get(url, **params):
    r = requests.get(url, params=params, timeout=25)
    r.raise_for_status()
    return r.json()

def odds(sport, path, **params):
    global BUDGET
    cost = 1
    if BUDGET < cost:
        raise RuntimeError('Totals per-run request budget reached')
    BUDGET -= cost
    r = requests.get('https://api.the-odds-api.com/v4/sports/'+sport+path,
        params=dict(apiKey=os.environ['ODDS_API_KEY'],regions='us',oddsFormat='decimal',**params),timeout=30)
    if not r.ok:
        raise RuntimeError('Odds provider HTTP '+str(r.status_code))
    remaining = r.headers.get('x-requests-remaining')
    if remaining is not None and float(remaining) < RESERVE:
        BUDGET = 0
        raise RuntimeError('Totals paused: shared odds-credit reserve reached (250)')
    return r.json()

def team_index(route):
    data = get('https://site.api.espn.com/apis/site/v2/sports/'+route+'/teams',limit=1000)
    aliases = {}
    for sport in data.get('sports',[]):
        for league in sport.get('leagues',[]):
            for item in league.get('teams',[]):
                t = item['team']
                for field in ('displayName','shortDisplayName'):
                    if t.get(field):
                        aliases.setdefault(key(t[field]),set()).add(str(t['id']))
    if not aliases:
        raise RuntimeError('No ESPN teams returned')
    return {k:next(iter(v)) for k,v in aliases.items() if len(v)==1}

def score(c):
    s = c.get('score')
    return float(s.get('value')) if isinstance(s,dict) else float(s)

def history(route, tid, count):
    ck = (route,tid)
    if ck in CACHE:
        return CACHE[ck]
    season = NOW.year + (1 if route.startswith('basketball') and NOW.month>=7 else 0)
    if route.startswith('football') and NOW.month<3:
        season -= 1
    games = {}
    for year in (season,season-1):
        data = get('https://site.api.espn.com/apis/site/v2/sports/'+route+'/teams/'+tid+'/schedule',season=year,seasontype=2)
        for event in data.get('events',[]):
            for comp in event.get('competitions',[]):
                if not comp.get('status',event.get('status',{})).get('type',{}).get('completed'):
                    continue
                dt = datetime.fromisoformat(event['date'].replace('Z','+00:00'))
                if dt >= NOW:
                    continue
                cs = comp.get('competitors',[])
                own = [c for c in cs if str(c.get('team',{}).get('id'))==tid]
                opp = [c for c in cs if str(c.get('team',{}).get('id'))!=tid]
                if len(own)!=1 or len(opp)!=1:
                    continue
                games[str(event['id'])] = (dt.isoformat(),score(own[0]),score(opp[0]),year)
    result = sorted(games.values())[-count:]
    CACHE[ck] = result
    return result

def estimate(home,away,minimum):
    if min(len(home),len(away)) < minimum:
        return None
    def mean(g,col):
        weights = [0.9**(len(g)-i-1) for i in range(len(g))]
        return sum(x[col]*w for x,w in zip(g,weights))/sum(weights)
    hp = (mean(home,1)+mean(away,2))/2
    ap = (mean(away,1)+mean(home,2))/2
    return round(hp,1),round(ap,1)

def quotes(data,market,team=None):
    result = []
    for book in data.get('bookmakers',[]):
        for m in book.get('markets',[]):
            if m.get('key')!=market:
                continue
            pairs = {}
            for o in m.get('outcomes',[]):
                if o.get('name') not in ('Over','Under') or o.get('point') is None:
                    continue
                if team is not None and key(o.get('description',''))!=key(team):
                    continue
                pairs.setdefault(float(o['point']),{})[o['name']] = float(o['price'])
            for line,sides in pairs.items():
                if len(sides)==2:
                    result.append(dict(book=book['title'],line=line,over=sides['Over'],under=sides['Under'],updated=m.get('last_update',book.get('last_update'))))
    return result

def build_league(label,config):
    sport,route,minimum,count = config
    events = odds(sport,'/odds',markets='totals')
    events = sorted((e for e in events if NOW < datetime.fromisoformat(e['commence_time'].replace('Z','+00:00')) < NOW+timedelta(days=WINDOW_DAYS.get(label,7))),key=lambda e:e['commence_time'])
    result = dict(league=label,games=[],errors=[],available_games=len(events))
    if not events:
        return result
    idx = team_index(route)
    for n,e in enumerate(events[:MAX_GAMES.get(label,8)]):
        home,away = e['home_team'],e['away_team']
        game = dict(home=home,away=away,start=e['commence_time'],projection=None,sample=None,game_quotes=quotes(e,'totals'),home_quotes=[],away_quotes=[],team_odds_status='Not checked: per-run team-total limit',model_status='Team names not matched exactly to ESPN')
        try:
            if time.monotonic()-START > HISTORY_SECONDS:
                game['model_status'] = 'Skipped: refresh time budget reached'
            else:
                hi,ai = idx.get(key(home)),idx.get(key(away))
                if hi and ai:
                    h,a = history(route,hi,count),history(route,ai,count)
                    game['sample'] = dict(home=len(h),away=len(a))
                    p = estimate(h,a,minimum)
                    game['model_status'] = 'Insufficient completed-game history' if p is None else 'Experimental score-average baseline'
                    if p:
                        game['projection'] = dict(home=p[0],away=p[1],total=round(p[0]+p[1],1))
        except Exception as exc:
            game['model_status'] = 'History unavailable: '+type(exc).__name__
        if n<2:
            try:
                d = odds(sport,'/events/'+e['id']+'/odds',markets='team_totals')
                game['home_quotes'] = quotes(d,'team_totals',home)
                game['away_quotes'] = quotes(d,'team_totals',away)
                game['team_odds_status'] = 'Checked; unavailable lines are not inferred'
            except Exception as exc:
                game['team_odds_status'] = str(exc)
        result['games'].append(game)
    return result

def main():
    output = dict(updated=NOW.isoformat(),note=NOTE,leagues=[])
    for label,config in SPORTS.items():
        try:
            result = build_league(label,config)
        except Exception as exc:
            result = dict(league=label,games=[],errors=[str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__],available_games=None)
        output['leagues'].append(result)
    target = Path('docs/totals.json')
    target.parent.mkdir(exist_ok=True)
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(output,allow_nan=False))
    temp.replace(target)
    if all(x['errors'] for x in output['leagues']):
        print('All totals leagues unavailable; see docs/totals.json')

if __name__ == '__main__':
    main()
