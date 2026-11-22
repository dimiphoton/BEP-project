"""Connexion Postgres et lecture du catalogue (schémas, rôles)."""

from __future__ import annotations

from typing import Any

import psycopg

from observatory.config import Settings

EXPECTED_SCHEMAS = ("marts", "ops", "raw", "staging")
EXPECTED_ROLES = ("dbt_rw", "ingest_rw", "reader_ro")

PgConnection = psycopg.Connection[tuple[Any, ...]]


def connect(
    settings: Settings,
    *,
    user: str | None = None,
    password: str | None = None,
) -> PgConnection:
    """Ouvre une connexion Postgres.

    Parameters
    ----------
    settings :
        Hôte, port et nom de la base.
    user :
        Rôle Postgres. Par défaut, l'administrateur défini dans `.env`.
    password :
        Mot de passe du rôle. Par défaut, celui de l'administrateur.

    Returns
    -------
    PgConnection
        Connexion ouverte. L'appelant la ferme.

    Raises
    ------
    psycopg.OperationalError
        La base est injoignable ou le mot de passe est refusé.
    """
    return psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=user or settings.postgres_user,
        password=settings.postgres_password if password is None else password,
        connect_timeout=10,
    )


def list_schemas(connection: PgConnection) -> list[str]:
    """Liste les schémas applicatifs, hors catalogues système.

    Parameters
    ----------
    connection :
        Connexion ouverte.

    Returns
    -------
    list[str]
        Noms triés.
    """
    rows = connection.execute(
        """
        SELECT nspname
        FROM pg_namespace
        WHERE nspname NOT LIKE 'pg_%'
          AND nspname <> 'information_schema'
        ORDER BY nspname
        """
    ).fetchall()
    return [row[0] for row in rows]


def list_roles(connection: PgConnection) -> list[str]:
    """Liste les rôles qui peuvent ouvrir une session, hors rôles système.

    Parameters
    ----------
    connection :
        Connexion ouverte.

    Returns
    -------
    list[str]
        Noms triés.
    """
    rows = connection.execute(
        """
        SELECT rolname
        FROM pg_roles
        WHERE rolcanlogin
          AND rolname NOT LIKE 'pg_%'
        ORDER BY rolname
        """
    ).fetchall()
    return [row[0] for row in rows]


def missing_names(found: list[str], expected: tuple[str, ...]) -> list[str]:
    """Retourne les noms attendus qui ne sont pas dans la liste trouvée.

    Parameters
    ----------
    found :
        Noms présents dans la base.
    expected :
        Noms exigés par le socle.

    Returns
    -------
    list[str]
        Absents, dans l'ordre de ``expected``.
    """
    found_set = set(found)
    return [name for name in expected if name not in found_set]


def ingest_can_write(connection: PgConnection) -> bool:
    """Indique si le rôle courant peut créer des objets dans raw et ops.

    Parameters
    ----------
    connection :
        Connexion ouverte avec le rôle d'ingestion.

    Returns
    -------
    bool
        True si USAGE et CREATE sont accordés sur les deux schémas.
    """
    row = connection.execute(
        """
        SELECT
          has_schema_privilege(current_user, 'raw', 'USAGE')
          AND has_schema_privilege(current_user, 'raw', 'CREATE')
          AND has_schema_privilege(current_user, 'ops', 'USAGE')
          AND has_schema_privilege(current_user, 'ops', 'CREATE')
        """
    ).fetchone()
    return bool(row and row[0])
