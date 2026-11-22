"""Écrit les PNG de ``pictures/presentations`` depuis les marts."""

from __future__ import annotations

import shutil
from pathlib import Path

from observatory.config import Settings
from observatory.db import connect
from observatory.figures import write_figures

PUBLISHED_DIR = Path("docs/slides-assets")


def main() -> int:
    """Dessine les graphiques. 1 si la base est injoignable."""
    settings = Settings.from_env()
    settings.require("postgres_password")
    with connect(settings) as connection:
        written = write_figures(connection)
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    for path in written:
        shutil.copyfile(path, PUBLISHED_DIR / path.name)
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
