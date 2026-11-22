"""Journal de passage, fraîcheur, et chute de volume de plus de 50 %."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from observatory.cli import cmd_ingest
from observatory.config import Settings
from observatory.db import connect
from observatory.healthcheck import collect_problems, main, problems
from observatory.runs import RunRecord, finish_run, latest_runs, start_run

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
WEEK = timedelta(days=7)


def _ok(name: str, when: datetime, read: int, rejected: int = 0) -> RunRecord:
    return RunRecord(name, "success", when, read, rejected)


def test_exact_half_is_kept_and_one_row_less_fails() -> None:
    """Garder 50 % passe. Garder moins, non. Le volume compte les lignes gardées."""
    fresh = {
        "sample": [
            _ok("sample", NOW, 80, rejected=40),
            _ok("sample", NOW - timedelta(days=1), 100),
        ]
    }
    assert problems(fresh, required=("sample",), now=NOW, max_age=WEEK) == [
        "source sample volume dropped from 100 to 40"
    ]
    half = {
        "sample": [
            _ok("sample", NOW, 50),
            _ok("sample", NOW - timedelta(days=1), 100),
        ]
    }
    assert problems(half, required=("sample",), now=NOW, max_age=WEEK) == []


def test_source_is_stale_only_after_the_max_age() -> None:
    """Sept jours pile restent frais. Une seconde de plus, la source est périmée."""
    on_time = {
        "sample": [_ok("sample", NOW - WEEK, 10)],
    }
    late = {
        "sample": [_ok("sample", NOW - WEEK - timedelta(seconds=1), 10)],
    }
    assert problems(on_time, required=("sample",), now=NOW, max_age=WEEK) == []
    assert problems(late, required=("sample",), now=NOW, max_age=WEEK) == [
        "source sample is stale (last success 2026-11-15)"
    ]


def test_missing_or_unfinished_run_fails() -> None:
    """Pas de passage, ou un passage encore ouvert, n'est pas un succès."""
    runs = {
        "missing": [],
        "open": [RunRecord("open", "running", None, None, None)],
        "broken": [RunRecord("broken", "failed", NOW, None, None)],
    }
    assert problems(
        runs,
        required=("missing", "open", "broken"),
        now=NOW,
        max_age=WEEK,
    ) == [
        "source missing has no run",
        "source open last run is running",
        "source broken last run is failed",
    ]


def _connect_or_skip(settings: Settings) -> psycopg.Connection:
    """Ouvre la base avec ingest_rw, ou saute le test si Postgres est arrêté."""
    try:
        return connect(
            settings,
            user=settings.ingest_user,
            password=settings.ingest_password,
        )
    except psycopg.OperationalError as exc:
        text = str(exc).lower()
        if any(
            token in text
            for token in (
                "could not connect",
                "connection refused",
                "timeout",
                "could not translate",
            )
        ):
            pytest.skip(f"Postgres indisponible : {exc}")
        raise


@pytest.mark.integration
def test_recorded_run_is_read_back_and_an_old_one_is_stale() -> None:
    """Le journal revient avec son volume, et un succès de 8 jours est périmé."""
    settings = Settings.from_env()
    if not settings.ingest_password:
        pytest.skip("INGEST_PASSWORD vide")
    source = "fixture_health"
    with _connect_or_skip(settings) as connection:
        try:
            run_id = start_run(connection, source)
            finish_run(
                connection,
                run_id,
                rows_read=38,
                rows_rejected=1,
                status="success",
            )
            loaded = latest_runs(connection, (source,))
            assert loaded[source][0].rows_read == 38
            assert loaded[source][0].rows_rejected == 1
            assert loaded[source][0].status == "success"
            connection.execute(
                """
                UPDATE ops.run_log
                SET started_at = clock_timestamp() - interval '8 days',
                    finished_at = clock_timestamp() - interval '8 days'
                WHERE run_id = %s
                """,
                (run_id,),
            )
            connection.commit()
            found = collect_problems(
                connection,
                required=(source,),
                max_age=WEEK,
            )
            assert len(found) == 1
            assert found[0].startswith(f"source {source} is stale")
        finally:
            connection.execute(
                "DELETE FROM ops.run_log WHERE source_name = %s",
                (source,),
            )
            connection.commit()


@pytest.mark.integration
def test_ingest_leaves_the_monitored_sources_healthy(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Après un chargement, le healthcheck des trois sources répond ok."""
    settings = Settings.from_env()
    if not settings.ingest_password:
        pytest.skip("INGEST_PASSWORD vide")
    with _connect_or_skip(settings):
        pass
    assert cmd_ingest(settings) == 0
    assert main() == 0
    captured = capsys.readouterr()
    assert captured.out.strip().splitlines()[-1] == "ok"
