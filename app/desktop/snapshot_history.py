"""Capture the closed account store before desktop authentication opens it."""
import json
import shutil
import sys
from pathlib import Path

from oracle.config import load_config
from oracle.data.auth_session import account_directory

root = Path(sys.argv[1])
profile = json.load(sys.stdin)
config = load_config(root/'config/oracle.desktop.yaml')
directory = root/account_directory(config, profile['login'], profile['server'])
target = root/'runtime/desktop/history'/directory.name
target.mkdir(parents=True, exist_ok=True)
try:
    shutil.copyfile(directory/'candles.duckdb', target/'candles.duckdb')
    wal = directory/'candles.duckdb.wal'
    target_wal = target/'candles.duckdb.wal'
    if wal.exists():
        shutil.copyfile(wal, target_wal)
    elif target_wal.exists():
        target_wal.unlink()
    print(json.dumps({'captured': True}))
except OSError:
    print(json.dumps({'captured': False}))
