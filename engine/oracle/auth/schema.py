"""Private IPC schema generation, separate from the broadcast schema."""

import argparse
import json
from pathlib import Path

from oracle.auth import contracts
from oracle.models import Contract


def export_schema(path: Path) -> None:
    definitions = {}
    for name, value in sorted(vars(contracts).items()):
        if isinstance(value, type) and issubclass(value, Contract) and value is not Contract:
            schema = value.model_json_schema(mode="serialization", by_alias=True)
            definitions.update(schema.pop("$defs", {}))
            definitions[name] = schema
    payload = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "OracleAuth",
        "type": "object",
        "additionalProperties": False,
        "properties": {n: {"$ref": f"#/$defs/{n}"} for n in definitions},
        "$defs": definitions,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    export_schema(parser.parse_args().output)
