"""Append-only stream evidence and retention-by-beat reporting; losses never disappear."""

import argparse
import json
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path
from typing import Any


class Timeline:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.rows: list[dict[str, Any]] = []
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, row: dict[str, Any]) -> None:
        if self.path:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        else:
            self.rows.append(row)


def retention_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    viewers = sorted((int(r["at_ms"]), int(r["count"])) for r in rows if r.get("kind") == "viewers")
    stamps = [t for t, _ in viewers]
    groups: dict[str, list[int]] = defaultdict(list)
    unknown: dict[str, int] = defaultdict(int)
    for row in rows:
        if row.get("kind") != "beat":
            continue
        start, end = int(row["start_ms"]), int(row["end_ms"])
        before, after = bisect_right(stamps, start) - 1, bisect_right(stamps, end) - 1
        if before < 0 or after < 0 or start - stamps[before] > 20000 or end - stamps[after] > 20000:
            unknown[row["type"]] += 1
        else:
            groups[row["type"]].append(viewers[after][1] - viewers[before][1])
    return {
        "viewer_samples": len(viewers),
        "beats": {
            key: {
                "measured": len(groups[key]),
                "unmeasured": unknown[key],
                "average_viewer_delta": sum(groups[key]) / len(groups[key])
                if groups[key]
                else None,
            }
            for key in sorted(set(groups) | set(unknown))
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("timeline", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = [
        json.loads(line) for line in args.timeline.read_text(encoding="utf-8").splitlines() if line
    ]
    report = json.dumps(retention_report(rows), indent=2) + "\n"
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
