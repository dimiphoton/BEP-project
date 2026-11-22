"""Point d'entrée en ligne de commande du socle."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

import psycopg

from observatory.config import Settings, ensure_dotenv
from observatory.contracts import (
    EVAL_SOURCE_NAME as CONTRACT_EVAL_SOURCE,
)
from observatory.contracts import (
    SAMPLE_PATH as CONTRACT_SAMPLE,
)
from observatory.contracts import (
    SOURCE_NAME as CONTRACT_SOURCE,
)
from observatory.contracts import (
    evaluate_contracts,
    ingest_contracts,
    log_contract_calls,
)
from observatory.db import (
    EXPECTED_ROLES,
    EXPECTED_SCHEMAS,
    connect,
    ingest_can_write,
    list_roles,
    list_schemas,
    missing_names,
)
from observatory.establishments import (
    ESTABLISHMENT_SAMPLE,
    ingest_establishments,
)
from observatory.establishments import (
    SOURCE_NAME as ESTABLISHMENT_SOURCE,
)
from observatory.municipalities import (
    SOURCE_NAME as MUNICIPALITY_SOURCE,
)
from observatory.municipalities import (
    ingest_population,
    resolve_population_source,
)
from observatory.nace import (
    EVAL_SOURCE_NAME,
    LiveProviderNotConfigured,
    classify_loaded_enterprises,
    evaluate_gold,
    log_ai_calls,
)
from observatory.nace import (
    SOURCE_NAME as NACE_SOURCE,
)
from observatory.runs import finish_run, start_run

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
    """Charge communes et établissements, puis classe les codes NACE.

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
        population_run = start_run(connection, MUNICIPALITY_SOURCE)
        try:
            result = ingest_population(connection, source)
        except (psycopg.Error, OSError, ValueError) as exc:
            # On ferme le passage avant de sortir, sinon il resterait « running ».
            logger.error("%s", exc)
            finish_run(
                connection,
                population_run,
                rows_read=None,
                rows_rejected=None,
                status="failed",
            )
            return 1
        population_status = "success" if result.loaded > 0 else "failed"
        finish_run(
            connection,
            population_run,
            rows_read=result.loaded + result.rejected,
            rows_rejected=result.rejected,
            status=population_status,
        )
        if result.loaded == 0:
            logger.error("no municipality was loaded")
            return 1
        establishment_run = start_run(connection, ESTABLISHMENT_SOURCE)
        if not ESTABLISHMENT_SAMPLE.exists():
            logger.error("missing sample %s", ESTABLISHMENT_SAMPLE.as_posix())
            finish_run(
                connection,
                establishment_run,
                rows_read=None,
                rows_rejected=None,
                status="failed",
            )
            return 1
        try:
            establishments = ingest_establishments(connection, ESTABLISHMENT_SAMPLE)
        except (psycopg.Error, OSError, ValueError) as exc:
            logger.error("%s", exc)
            finish_run(
                connection,
                establishment_run,
                rows_read=None,
                rows_rejected=None,
                status="failed",
            )
            return 1
        establishment_status = "success" if establishments.loaded > 0 else "failed"
        finish_run(
            connection,
            establishment_run,
            rows_read=establishments.loaded + establishments.rejected,
            rows_rejected=establishments.rejected,
            status=establishment_status,
        )
        nace_run = start_run(connection, NACE_SOURCE)
        try:
            classified = classify_loaded_enterprises(
                connection,
                mode=settings.ai_mode,
                threshold=settings.ai_confidence_threshold,
            )
        except (LiveProviderNotConfigured, FileNotFoundError, ValueError) as exc:
            logger.error("%s", exc)
            finish_run(
                connection,
                nace_run,
                rows_read=None,
                rows_rejected=None,
                status="failed",
            )
            return 1
        nace_status = "success" if classified.codes > 0 else "failed"
        # La revue n'est pas un rejet : le volume suivi est le nombre de codes.
        finish_run(
            connection,
            nace_run,
            rows_read=classified.codes,
            rows_rejected=0,
            status=nace_status,
        )
        contract_run = start_run(connection, CONTRACT_SOURCE)
        if not CONTRACT_SAMPLE.exists():
            logger.error("missing sample %s", CONTRACT_SAMPLE.as_posix())
            finish_run(
                connection,
                contract_run,
                rows_read=None,
                rows_rejected=None,
                status="failed",
            )
            return 1
        try:
            loaded, rejected, review = ingest_contracts(
                connection,
                CONTRACT_SAMPLE,
                mode=settings.ai_mode,
                threshold=settings.ai_confidence_threshold,
            )
        except (
            LiveProviderNotConfigured,
            FileNotFoundError,
            ValueError,
            psycopg.Error,
        ) as exc:
            logger.error("%s", exc)
            finish_run(
                connection,
                contract_run,
                rows_read=None,
                rows_rejected=None,
                status="failed",
            )
            return 1
        contract_status = "success" if loaded > 0 else "failed"
        # La revue n'est pas un rejet : seules les extractions invalides le sont.
        finish_run(
            connection,
            contract_run,
            rows_read=loaded + rejected + review,
            rows_rejected=rejected,
            status=contract_status,
        )
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
    logger.info(
        "classified %s nace codes, %s by rule, %s by ai, %s to review",
        classified.codes,
        classified.by_rule,
        classified.by_ai,
        classified.to_review,
    )
    if classified.codes == 0:
        logger.error("no nace code was classified")
        return 1
    logger.info(
        "loaded %s public contracts, rejected %s lines, %s to review",
        loaded,
        rejected,
        review,
    )
    if loaded == 0:
        logger.error("no public contract was loaded")
        return 1
    return 0


