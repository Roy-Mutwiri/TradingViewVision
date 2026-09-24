"""Local read-only phase-0 dashboard shell. Manual controls belong to phase 9."""

from collections import deque
from pathlib import Path
from typing import Callable

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from oracle.auth.contracts import OperatorAccount
from oracle.config import OracleConfig
from oracle.models import WireEvent


def create_dashboard(
    config: OracleConfig,
    strings_dir: Path,
    account_provider: Callable[[], OperatorAccount | None] | None = None,
    frame_provider: Callable[[], dict[str, object] | None] | None = None,
) -> FastAPI:
    raw = yaml.safe_load((strings_dir / f"{config.language}.yaml").read_text(encoding="utf-8"))
    app = FastAPI(title="ORACLE STUDIO", docs_url=None, redoc_url=None)
    events: deque[WireEvent] = deque(maxlen=100)
    app.state.events = events

    @app.get("/account")
    async def account() -> dict[str, object]:
        info = account_provider() if account_provider else None
        if info is None:
            raise HTTPException(status_code=401, detail="Authenticate in the desktop login gate")
        return info.model_dump(mode="json", by_alias=True)

    @app.get("/state")
    async def state() -> dict[str, object]:
        """The newest speaker frame (docs/ORACLE_BRIDGE.md §2).

        Read-only, loopback-bound, and only so the speaker has current state at startup instead of standing mute
        until the next frame lands. The JSONL sink remains the live channel; this is not polled in normal running.
        """
        frame = frame_provider() if frame_provider else None
        if frame is None:
            raise HTTPException(status_code=503, detail="No speaker frame yet; the sink may be disabled")
        return frame

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "skeleton", "phase_gate": "pending"}

    @app.get("/events")
    async def recent_events() -> list[dict[str, object]]:
        return [event.model_dump(mode="json") for event in events]

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        import html

        direction = "rtl" if config.language == "ar" else "ltr"
        title = html.escape(str(raw["app.title"]))
        status = html.escape(str(raw["status.skeleton"]))
        return f'<html lang="{config.language}" dir="{direction}"><title>{title}</title><h1>{title}</h1><p>{status}</p></html>'

    return app
