"""Écrit ``docs/metrics.json`` à partir de la base, de dbt et de l'évaluation NACE."""

from __future__ import annotations

from observatory.config import Settings
from observatory.db import connect
from observatory.metrics import collect_metrics, write_metrics


def main() -> int:
    """Mesure puis écrit le JSON. 1 si la base est injoignable."""
    settings = Settings.from_env()
    settings.require("postgres_password")
    with connect(settings) as connection:
        payload = collect_metrics(connection)
    write_metrics(payload)
    counts = payload["counts"]
    print(
        "metrics "
        f"municipalities={counts['municipalities']} "
        f"establishments={counts['establishments']} "
        f"enterprises={counts['enterprises']} "
        f"public_contracts={counts['public_contracts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
