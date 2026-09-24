"""Deterministic retention rehearsal, explicitly synthetic and never live evidence."""

import argparse
import json
import math
from pathlib import Path

from oracle.director.director import Director
from oracle.director.timeline import Timeline, retention_report
from oracle.models import Bar


def replay(seconds: int = 3600) -> dict[str, object]:
    timeline = Timeline()
    director = Director(timeline)
    director.rehearsal = True
    base = 1789680000000
    frames = []
    previous = base
    events = {
        10: ("Amina💛", "Watching gold"),
        20: ("HaddanFx", "Following the chart"),
        30: ("Sara", "What is gold's price?"),
        75: ("HaddanFx", "!score"),
        110: ("مرحبا_ذهب", "!levels"),
    }
    for second in range(seconds + 1):
        now = base + second * 1000
        bucket = now // 60000 * 60000
        price = 4346 + math.sin(second / 31) * 4 + second / 300
        bar = Bar(
            symbol="XAUUSD",
            tf="M1",
            t_open_ms=bucket,
            o=4346,
            h=max(4352, price),
            l=min(4340, price),
            c=price,
            tick_volume=417,
            source="synthetic",
            complete=False,
            digits=3,
        )
        closed = (
            [
                Bar.model_validate(
                    bar.model_dump(exclude={"id", "object_hash"})
                    | {"t_open_ms": previous, "complete": True}
                )
            ]
            if bucket != previous
            else []
        )
        director.observe(bar, closed, now)
        if second in events:
            name, text = events[second]
            director.ingest("comment", name, text, now, event_id=f"rehearsal-{second}")
        if second == 90:
            director.ingest("gift", "Supporter", "", now, event_id="gift")
        if second % 10 == 0:
            director.ingest("viewers", "", "", now, viewer_count=100 + second // 60)
        frames.append(director.view(now).model_dump(mode="json"))
        previous = bucket
    director.close(base + seconds * 1000)
    return {
        "provenance": "SYNTHETIC RETENTION REHEARSAL — NOT A LIVE STREAM",
        "frames": frames,
        "timeline": timeline.rows,
        "report": retention_report(timeline.rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--seconds", type=int, default=3600)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(replay(args.seconds), ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
