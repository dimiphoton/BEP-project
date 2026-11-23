"""Écrit les PNG de ``pictures/presentations`` : carte, schémas, puis barres des marts."""

from __future__ import annotations

import shutil
from pathlib import Path

from psycopg import Error as PgError

from observatory.config import Settings
from observatory.db import connect
from observatory.figures import write_didactic_figures, write_figures

PUBLISHED_DIR = Path("docs/slides-assets")


def main() -> int:
    """Dessine la carte et les schémas. La base absente n'empêche pas ce dessin."""
    written = write_didactic_figures()
    settings = Settings.from_env()
    try:
        settings.require("postgres_password")
        with connect(settings) as connection:
            written.extend(write_figures(connection))
    except (OSError, PgError) as exc:
        # La base peut être arrêtée : les schémas, eux, sont déjà dessinés.
        print(f"barres des marts non rejouées ({exc})")
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    for path in written:
        shutil.copyfile(path, PUBLISHED_DIR / path.name)
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
