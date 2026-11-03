"""Write the API's OpenAPI schema to the frontend, which generates typed clients from it.

Usage (from backend/): uv run python scripts/export_openapi.py
CI fails if the committed schema is out of date.
"""

import json
from pathlib import Path

from legalos.main import create_app

OUTPUT = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "api" / "openapi.json"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    schema = create_app().openapi()
    OUTPUT.write_text(json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
