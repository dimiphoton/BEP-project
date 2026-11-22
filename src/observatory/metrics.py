"""Mesures écrites dans ``docs/metrics.json``. Rien n'y est saisi à la main.

Un comptage impossible (table absente, ``dbt`` pas encore lancé) reste
``null``. Ce n'est pas un zéro.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from observatory.contracts import SOURCE_NAME as CONTRACT_SOURCE
from observatory.contracts import evaluate_contracts
from observatory.db import PgConnection
from observatory.establishments import SOURCE_NAME as ESTABLISHMENT_SOURCE
from observatory.municipalities import SOURCE_NAME as MUNICIPALITY_SOURCE
from observatory.nace import evaluate_gold

METRICS_PATH = Path("docs/metrics.json")
RUN_RESULTS_PATH = Path("dbt/target/run_results.json")

_MUNICIPALITIES = "marts.dim_municipality"
_ESTABLISHMENTS = "marts.fact_establishment"
_ENTERPRISES = "marts.dim_enterprise"
_CONTRACTS = "marts.fact_public_contract"


def count_dbt_tests(payload: dict) -> tuple[int, int]:
    """Compte les tests dbt réussis et échoués.

    Parameters
    ----------
    payload :
        Contenu de ``target/run_results.json``. Les modèles ne comptent pas.

    Returns
    -------
    tuple[int, int]
        Tests au statut ``pass``, puis ``fail`` ou ``error``.
    """
    passed = 0
    failed = 0
    for result in payload.get("results", []):
        unique_id = str(result.get("unique_id") or "")
        if not unique_id.startswith("test."):
            continue
        status = result.get("status")
        if status == "pass":
            passed += 1
        elif status in {"fail", "error"}:
            failed += 1
    return passed, failed


def load_dbt_tests(path: Path = RUN_RESULTS_PATH) -> tuple[int | None, int | None]:
    """Lit le dernier ``dbt build``. Absent : les deux comptes restent vides.

    Parameters
    ----------
    path :
        Fichier ``run_results.json``, régénéré par ``make build``.

    Returns
    -------
    tuple[int | None, int | None]
        Réussis et échoués, ou ``(None, None)`` si le fichier n'existe pas.
    """
    if not path.is_file():
        return None, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return count_dbt_tests(payload)


def collect_metrics(connection: PgConnection) -> dict:
    """Assemble les mesures depuis la base, dbt et l'évaluation NACE.

    Parameters
    ----------
    connection :
        Connexion qui peut lire ``marts`` et ``ops``.

    Returns
    -------
    dict
        Document ``metrics.json``, clés dans un ordre stable.
    """
    evaluation = evaluate_gold()
    contracts = evaluate_contracts()
    dbt_passed, dbt_failed = load_dbt_tests()
    return {
        "counts": {
            "municipalities": _count_relation(connection, _MUNICIPALITIES),
            "establishments": _count_relation(connection, _ESTABLISHMENTS),
            "enterprises": _count_relation(connection, _ENTERPRISES),
            "public_contracts": _count_relation(connection, _CONTRACTS),
        },
        "rejects": _reject_counts(connection),
        "dbt": {"passed": dbt_passed, "failed": dbt_failed},
        "ai": {
            "nace_agreement": round(evaluation.agreement, 4),
            "nace_agreed": evaluation.agreed,
            "nace_scored": evaluation.scored,
            "nace_unverified": evaluation.unverified,
            "nace_below_threshold": evaluation.below_threshold,
            "extraction_field_accuracy": round(contracts.accuracy, 4),
            "extraction_fields_matched": contracts.matched,
            "extraction_fields_scored": contracts.scored,
            "extraction_unverified": contracts.unverified,
            "extraction_below_threshold": contracts.below_threshold,
        },
        "data_origin": {
            "municipalities": "real",
            "establishments": "synthetic",
            "public_contracts": "synthetic",
        },
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }


def write_metrics(payload: dict, path: Path = METRICS_PATH) -> None:
    """Écrit le JSON indenté, UTF-8, avec un saut de ligne final.

    Parameters
    ----------
    payload :
        Document produit par ``collect_metrics``.
    path :
        Destination versionnée.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def _count_relation(connection: PgConnection, qualified: str) -> int | None:
    """Compte une relation si elle existe. Sinon ``None``, pas zéro."""
    found = connection.execute("SELECT to_regclass(%s)", (qualified,)).fetchone()
    if found is None or found[0] is None:
        return None
    # Le nom vient de la constante du module, pas d'une saisie.
    row = connection.execute(f"SELECT count(*) FROM {qualified}").fetchone()
    if row is None:
        return None
    return int(row[0])


def _reject_counts(connection: PgConnection) -> dict[str, int]:
    """Rejets par source. Les deux sources chargées apparaissent même à zéro."""
    counts = {
        MUNICIPALITY_SOURCE: 0,
        ESTABLISHMENT_SOURCE: 0,
        CONTRACT_SOURCE: 0,
    }
    found = connection.execute("SELECT to_regclass('ops.rejects')").fetchone()
    if found is None or found[0] is None:
        return counts
    rows = connection.execute(
        """
        SELECT source_name, count(*)
        FROM ops.rejects
        GROUP BY source_name
        ORDER BY source_name
        """
    ).fetchall()
    for source_name, total in rows:
        counts[source_name] = int(total)
    return counts
