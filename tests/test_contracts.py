"""Avis synthétiques : extraction mock, quarantaine, lien par la commune."""

from __future__ import annotations

import psycopg
import pytest

from observatory.config import Settings
from observatory.contracts import (
    ContractNotice,
    evaluate_contracts,
    ingest_contracts,
    load_cache,
    load_notices,
    prepare_contracts,
)
from observatory.db import connect
from observatory.municipalities import (
    SAMPLE_CSV,
    ingest_population,
    iter_sample_records,
)
from observatory.nace import LiveProviderNotConfigured


def _allowed() -> set[str]:
    return {record.nis_code for record in iter_sample_records()}


def test_gold_misses_only_the_deliberate_amount() -> None:
    """Dix avis, huit champs : un seul montant ne concorde pas."""
    result = evaluate_contracts()
    assert result.scored == 80
    assert result.matched == 79
    assert result.unverified == 10
    assert result.below_threshold == 1
    assert result.accuracy == pytest.approx(79 / 80)


def test_invalid_amount_is_rejected_and_low_confidence_is_not_loaded() -> None:
    """Le montant négatif est refusé. L'avis sous le seuil part en revue."""
    prepared = prepare_contracts(load_notices(), load_cache(), _allowed())
    loaded_ids = {item.notice_id for item in prepared.loaded}
    assert "synthetic-notice-12" not in loaded_ids
    assert "synthetic-notice-07" not in loaded_ids
    assert len(prepared.rejected) == 1
    assert len(prepared.review) == 1
    assert len(prepared.loaded) == 10
    assert all(item.nis_code in _allowed() for item in prepared.loaded)


def test_unknown_municipality_is_rejected() -> None:
    """Une commune hors référentiel ne passe pas, même si le reste est valide."""
    notice = ContractNotice("synthetic-notice-01", "texte", 2)
    answer = dict(load_cache()["synthetic-notice-01"])
    answer["nis_code"] = "91004"
    prepared = prepare_contracts([notice], {"synthetic-notice-01": answer}, _allowed())
    assert prepared.loaded == ()
    assert len(prepared.rejected) == 1


def test_live_mode_is_not_wired() -> None:
    """Le mode live n'invente pas de fournisseur."""
    with pytest.raises(LiveProviderNotConfigured):
        prepare_contracts(load_notices(), load_cache(), _allowed(), mode="live")


@pytest.mark.integration
def test_ingest_keeps_contracts_on_known_municipalities() -> None:
    """Le chargement réel laisse 10 avis, 1 rejet et 1 avis en revue."""
    settings = Settings.from_env()
    if not settings.ingest_password:
        pytest.skip("INGEST_PASSWORD vide")
    try:
        connection = connect(
            settings,
            user=settings.ingest_user,
            password=settings.ingest_password,
        )
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponible : {exc}")
    with connection:
        ingest_population(connection, SAMPLE_CSV)
        loaded, rejected, review = ingest_contracts(connection)
        stored = connection.execute(
            "SELECT count(*) FROM raw.public_contract"
        ).fetchone()
        orphans = connection.execute(
            """
            SELECT count(*)
            FROM raw.public_contract AS contract
            LEFT JOIN raw.municipality_population AS municipality
                ON contract.nis_code = municipality.nis_code
            WHERE municipality.nis_code IS NULL
            """
        ).fetchone()
    assert loaded == 10
    assert rejected == 1
    assert review == 1
    assert stored is not None and stored[0] == 10
    assert orphans is not None and orphans[0] == 0
