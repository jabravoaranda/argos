from __future__ import annotations

import json
import os
from pathlib import Path


os.environ.setdefault("ARGOS_ADMIN_TOKEN", "openapi-export-placeholder")
os.environ.setdefault("ECOWITT_INGEST_TOKEN", "openapi-export-placeholder")
os.environ.setdefault("ARGOS_DAILY_SYNC_ENABLED", "false")

from argos.main import create_app  # noqa: E402


def main() -> None:
    destination = Path("openapi.json")
    destination.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(destination.resolve())


if __name__ == "__main__":
    main()
