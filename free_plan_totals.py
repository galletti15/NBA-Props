"""Daily, cached game-total odds for the free plan. No team-total requests."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
import totals_pipeline as totals

STATE = Path('data/free-plan-totals.json')
OUT = Path('docs/totals.json')
RESERVE = 25
NOTE = ('FREE PLAN: game-total odds fetched at most once per league per UTC day. '
        'Sportsbook team-total requests disabled; team-score projections remain available when history matches. '
        'NBA/NFL player-prop automatic refreshes are paused; manual runs still spend credits. '
        'Experimental recent-score model, not backtested; no pace, injury, weather or schedule-strength adjustments. '
        'NBA/NFL: up to 8 games in the next 7 days. NCAAF: all games in the next 7 days. NCAAB: all games in the next 24 hours. Decimal odds. '
        'Cached odds retain sportsbook timestamps and may be stale. '
        'A 25-credit reserve pauses further requests after a low balance is reported.')

def load(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, allow_nan=False))
    temp.replace(path)

def cached_odds(state, sport, path, params, fetch, today):
    if params.get('markets') == 'team_totals':
        return {'bookmakers': []}
    if path != '/odds' or params.get('markets') != 'totals':
        raise RuntimeError('Free-plan mode allows only game-total odds')
    entries = state.setdefault('leagues', {})
    entry = entries.setdefault(sport, {})
    if entry.get('attempt_day') == today:
        if entry.get('data_day') == today:
            return copy.deepcopy(entry['data'])
        raise RuntimeError('Already attempted today; cached data retained. '+entry.get('error',''))
    if state.get('balance_day') == today and state.get('remaining', RESERVE+1) <= RESERVE:
        raise RuntimeError('Free-plan odds paused at the 25-credit reserve')
    entry['attempt_day'] = today
    try:
        data, remaining = fetch(sport, path, params)
        if not isinstance(data, list):
            raise RuntimeError('Unexpected game-odds response')
        entry.update(data=data, data_day=today)
        entry.pop('error', None)
        if remaining is not None:
            state.update(remaining=remaining, balance_day=today)
        return copy.deepcopy(data)
    except Exception as exc:
        entry['error'] = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        raise RuntimeError(entry['error']) from None

def fetch(sport, path, params):
    import os
    r = totals.requests.get('https://api.the-odds-api.com/v4/sports/'+sport+path,
        params=dict(apiKey=os.environ['ODDS_API_KEY'], regions='us', oddsFormat='decimal', **params), timeout=30)
    if not r.ok:
        raise RuntimeError('Odds provider HTTP '+str(r.status_code))
    balance = r.headers.get('x-requests-remaining')
    return r.json(), float(balance) if balance is not None else None

def main():
    state = load(STATE, {})
    previous = {x['league']: x for x in load(OUT, {'leagues':[]}).get('leagues',[])}
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    totals.NOW = now
    totals.CACHE.clear()
    totals.odds = lambda sport,path,**params: cached_odds(state,sport,path,params,fetch,today)
    original_index = totals.team_index
    def safe_index(route):
        try:
            return original_index(route)
        except Exception as exc:
            print('ESPN team index unavailable:', route, type(exc).__name__)
            return {}
    totals.team_index = safe_index
    leagues = []
    for label, config in totals.SPORTS.items():
        try:
            result = totals.build_league(label, config)
            for g in result['games']:
                g['team_odds_status'] = 'Sportsbook team-total requests disabled in free-plan mode'
        except Exception as exc:
            result = copy.deepcopy(previous.get(label, dict(league=label,games=[],available_games=None)))
            result['errors'] = ['Refresh unavailable; prior unstarted games retained: '+str(exc)]
            result['games'] = [g for g in result.get('games',[]) if datetime.fromisoformat(g['start'].replace('Z','+00:00'))>now]
            for g in result['games']:
                g['home_quotes'],g['away_quotes'] = [],[]
                g['team_odds_status'] = 'Disabled in free-plan mode; retained projections may be stale'
            result['available_games'] = len(result['games'])
        leagues.append(result)
        write(STATE,state)
    write(OUT,dict(updated=now.isoformat(),note=NOTE,leagues=leagues))

if __name__ == '__main__':
    main()
