"""Lien avis-entreprise : numéro, nom proche, nom éloigné."""

from __future__ import annotations

import psycopg
import pytest

from observatory.config import Settings
from observatory.contracts import ingest_contracts
from observatory.db import connect
from observatory.entities import (
    SOURCE_NAME,
    ContractWinner,
    EnterpriseName,
    link_loaded_contracts,
    resolve_winner,
)
from observatory.establishments import ESTABLISHMENT_SAMPLE, ingest_establishments
from observatory.municipalities import SAMPLE_CSV, ingest_population

_FIRMS = [
    EnterpriseName("0000000196", "Synthetic firm 001"),
    EnterpriseName("0000000592", "Synthetic firm 005"),
    EnterpriseName("0000000889", "Synthetic firm 008"),
]


def test_known_number_links_without_looking_at_the_name() -> None:
    """Un numéro présent dans le référentiel lie, même si le nom diffère."""
    link = resolve_winner(
        ContractWinner("n1", "Autre nom", "0000000196"),
        _FIRMS,
    )
    assert link.status == "linked"
    assert link.method == "number"
    assert link.score == 100.0


def test_exact_name_links_when_the_number_is_absent() -> None:
    """Sans numéro, le même nom lie."""
    link = resolve_winner(
        ContractWinner("n2", "Synthetic firm 001", None),
        _FIRMS,
    )
    assert link.status == "linked"
    assert link.method == "name"
    assert link.enterprise_number == "0000000196"


def test_near_name_waits_for_review() -> None:
    """Un nom proche, pas identique, ne lie pas tout seul."""
    link = resolve_winner(
        ContractWinner("n3", "Synth. firm 005", None),
        _FIRMS,
    )
    assert link.status == "review"
    assert link.enterprise_number == "0000000592"
    assert link.score == 87.5


def test_distant_name_stays_unmatched() -> None:
    """Un nom sans rapport ne propose pas d'entreprise."""
    link = resolve_winner(
        ContractWinner("n4", "Atelier du parc", None),
        _FIRMS,
    )
    assert link.status == "unmatched"
    assert link.enterprise_number is None


@pytest.mark.integration
def test_loaded_sample_splits_into_link_review_and_unmatched() -> None:
    """L'échantillon réel donne 8 liens, 1 revue et 1 avis sans lien."""
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
        ingest_establishments(connection, ESTABLISHMENT_SAMPLE)
        ingest_contracts(connection)
        first = link_loaded_contracts(connection)
        second = link_loaded_contracts(connection)
        queued = connection.execute(
            "SELECT count(*) FROM ops.review_queue WHERE source_name = %s",
            (SOURCE_NAME,),
        ).fetchone()
    assert first == {"linked": 8, "review": 1, "unmatched": 1}
    assert second == first
    assert queued is not None and queued[0] == 1
