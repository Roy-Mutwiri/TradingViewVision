"""Single-source protocol schema exporter; generated TypeScript is never edited."""

import argparse
import json
from pathlib import Path

from oracle import models
from oracle.models import Contract


def export_schema(path: Path) -> None:
    definitions: dict[str, object] = {}
    for name, item in sorted(vars(models).items()):
        if (
            isinstance(item, type)
            and issubclass(item, Contract)
            and item not in (Contract, models.Identified)
        ):
            schema = item.model_json_schema(mode="serialization")
            definitions.update(schema.pop("$defs", {}))
            definitions[name] = schema
    schema_root = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "OracleProtocol",
        "type": "object",
        "additionalProperties": False,
        "properties": {name: {"$ref": f"#/$defs/{name}"} for name in definitions},
        "$defs": definitions,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema_root, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    export_schema(parser.parse_args().output)


if __name__ == "__main__":
    main()
