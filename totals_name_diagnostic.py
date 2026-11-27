"""Read-only: list teams in docs/totals.json that do not match ESPN names."""
import difflib
import json
import os
from collections import Counter
from pathlib import Path
import totals_pipeline as tp

ROUTES = {'NCAAB': 'basketball/mens-college-basketball', 'NCAAF': 'football/college-football'}


def espn_names(route):
    data = tp.get('https://site.api.espn.com/apis/site/v2/sports/' + route + '/teams', limit=1000)
    names = []
    for sport in data.get('sports', []):
        for league in sport.get('leagues', []):
            for item in league.get('teams', []):
                names.append(item['team']['displayName'])
    return names


def main():
    totals = json.loads(Path('docs/totals.json').read_text())
    lines = []
    for league in totals['leagues']:
        route = ROUTES.get(league['league'])
        if not route:
            continue
        index = tp.team_index(route)
        names = espn_names(route)
        by_key = {tp.key(n): n for n in names}
        games = league['games']
        status = Counter(g['model_status'] for g in games)
        missing = sorted({t for g in games for t in (g['home'], g['away']) if tp.key(t) not in index})
        lines.append('## %s: %d games, %d ESPN teams, %d unmatched names' % (league['league'], len(games), len(names), len(missing)))
        for text, count in status.most_common():
            lines.append('- %s: %d' % (text, count))
        for team in missing:
            close = difflib.get_close_matches(tp.key(team), list(by_key), n=2, cutoff=0.6)
            ambiguous = tp.key(team) in by_key
            hint = ', '.join(by_key[c] for c in close) or 'no close ESPN name'
            lines.append('- UNMATCHED %r%s -> closest ESPN: %s' % (team, ' (ambiguous alias)' if ambiguous else '', hint))
    report = '\n'.join(lines)
    print(report)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as f:
            f.write(report + '\n')


if __name__ == '__main__':
    main()