def cmd_eval_nace(settings: Settings) -> int:
    """Mesure l'accord du classeur avec le fichier d'évaluation.

    Parameters
    ----------
    settings :
        Mode d'IA, seuil, et mot de passe de ``ingest_rw`` pour le journal.

    Returns
    -------
    int
        0 si le score est calculé et les appels sont journalisés, 1 sinon.
    """
    settings.require("ingest_password")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        result = evaluate_gold(
            mode=settings.ai_mode,
            threshold=settings.ai_confidence_threshold,
        )
    except (LiveProviderNotConfigured, FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1
    if result.scored == 0:
        logger.error("gold file has no row")
        return 1
    print(
        f"nace agreement {result.agreement:.4f} "
        f"({result.agreed}/{result.scored}); "
        f"unverified labels {result.unverified}; "
        f"below threshold {result.below_threshold}",
        flush=True,
    )
    try:
        with connect(
            settings,
            user=settings.ingest_user,
            password=settings.ingest_password,
        ) as connection:
            logged = log_ai_calls(
                connection,
                result.predictions,
                source_name=EVAL_SOURCE_NAME,
            )
    except psycopg.Error as exc:
        logger.error("ai_log not written: %s", exc)
        return 1
    logger.info("appended %s ai calls to ops.ai_log", logged)
    return 0


def cmd_eval_contracts(settings: Settings) -> int:
    """Mesure l'exactitude de chaque champ extrait des avis.

    Parameters
    ----------
    settings :
        Mode d'IA, seuil, et mot de passe de ``ingest_rw`` pour le journal.

    Returns
    -------
    int
        0 si le score est calculé, 1 sinon.
    """
    settings.require("ingest_password")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        result = evaluate_contracts(
            mode=settings.ai_mode,
            threshold=settings.ai_confidence_threshold,
        )
    except (LiveProviderNotConfigured, FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1
    if result.scored == 0:
        logger.error("gold file has no field")
        return 1
    print(
        f"contract field accuracy {result.accuracy:.4f} "
        f"({result.matched}/{result.scored}); "
        f"unverified labels {result.unverified}; "
        f"below threshold {result.below_threshold}",
        flush=True,
    )
    try:
        with connect(
            settings,
            user=settings.ingest_user,
            password=settings.ingest_password,
        ) as connection:
            logged = log_contract_calls(
                connection,
                result.calls,
                source_name=CONTRACT_EVAL_SOURCE,
            )
    except psycopg.Error as exc:
        logger.error("ai_log not written: %s", exc)
        return 1
    logger.info("appended %s ai calls to ops.ai_log", logged)
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
    sub.add_parser("ingest", help="Load sources and classify NACE families")
    sub.add_parser("build", help="Run dbt build")
    sub.add_parser("eval-nace", help="Score NACE families against the gold file")
    sub.add_parser("eval-contracts", help="Score contract fields against the gold file")
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
    if args.command == "eval-nace":
        raise SystemExit(cmd_eval_nace(settings))
    if args.command == "eval-contracts":
        raise SystemExit(cmd_eval_contracts(settings))


if __name__ == "__main__":
    main()
