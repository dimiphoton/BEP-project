"""Contrôle des sources : dernier passage, âge, et chute de volume.

Une source est périmée quand son dernier succès a plus de
``HEALTHCHECK_MAX_AGE_DAYS`` jours (7 par défaut). La chute de volume
est stricte : garder exactement la moitié du passage précédent passe
encore, garder moins échoue.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import psycopg

from observatory.config import Settings, ensure_dotenv
from observatory.contracts import SOURCE_NAME as CONTRACT_SOURCE
from observatory.db import PgConnection, connect
from observatory.entities import SOURCE_NAME as ENTITY_SOURCE
from observatory.establishments import SOURCE_NAME as ESTABLISHMENT_SOURCE
from observatory.municipalities import SOURCE_NAME as MUNICIPALITY_SOURCE
from observatory.nace import SOURCE_NAME as NACE_SOURCE
from observatory.runs import RunRecord, latest_runs

MONITORED_SOURCES = (
    MUNICIPALITY_SOURCE,
    ESTABLISHMENT_SOURCE,
    NACE_SOURCE,
    CONTRACT_SOURCE,
    ENTITY_SOURCE,
)
DEFAULT_MAX_AGE_DAYS = 7
# Moins de la moitié du volume précédent : la chute dépasse 50 %.
VOLUME_FLOOR = 0.5


def max_age_from_env() -> timedelta:
    """Lit le nombre de jours avant qu'une source soit périmée.

    Returns
    -------
    timedelta
        Durée positive.

    Raises
    ------
    SystemExit
        La variable n'est pas un entier strictement positif.
    """
    raw = os.environ.get("HEALTHCHECK_MAX_AGE_DAYS", str(DEFAULT_MAX_AGE_DAYS))
    try:
        days = int(raw)
    except ValueError as exc:
        raise SystemExit(
            f"HEALTHCHECK_MAX_AGE_DAYS is not an integer ({raw})."
        ) from exc
    if days <= 0:
        raise SystemExit("HEALTHCHECK_MAX_AGE_DAYS must be greater than 0.")
    return timedelta(days=days)


def problems(
    runs: dict[str, list[RunRecord]],
    *,
    required: tuple[str, ...],
    now: datetime,
    max_age: timedelta,
) -> list[str]:
    """Liste ce qui empêche de considérer les sources comme saines.

    Parameters
    ----------
    runs :
        Passages par source, du plus récent au plus ancien.
    required :
        Sources qui doivent avoir un succès récent.
    now :
        Instant de la comparaison, conscient du fuseau.
    max_age :
        Âge au-delà duquel le dernier succès est périmé.

    Returns
    -------
    list[str]
        Messages vides si tout va bien, dans l'ordre de ``required``.
    """
    found: list[str] = []
    for name in required:
        history = runs.get(name, [])
        if not history:
            found.append(f"source {name} has no run")
            continue
        latest = history[0]
        if latest.status != "success":
            found.append(f"source {name} last run is {latest.status}")
            continue
        if latest.finished_at is None or now - latest.finished_at > max_age:
            when = (
                "no end time"
                if latest.finished_at is None
                else latest.finished_at.date().isoformat()
            )
            found.append(f"source {name} is stale (last success {when})")
        drop = _volume_drop(history)
        if drop is not None:
            previous, current = drop
            found.append(f"source {name} volume dropped from {previous} to {current}")
    return found


def collect_problems(
    connection: PgConnection,
    *,
    required: tuple[str, ...] = MONITORED_SOURCES,
    now: datetime | None = None,
    max_age: timedelta | None = None,
) -> list[str]:
    """Lit le journal et applique les règles de fraîcheur et de volume.

    Parameters
    ----------
    connection :
        Connexion ouverte avec ``ingest_rw``.
    required :
        Sources attendues. Par défaut, les trois étapes de ``make ingest``.
    now :
        Instant de comparaison. Par défaut, maintenant en UTC.
    max_age :
        Âge maximum d'un succès. Par défaut, la variable d'environnement.

    Returns
    -------
    list[str]
        Problèmes, ou une liste vide.
    """
    moment = now or datetime.now(UTC)
    window = max_age if max_age is not None else max_age_from_env()
    loaded = latest_runs(connection, required)
    return problems(loaded, required=required, now=moment, max_age=window)


def main() -> int:
    """Affiche ``ok`` ou les sources en échec.

    Returns
    -------
    int
        0 si les sources suivies sont fraîches et stables, 1 sinon.
    """
    ensure_dotenv()
    settings = Settings.from_env()
    settings.require("ingest_password")
    try:
        window = max_age_from_env()
        with connect(
            settings,
            user=settings.ingest_user,
            password=settings.ingest_password,
        ) as connection:
            found = collect_problems(connection, max_age=window)
    except psycopg.OperationalError as exc:
        print(f"postgres unavailable: {exc}")
        return 1
    if found:
        for line in found:
            print(line)
        return 1
    print("ok")
    return 0


def _volume_drop(history: list[RunRecord]) -> tuple[int, int] | None:
    """Deux derniers succès : (précédent, courant) si la chute dépasse 50 %."""
    successes = [item for item in history if item.status == "success"]
    if len(successes) < 2:
        return None
    current = _kept(successes[0])
    previous = _kept(successes[1])
    if current is None or previous is None or previous == 0:
        return None
    if current < previous * VOLUME_FLOOR:
        return previous, current
    return None


def _kept(run: RunRecord) -> int | None:
    """Lignes gardées : lues moins refusées."""
    if run.rows_read is None or run.rows_rejected is None:
        return None
    return run.rows_read - run.rows_rejected
