"""Contrats du socle : init SQL, configuration, catalogue Postgres."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

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

INIT_SCRIPT = Path("db/init/01_schemas_and_roles.sh")
ENV_EXAMPLE = Path(".env.example")


def test_init_script_declares_schemas_and_roles() -> None:
    """Le script d'init crée les quatre schémas et les trois rôles."""
    script = INIT_SCRIPT.read_text(encoding="utf-8")
    for schema in EXPECTED_SCHEMAS:
        assert f"CREATE SCHEMA IF NOT EXISTS {schema}" in script
    for role in EXPECTED_ROLES:
        assert role in script
    assert "CREATE ROLE" in script
    assert "NOSUPERUSER" in script


def test_env_example_has_connection_keys() -> None:
    """Le modèle versionné couvre les variables lues par Settings."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for key in (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "INGEST_USER",
        "INGEST_PASSWORD",
        "DBT_USER",
        "DBT_PASSWORD",
        "READER_USER",
        "READER_PASSWORD",
    ):
        assert f"{key}=" in text


def test_ensure_dotenv_copies_example_and_loads_it(
    tmp_path: Path,
) -> None:
    """Sans .env, le modèle est copié puis une variable nouvelle est chargée."""
    probe = "OBSERVATORY_ENV_PROBE"
    previous = os.environ.get(probe)
    example = tmp_path / ".env.example"
    example.write_text(f"{probe}=from-example\n", encoding="utf-8")
    os.environ.pop(probe, None)
    try:
        ensure_dotenv(tmp_path / ".env", example)
        assert (tmp_path / ".env").is_file()
        assert os.environ[probe] == "from-example"
    finally:
        if previous is None:
            os.environ.pop(probe, None)
        else:
            os.environ[probe] = previous


def test_ensure_dotenv_keeps_existing_environment(tmp_path: Path) -> None:
    """Une variable déjà définie gagne sur le fichier."""
    probe = "OBSERVATORY_ENV_PROBE"
    previous = os.environ.get(probe)
    example = tmp_path / ".env.example"
    example.write_text(f"{probe}=from-example\n", encoding="utf-8")
    os.environ[probe] = "from-process"
    try:
        ensure_dotenv(tmp_path / ".env", example)
        assert os.environ[probe] == "from-process"
    finally:
        if previous is None:
            os.environ.pop(probe, None)
        else:
            os.environ[probe] = previous


def test_settings_prefer_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings lit l'environnement du processus, pas une valeur figée."""
    monkeypatch.setenv("POSTGRES_HOST", "from-process")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    settings = Settings.from_env()
    assert settings.postgres_host == "from-process"
    assert settings.postgres_port == 5433
    assert settings.postgres_password == "secret"


def test_require_rejects_empty_password() -> None:
    """Un mot de passe vide arrête la commande avant toute connexion."""
    settings = Settings(postgres_password="")
    with pytest.raises(SystemExit):
        settings.require("postgres_password")


def test_missing_names_keeps_expected_order() -> None:
    """Les absents restent dans l'ordre du contrat, pas dans celui du catalogue."""
    found = ["raw", "public"]
    assert missing_names(found, EXPECTED_SCHEMAS) == ["marts", "ops", "staging"]


def _connect_or_skip(settings: Settings, **kwargs: str) -> psycopg.Connection:
    """Ouvre la base, ou saute le test si le serveur n'est pas démarré."""
    try:
        return connect(settings, **kwargs)
    except psycopg.OperationalError as exc:
        text = str(exc).lower()
        offline = (
            "could not connect" in text
            or "connection refused" in text
            or "timeout" in text
            or "could not translate" in text
        )
        if offline:
            pytest.skip(f"Postgres indisponible : {exc}")
        raise


@pytest.mark.integration
def test_database_has_schemas_and_non_superuser_roles() -> None:
    """Les schémas et les trois rôles existent, et aucun n'est superutilisateur."""
    settings = Settings.from_env()
    if not settings.postgres_password:
        pytest.skip("POSTGRES_PASSWORD vide")
    with _connect_or_skip(settings) as connection:
        schemas = list_schemas(connection)
        roles = list_roles(connection)
        rows = connection.execute(
            """
            SELECT rolname, rolsuper
            FROM pg_roles
            WHERE rolname = ANY(%s)
            """,
            (list(EXPECTED_ROLES),),
        ).fetchall()
    assert missing_names(schemas, EXPECTED_SCHEMAS) == []
    assert missing_names(roles, EXPECTED_ROLES) == []
    assert {row[0] for row in rows} == set(EXPECTED_ROLES)
    assert all(row[1] is False for row in rows)


@pytest.mark.integration
def test_ingest_role_can_write_raw_and_ops() -> None:
    """ingest_rw peut créer des objets dans raw et ops."""
    settings = Settings.from_env()
    if not settings.ingest_password:
        pytest.skip("INGEST_PASSWORD vide")
    with _connect_or_skip(
        settings,
        user=settings.ingest_user,
        password=settings.ingest_password,
    ) as connection:
        assert ingest_can_write(connection)


@pytest.mark.integration
def test_dbt_role_writes_staging_and_marts_only() -> None:
    """dbt_rw lit raw, et crée des objets dans staging et marts."""
    settings = Settings.from_env()
    if not settings.dbt_password:
        pytest.skip("DBT_PASSWORD vide")
    with _connect_or_skip(
        settings,
        user=settings.dbt_user,
        password=settings.dbt_password,
    ) as connection:
        row = connection.execute(
            """
            SELECT
              has_schema_privilege(current_user, 'raw', 'USAGE')
              AND NOT has_schema_privilege(current_user, 'raw', 'CREATE')
              AND has_schema_privilege(current_user, 'staging', 'CREATE')
              AND has_schema_privilege(current_user, 'marts', 'CREATE')
            """
        ).fetchone()
    assert row is not None
    assert row[0] is True


@pytest.mark.integration
def test_reader_can_select_future_marts_only() -> None:
    """Une table créée par dbt_rw est lisible par reader_ro, pas modifiable."""
    settings = Settings.from_env()
    if not settings.dbt_password or not settings.reader_password:
        pytest.skip("mots de passe dbt ou reader vides")
    writer = _connect_or_skip(
        settings,
        user=settings.dbt_user,
        password=settings.dbt_password,
    )
    try:
        writer.execute("DROP TABLE IF EXISTS marts._privilege_probe")
        writer.execute("CREATE TABLE marts._privilege_probe (id int)")
        writer.commit()
        with _connect_or_skip(
            settings,
            user=settings.reader_user,
            password=settings.reader_password,
        ) as reader:
            can_select = reader.execute(
                """
                SELECT has_table_privilege(
                  current_user, 'marts._privilege_probe', 'SELECT'
                )
                """
            ).fetchone()
            can_insert = reader.execute(
                """
                SELECT has_table_privilege(
                  current_user, 'marts._privilege_probe', 'INSERT'
                )
                """
            ).fetchone()
            can_create = reader.execute(
                """
                SELECT has_schema_privilege(current_user, 'marts', 'CREATE')
                """
            ).fetchone()
        assert can_select is not None and can_select[0] is True
        assert can_insert is not None and can_insert[0] is False
        assert can_create is not None and can_create[0] is False
    finally:
        # Une erreur SQL laisse la transaction annulée : rollback avant le DROP.
        writer.rollback()
        writer.execute("DROP TABLE IF EXISTS marts._privilege_probe")
        writer.commit()
        writer.close()
