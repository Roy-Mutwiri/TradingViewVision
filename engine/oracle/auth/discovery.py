"""Best-effort local terminal discovery; binary server scans never fail startup."""

import os
import re
from pathlib import Path

import yaml

SERVER = re.compile(r"^[A-Za-z]+-(?:MT5)?(?:Real|Trial)\d*$", re.IGNORECASE)


def extract_servers(blob: bytes) -> list[str]:
    result = set()
    for offset in (0, 1):
        text = blob[offset:].decode("utf-16-le", errors="ignore")
        for value in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,127}", text):
            if SERVER.fullmatch(value):
                result.add(value)
    return sorted(result)


def discover_servers(appdata: Path | None = None) -> list[str]:
    root = appdata or Path(os.environ.get("APPDATA", ""))
    found = set()
    if not str(root) or root == Path("."):
        return []
    for folder in (root / "MetaQuotes/Terminal").glob("*/config"):
        try:
            for path in folder.iterdir():
                if path.is_file() and path.stat().st_size <= 16 * 1024 * 1024:
                    try:
                        found.update(extract_servers(path.read_bytes()))
                    except OSError:
                        pass
        except OSError:
            pass
    return sorted(found)


def server_choices(seed_path: Path, profiles: list[str]) -> list[str]:
    try:
        seed = yaml.safe_load(seed_path.read_text(encoding="utf-8")) or {}
        seeded = [s for s in seed.get("servers", []) if isinstance(s, str)]
    except (OSError, yaml.YAMLError):
        seeded = []
    return list(dict.fromkeys([*profiles, *discover_servers(), *seeded]))


def locate_terminal(preferred: str | None) -> Path | None:
    if preferred:
        path = Path(preferred)
        return (
            path
            if path.is_file() and path.name.lower() in ("terminal64.exe", "terminal.exe")
            else None
        )
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        root = Path(os.environ.get(env, "C:/Program Files"))
        for folder in ("MetaTrader 5 EXNESS", "MetaTrader 5", "Exness MetaTrader 5"):
            path = root / folder / "terminal64.exe"
            if path.is_file():
                return path
    return None
