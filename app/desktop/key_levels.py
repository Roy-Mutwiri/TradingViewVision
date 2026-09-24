"""Read-only desktop context from a private snapshot of existing M1 history."""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import duckdb
from oracle.config import load_config
from oracle.data.analytical_days import analytical_levels, trading_day, trading_week_bounds
from oracle.data.auth_session import account_directory
from oracle.models import Bar


def key_levels(root, profile, now_ms):
    config = load_config(root/'config/oracle.desktop.yaml')
    identity_directory = account_directory(config, profile['login'], profile['server'])
    source = root/'runtime/desktop/history'/identity_directory.name/'candles.duckdb'
    destination_root = root/'runtime/desktop'
    destination_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination_root) as directory:
        snapshot = Path(directory)/'candles.duckdb'
        for _ in range(3):
            files = [source] + ([Path(str(source)+'.wal')] if Path(str(source)+'.wal').exists() else [])
            before = [(path.stat().st_size, path.stat().st_mtime_ns) for path in files]
            for path in files:
                shutil.copyfile(path, Path(directory)/path.name)
            after = [(path.stat().st_size, path.stat().st_mtime_ns) for path in files]
            if before == after:
                break
        else:
            raise RuntimeError('History is updating; retry next minute')
        with duckdb.connect(str(snapshot)) as db:
            identity = db.execute('SELECT server,login FROM account_identity WHERE broker=?',
                                  [config.data.canonical_broker]).fetchone()
            if identity != (profile['server'], profile['login']):
                raise RuntimeError('History does not belong to the active session')
            rows = db.execute("SELECT payload FROM bars WHERE broker=? AND tf='M1' AND t<? ORDER BY t DESC LIMIT 30000",
                              [config.data.canonical_broker, now_ms]).fetchall()
        bars = [Bar.model_validate_json(row[0]) for row in reversed(rows)]
        bars = [bar for bar in bars if bar.complete and bar.t_open_ms+60000 <= now_ms]
        if not bars or trading_day(bars[-1].t_open_ms, config.sessions.day_boundary) != trading_day(now_ms, config.sessions.day_boundary):
            raise RuntimeError('Current trading-day history is not available in the desktop snapshot')
        levels = analytical_levels(bars, now_ms, config.sessions)
        week_start, week_end = trading_week_bounds(now_ms, config.sessions.day_boundary)
        weekly = next((bar.o for bar in bars if week_start <= bar.t_open_ms < week_end), None)
        return {'pdh': levels.pdh, 'pdl': levels.pdl, 'weekly_open': weekly, 'as_of_ms': now_ms}


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        result = key_levels(Path(sys.argv[1]), request['profile'], request.get('now_ms', int(time.time()*1000)))
    except Exception as error:
        result = {'pdh': None, 'pdl': None, 'weekly_open': None, 'error': str(error)[:180]}
    print(json.dumps(result), flush=True)
