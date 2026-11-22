"""Famille NACE : règle d'abord, cache mock, file de revue, accord non relu."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import psycopg
import pytest

from observatory.config import Settings
from observatory.db import connect
from observatory.establishments import ESTABLISHMENT_SAMPLE, ingest_establishments
from observatory.municipalities import SAMPLE_CSV, ingest_population
from observatory.nace import (
    ACTIVITY_FAMILIES,
    PROMPT_PATH,
    PROMPT_VERSION,
    SOURCE_NAME,
    LiveProviderNotConfigured,
    classify_codes,
    classify_loaded_enterprises,
    classify_nace,
    evaluate_gold,
    load_gold,
)


def test_sample_codes_follow_the_section_rule() -> None:
    """Les huit codes de l'échantillon ont une famille, sans modèle."""
    expected = {
        "1011": "industrie",
        "4120": "construction",
        "4321": "construction",
        "4711": "commerce",
        "4941": "logistique",
        "5210": "logistique",
        "6201": "services",
        "6820": "services",
    }
    seen: set[str] = set()
    with ESTABLISHMENT_SAMPLE.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            seen.add(row["nace_code"])
    assert seen == set(expected)
    for code, family in expected.items():
        prediction = classify_nace(code, mode="live")
        assert prediction.method == "rule"
        assert prediction.activity_family == family
        assert prediction.review_reason is None


def test_live_mode_stops_only_when_the_rule_is_silent() -> None:
    """Une section ambiguë ne déclenche pas un appel inventé."""
    assert classify_nace("6201", mode="live").method == "rule"
    with pytest.raises(LiveProviderNotConfigured):
        classify_nace("0111", mode="live")


def test_missing_cache_answer_goes_to_review() -> None:
    """Un code hors table et hors cache n'a pas de famille."""
    prediction = classify_nace("9999")
    assert prediction.method == "unresolved"
    assert prediction.activity_family is None
    assert prediction.review_reason == "no cached answer"


def test_threshold_is_strict() -> None:
    """0,80 reste accepté. Juste au-dessus du seuil, la ligne part en revue."""
    accepted = classify_nace("9001")
    assert accepted.confidence == 0.8
    assert accepted.review_reason is None
    reviewed = classify_nace("9001", threshold=0.81)
    assert reviewed.review_reason == "confidence below threshold"


def test_family_outside_the_list_is_not_kept(tmp_path: Path) -> None:
    """Une famille absente de la liste fermée ne s'écrit pas comme un résultat."""
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps(
            {
                "model_name": "mock-nace-cache",
                "prompt_version": PROMPT_VERSION,
                "answers": {"0111": {"activity_family": "energie", "confidence": 0.99}},
            }
        ),
        encoding="utf-8",
    )
    prediction = classify_nace("0111", cache_path=path)
    assert prediction.method == "unresolved"
    assert prediction.review_reason == "activity family outside the closed list"


def test_prompt_names_every_family() -> None:
    """Le prompt versionné annonce la même liste que le code."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    for family in ACTIVITY_FAMILIES:
        assert family in text


def test_gold_agreement_is_draft_and_one_code_disagrees() -> None:
    """L'accord est mesuré sur des libellés non relus. 0729 reste en désaccord."""
    result = evaluate_gold()
    rows = load_gold()
    mismatches = [
        row.nace_code
        for row, prediction in zip(rows, result.predictions, strict=True)
        if prediction.activity_family != row.activity_family
    ]
    assert result.scored == 50
    assert result.unverified == 50
    assert all(not row.label_verified for row in rows)
    assert mismatches == ["0729"]
    assert result.agreed == result.scored - 1
    below = {item.nace_code for item in result.predictions if item.review_reason}
    assert below == {"0510", "0812", "3811", "3821", "9700", "0311", "0729"}
    mining = classify_nace("0729")
    assert mining.activity_family == "industrie"
    assert mining.method == "ai"


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
def test_enterprise_codes_are_rules_and_a_low_score_is_queued() -> None:
    """Les codes chargés ne vont pas en revue. Un code sous le seuil, oui."""
    settings = Settings.from_env()
    if not settings.ingest_password:
        pytest.skip("INGEST_PASSWORD vide")
    with _connect_or_skip(settings) as connection:
        ingest_population(connection, SAMPLE_CSV)
        ingest_establishments(connection, ESTABLISHMENT_SAMPLE)
        summary = classify_loaded_enterprises(
            connection,
            mode=settings.ai_mode,
            threshold=settings.ai_confidence_threshold,
        )
        assert summary.codes > 0
        assert summary.by_rule == summary.codes
        assert summary.by_ai == 0
        assert summary.to_review == 0
        methods = connection.execute(
            """
            SELECT activity.method
            FROM raw.enterprise AS enterprise
            JOIN raw.nace_activity AS activity
                ON enterprise.nace_code = activity.nace_code
            """
        ).fetchall()
        assert methods
        assert {row[0] for row in methods} == {"rule"}
        before = connection.execute(
            "SELECT count(*) FROM ops.ai_log WHERE source_name = %s",
            (SOURCE_NAME,),
        ).fetchone()
        assert before is not None
        try:
            classify_codes(
                connection,
                ["3811"],
                source_name=SOURCE_NAME,
                replace_review=True,
            )
            queued = connection.execute(
                """
                SELECT entity_key, reason
                FROM ops.review_queue
                WHERE source_name = %s
                """,
                (SOURCE_NAME,),
            ).fetchall()
            assert queued == [("3811", "confidence below threshold")]
            after = connection.execute(
                "SELECT count(*) FROM ops.ai_log WHERE source_name = %s",
                (SOURCE_NAME,),
            ).fetchone()
            assert after is not None
            assert after[0] == before[0] + 1
        finally:
            connection.execute(
                "DELETE FROM raw.nace_activity WHERE nace_code = %s",
                ("3811",),
            )
            classify_loaded_enterprises(connection)
