"""Run the NBA pipeline without publishing empty or failed refreshes."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path('docs/data.json')

def read_snapshot(path):
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or not isinstance(value.get('props'), list):
            return None
        return value
    except (OSError, ValueError):
        return None

def usable(value):
    return bool(value and value.get('props')) and all(
        isinstance(row, dict) and {'player','market','line','proj'} <= row.keys()
        for row in value['props'])

def atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.guard.tmp')
    temp.write_text(json.dumps(value, allow_nan=False))
    temp.replace(path)

def finish(previous, target, returncode, attempted):
    current = read_snapshot(target)
    if returncode == 0 and usable(current):
        print('NBA refresh accepted:', len(current['props']), 'props')
        return True
    if not usable(previous):
        raise RuntimeError('NBA refresh failed or produced no usable props; no valid saved snapshot available. Publishing blocked.')
    retained = dict(previous)
    retained['stale'] = True
    retained['last_refresh_attempt'] = attempted
    retained['refresh_status'] = 'retained_previous'
    retained['refresh_error'] = ('NBA pipeline exited with code '+str(returncode)) if returncode else 'NBA pipeline produced empty or invalid props data'
    warning = ('STALE SAVED DATA: Latest NBA refresh failed or returned no usable props. '
               'Previous props and their original update time have been retained. '
               'These are not live lines; games may have started or finished. '
               'Check current lines and player status before use.')
    retained['message'] = warning
    atomic_write(target, retained)
    print('::warning::'+retained['refresh_error']+'; kept '+str(len(retained['props']))+' saved props')
    return False

def main():
    previous = read_snapshot(TARGET)
    attempted = datetime.now(timezone.utc).isoformat()
    try:
        returncode = subprocess.run([sys.executable, 'pipeline.py'], check=False).returncode
    except OSError:
        returncode = 127
    finish(previous, TARGET, returncode, attempted)

if __name__ == '__main__':
    main()
