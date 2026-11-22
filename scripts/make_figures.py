"""Écrit les PNG de ``pictures/presentations`` depuis les marts."""

from __future__ import annotations

from observatory.config import Settings
from observatory.db import connect
from observatory.figures import write_figures


def main() -> int:
    """Dessine les graphiques. 1 si la base est injoignable."""
    settings = Settings.from_env()
    settings.require("postgres_password")
    with connect(settings) as connection:
        written = write_figures(connection)
    for path in written:
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
