"""Point d'entrée en ligne de commande du socle."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from observatory.config import Settings, ensure_dotenv
from observatory.db import (
    EXPECTED_ROLES,
    EXPECTED_SCHEMAS,
    connect,
    ingest_can_write,
    list_roles,
    list_schemas,
    missing_names,
)
from observatory.establishments import ESTABLISHMENT_SAMPLE, ingest_establishments
from observatory.municipalities import ingest_population, resolve_population_source

logger = logging.getLogger(__name__)


def _print_catalog(schemas: list[str], roles: list[str]) -> None:
    """Affiche le catalogue, qui est le résultat attendu de ``make up``."""
    print("Schemas:")
    for name in schemas:
        print(f"  {name}")
    print("Roles:")
    for name in roles:
        print(f"  {name}")


def cmd_check(settings: Settings) -> int:
    """Affiche les schémas et les rôles, et échoue s'il en manque un.

    Parameters
    ----------
    settings :
        Connexion administrateur.

    Returns
    -------
    int
        0 si le socle est complet, 1 sinon.
    """
    settings.require("postgres_password")
    with connect(settings) as connection:
        schemas = list_schemas(connection)
        roles = list_roles(connection)
    _print_catalog(schemas, roles)
    absent_schemas = missing_names(schemas, EXPECTED_SCHEMAS)
    absent_roles = missing_names(roles, EXPECTED_ROLES)
    if absent_schemas or absent_roles:
        print(f"Missing schemas: {', '.join(absent_schemas) or '-'}")
        print(f"Missing roles: {', '.join(absent_roles) or '-'}")
        return 1
    return 0


def cmd_ingest(settings: Settings) -> int:
    """Charge la population communale puis les établissements synthétiques.

    Parameters
    ----------
    settings :
        Mot de passe du rôle ``ingest_rw``.

    Returns
    -------
    int
        0 si les communes et les établissements sont chargés, 1 sinon.
    """
    settings.require("ingest_password")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        source = resolve_population_source()
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    with connect(
        settings,
        user=settings.ingest_user,
        password=settings.ingest_password,
    ) as connection:
        if not ingest_can_write(connection):
            logger.error("ingest_rw cannot create objects in raw and ops")
            return 1
        result = ingest_population(connection, source)
        if result.loaded == 0:
            logger.error("no municipality was loaded")
            return 1
        if not ESTABLISHMENT_SAMPLE.exists():
            logger.error("missing sample %s", ESTABLISHMENT_SAMPLE.as_posix())
            return 1
        establishments = ingest_establishments(connection, ESTABLISHMENT_SAMPLE)
    logger.info(
        "loaded %s municipalities, rejected %s lines, source %s",
        result.loaded,
        result.rejected,
        result.source.as_posix(),
    )
    logger.info(
        "loaded %s establishments, rejected %s lines, source %s",
        establishments.loaded,
        establishments.rejected,
        establishments.source.as_posix(),
    )
    if establishments.loaded == 0:
        logger.error("no establishment was loaded")
        return 1
    return 0


def cmd_build() -> int:
    """Lance ``dbt build`` avec les variables déjà chargées depuis `.env`.

    Returns
    -------
    int
        Code de retour de dbt.
    """
    ensure_dotenv()
    dbt_name = "dbt.exe" if sys.platform == "win32" else "dbt"
    dbt_exe = Path(sys.executable).with_name(dbt_name)
    if not dbt_exe.exists():
        raise SystemExit('dbt is not installed. Run: pip install -e ".[dev]"')
    completed = subprocess.run(
        [
            str(dbt_exe),
            "build",
            "--project-dir",
            "dbt",
            "--profiles-dir",
            "dbt",
        ],
        check=False,
    )
    return completed.returncode


def main() -> None:
    """Point d'entrée principal du CLI."""
    parser = argparse.ArgumentParser(
        description="Territorial observatory — database foundation"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ensure-env", help="Create .env from .env.example when missing")
    sub.add_parser("check", help="List schemas and roles")
    sub.add_parser("ingest", help="Check that ingest_rw can write raw and ops")
    sub.add_parser("build", help="Run dbt build")
    args = parser.parse_args()

    if args.command == "ensure-env":
        ensure_dotenv()
        return
    if args.command == "build":
        raise SystemExit(cmd_build())

    settings = Settings.from_env()
    if args.command == "check":
        raise SystemExit(cmd_check(settings))
    if args.command == "ingest":
        raise SystemExit(cmd_ingest(settings))


if __name__ == "__main__":
    main()
