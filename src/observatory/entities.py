"""Rattache l'attributaire d'un avis à une entreprise connue.

Le numéro d'entreprise, s'il est dans le référentiel, lie tout de suite.
Sinon le nom est normalisé et comparé avec rapidfuzz. Un score haut lie,
une zone grise part en revue, un score bas ne lie pas.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from observatory.db import PgConnection

SOURCE_NAME = "entity_resolution"
MODEL_NAME = "rapidfuzz"
PROMPT_VERSION = "entity-resolution-1"
# Score rapidfuzz sur 100, après normalisation. 95 lie, 80 ouvre la revue.
AUTO_SCORE = 95.0
REVIEW_SCORE = 80.0


@dataclass(frozen=True)
class EnterpriseName:
    """Entreprise du référentiel, numéro et nom."""

    enterprise_number: str
    enterprise_name: str


@dataclass(frozen=True)
class ContractWinner:
    """Avis déjà chargé, avec le nom et le numéro extraits."""

    notice_id: str
    winner_name: str
    enterprise_number: str | None


@dataclass(frozen=True)
class EntityLink:
    """Décision pour un avis."""

    notice_id: str
    winner_name: str
    enterprise_number: str | None
    method: str
    score: float
    status: str


def normalize_name(value: str) -> str:
    """Minuscules, sans ponctuation, espaces simples.

    Parameters
    ----------
    value :
        Nom tel qu'extrait.

    Returns
    -------
    str
        Forme comparée par rapidfuzz.
    """
    text = value.casefold()
    text = re.sub(r"[^0-9a-z]+", " ", text)
    return " ".join(text.split())


def resolve_winner(
    winner: ContractWinner,
    enterprises: list[EnterpriseName],
) -> EntityLink:
    """Choisit le lien d'un avis.

    Parameters
    ----------
    winner :
        Attributaire extrait.
    enterprises :
        Référentiel des entreprises.

    Returns
    -------
    EntityLink
        Lien, revue, ou absence de lien.
    """
    by_number = {item.enterprise_number: item for item in enterprises}
    number = winner.enterprise_number
    if number and number in by_number:
        return EntityLink(
            notice_id=winner.notice_id,
            winner_name=winner.winner_name,
            enterprise_number=number,
            method="number",
            score=100.0,
            status="linked",
        )
    best_number, best_score = _best_name(winner.winner_name, enterprises)
    if best_score >= AUTO_SCORE and best_number is not None:
        return EntityLink(
            notice_id=winner.notice_id,
            winner_name=winner.winner_name,
            enterprise_number=best_number,
            method="name",
            score=best_score,
            status="linked",
        )
    if best_score >= REVIEW_SCORE and best_number is not None:
        return EntityLink(
            notice_id=winner.notice_id,
            winner_name=winner.winner_name,
            enterprise_number=best_number,
            method="name",
            score=best_score,
            status="review",
        )
    return EntityLink(
        notice_id=winner.notice_id,
        winner_name=winner.winner_name,
        enterprise_number=None,
        method="none",
        score=best_score,
        status="unmatched",
    )


def resolve_winners(
    winners: list[ContractWinner],
    enterprises: list[EnterpriseName],
) -> list[EntityLink]:
    """Résout une liste d'avis, dans l'ordre reçu.

    Parameters
    ----------
    winners :
        Avis chargés.
    enterprises :
        Référentiel.

    Returns
    -------
    list[EntityLink]
        Une décision par avis.
    """
    return [resolve_winner(winner, enterprises) for winner in winners]


def link_loaded_contracts(connection: PgConnection) -> dict[str, int]:
    """Réécrit les liens des avis chargés, et la revue de cette source.

    Parameters
    ----------
    connection :
        Connexion ``ingest_rw``.

    Returns
    -------
    dict[str, int]
        Effectifs ``linked``, ``review`` et ``unmatched``.
    """
    enterprises = _read_enterprises(connection)
    winners = _read_winners(connection)
    links = resolve_winners(winners, enterprises)
    _ensure_table(connection)
    _replace_links(connection, links)
    _replace_review(connection, links)
    _insert_logs(connection, links)
    connection.commit()
    counts = {"linked": 0, "review": 0, "unmatched": 0}
    for link in links:
        counts[link.status] += 1
    return counts


def _best_name(
    winner_name: str,
    enterprises: list[EnterpriseName],
) -> tuple[str | None, float]:
    """Meilleur score de nom. À égalité, le plus petit numéro gagne."""
    if not enterprises:
        return None, 0.0
    left = normalize_name(winner_name)
    ranked: list[tuple[float, str]] = []
    for enterprise in enterprises:
        right = normalize_name(enterprise.enterprise_name)
        score = round(fuzz.token_sort_ratio(left, right), 1)
        ranked.append((score, enterprise.enterprise_number))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    score, number = ranked[0]
    return number, score


def _read_enterprises(connection: PgConnection) -> list[EnterpriseName]:
    """Lit le référentiel brut des entreprises."""
    rows = connection.execute(
        """
        SELECT enterprise_number, enterprise_name
        FROM raw.enterprise
        ORDER BY enterprise_number
        """
    ).fetchall()
    return [EnterpriseName(str(number), str(name)) for number, name in rows]


def _read_winners(connection: PgConnection) -> list[ContractWinner]:
    """Lit les avis déjà acceptés dans le brut."""
    rows = connection.execute(
        """
        SELECT notice_id, winner_name, enterprise_number
        FROM raw.public_contract
        ORDER BY notice_id
        """
    ).fetchall()
    return [
        ContractWinner(
            str(notice_id),
            str(winner_name),
            None if enterprise_number is None else str(enterprise_number),
        )
        for notice_id, winner_name, enterprise_number in rows
    ]


def _ensure_table(connection: PgConnection) -> None:
    """Crée la table des liens. Une ligne par avis chargé."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.contract_enterprise_link (
            notice_id text PRIMARY KEY,
            enterprise_number text,
            method text NOT NULL,
            score numeric NOT NULL,
            status text NOT NULL,
            winner_name text NOT NULL,
            source_name text NOT NULL,
            CHECK (method IN ('number', 'name', 'none')),
            CHECK (status IN ('linked', 'review', 'unmatched')),
            CHECK (score >= 0 AND score <= 100)
        )
        """
    )


def _replace_links(connection: PgConnection, links: list[EntityLink]) -> None:
    """Remplace les liens de cette source. Relancer ne double pas."""
    connection.execute(
        "DELETE FROM raw.contract_enterprise_link WHERE source_name = %s",
        (SOURCE_NAME,),
    )
    if not links:
        return
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO raw.contract_enterprise_link (
                notice_id, enterprise_number, method, score,
                status, winner_name, source_name
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    link.notice_id,
                    link.enterprise_number,
                    link.method,
                    link.score,
                    link.status,
                    link.winner_name,
                    SOURCE_NAME,
                )
                for link in links
            ],
        )


def _replace_review(connection: PgConnection, links: list[EntityLink]) -> None:
    """Ne remplace que la revue des noms, pas celle des autres sources."""
    connection.execute(
        "DELETE FROM ops.review_queue WHERE source_name = %s",
        (SOURCE_NAME,),
    )
    queued = [link for link in links if link.status == "review"]
    if not queued:
        return
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO ops.review_queue (source_name, entity_key, reason, payload)
            VALUES (%s, %s, %s, %s)
            """,
            [
                (
                    SOURCE_NAME,
                    link.notice_id,
                    "name score in the review band",
                    link.winner_name,
                )
                for link in queued
            ],
        )


def _insert_logs(connection: PgConnection, links: list[EntityLink]) -> None:
    """Journalise chaque comparaison. Ce n'est pas un appel distant."""
    if not links:
        return
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO ops.ai_log (
                source_name, input_text, output_text, model_name,
                prompt_version, confidence
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    SOURCE_NAME,
                    link.winner_name,
                    json.dumps(
                        {
                            "status": link.status,
                            "method": link.method,
                            "enterprise_number": link.enterprise_number,
                            "score": link.score,
                        },
                        ensure_ascii=False,
                    ),
                    MODEL_NAME,
                    PROMPT_VERSION,
                    link.score / 100,
                )
                for link in links
            ],
        )
