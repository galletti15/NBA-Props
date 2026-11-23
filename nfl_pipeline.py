"""Experimental NFL baseline. No injury, weather or matchup adjustments yet."""
import json, os, re, unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import requests
import nflreadpy as nfl
from scipy.stats import norm, poisson

MARKETS = {
    'player_pass_yds': ('PASS YDS', 'passing_yards'),
    'player_pass_attempts': ('PASS ATT', 'attempts'),
    'player_pass_completions': ('PASS CMP', 'completions'),
    'player_pass_tds': ('PASS TD', 'passing_tds'),
    'player_pass_interceptions': ('INT', 'passing_interceptions'),
    'player_rush_yds': ('RUSH YDS', 'rushing_yards'),
    'player_rush_attempts': ('RUSH ATT', 'carries'),
    'player_reception_yds': ('REC YDS', 'receiving_yards'),
    'player_receptions': ('REC', 'receptions'),
}
BASE = 'https://api.the-odds-api.com/v4/sports/americanfootball_nfl'

def name(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z]', '', re.sub(r'\b(jr|sr|ii|iii|iv)\b', '', s))

def request(path, **params):
    r = requests.get(BASE + path, params={'apiKey': os.environ['ODDS_API_KEY'], **params}, timeout=45)
    r.raise_for_status()
    remaining = r.headers.get('x-requests-remaining')
    if remaining is not None and float(remaining) < 100:
        raise RuntimeError('Odds credits below NFL safety reserve (100); NBA may also consume credits.')
    return r.json()

def forecast(g, col, season):
    x = g[col].fillna(0).astype(float).to_numpy()
    w = np.where(g['season'].to_numpy() == season, 1.0, 0.45)
    w *= np.power(0.92, np.arange(len(x))[::-1])
    mu = float(np.average(x, weights=w))
    sd = max(float(np.sqrt(np.average((x-mu)**2, weights=w))), abs(mu)*0.25, 1.0)
    return mu, sd

def main():
    now = datetime.now(timezone.utc)
    events = request('/events')
    events = [e for e in events if now < datetime.fromisoformat(e['commence_time'].replace('Z','+00:00')) < now+timedelta(hours=48)]
    rows = []
    skipped = 0
    if events:
        season = now.year if now.month >= 8 else now.year-1
        g = nfl.load_player_stats([season-1, season]).to_pandas()
        if 'recent_team' not in g.columns and 'team' in g.columns:
            g = g.rename(columns={'team': 'recent_team'})
        required = {'season','week','player_id','player_display_name','recent_team'} | {v[1] for v in MARKETS.values()}
        if not required.issubset(g.columns):
            raise RuntimeError('Unexpected nflverse columns: '+str(sorted(required-set(g.columns))))
        if 'season_type' in g.columns:
            g = g[g.season_type == 'REG']
        g = g.sort_values(['season','week'])
        g['match_name'] = g.player_display_name.map(name)
        groups = {k:v for k,v in g.groupby('match_name') if v.player_id.nunique()==1}
        for event in events:
            data = request('/events/'+event['id']+'/odds', regions='us', markets=','.join(MARKETS), oddsFormat='decimal')
            pairs = {}
            for book in data.get('bookmakers',[]):
                for market in book.get('markets',[]):
                    for out in market.get('outcomes',[]):
                        if out.get('name') not in ('Over','Under') or out.get('point') is None:
                            continue
                        key = (out.get('description',''),market['key'],float(out['point']))
                        sides = pairs.setdefault(key,{}).setdefault(book['key'],{})
                        sides[out['name']] = float(out['price'])
            for (player, market, line), books in pairs.items():
                h = groups.get(name(player))
                if h is None or len(h) < 4:
                    skipped += 1
                    continue
                h = h.tail(20)
                label, col = MARKETS[market]
                mu, sd = forecast(h,col,season)
                if 'YDS' in label:
                    po = float(norm.sf(line,loc=mu,scale=sd))
                    pu = 1-po
                else:
                    po = float(poisson.sf(np.floor(line),mu))
                    pu = float(poisson.cdf(np.ceil(line)-1,mu))
                if po+pu <= 0:
                    continue
                po /= po+pu
                fair = []
                for b in books.values():
                    if b.get('Over',0)>1 and b.get('Under',0)>1:
                        a,c = 1/b['Over'],1/b['Under']
                        fair.append(a/(a+c))
                if not fair:
                    continue
                mp = float(np.mean(fair))
                edge = po-mp
                over = max((b['Over'] for b in books.values() if 'Over' in b),default=None)
                under = max((b['Under'] for b in books.values() if 'Under' in b),default=None)
                rows.append(dict(player=player,team=str(h.iloc[-1].recent_team),opp=event['away_team']+' at '+event['home_team'],market=label,line=line,proj=round(mu,1),p_over=po,mkt_p_over=mp,edge=edge,pick='OVER' if edge>=0 else 'UNDER',best_over=over,best_under=under,status='Injury status NOT connected',sample=len(h),start=event['commence_time']))
    rows.sort(key=lambda r:abs(r['edge']),reverse=True)
    payload = dict(updated=now.isoformat(),props=rows,message='Experimental historical baseline; not backtested. No injury, weather, matchup or role-change adjustments. Probabilities are conditional on playing. Decimal odds. Next 48 hours only.',skipped=skipped)
    target=Path('docs/nfl.json')
    target.parent.mkdir(exist_ok=True)
    temp=target.with_suffix('.tmp')
    temp.write_text(json.dumps(payload,allow_nan=False))
    temp.replace(target)

if __name__ == '__main__':
    main()
