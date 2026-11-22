"""Avis de marchés synthétiques, extraits par le cache mock.

TED et le portail wallon ne sont pas branchés : leur format n'a pas été
lu. L'échantillon ``synthetic_public_contracts`` tient lieu de source.
Une extraction invalide part en quarantaine. Sous le seuil, l'avis va
en revue et n'entre pas dans le brut.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

from observatory.db import PgConnection
from observatory.establishments import belgian_check_digits_ok
from observatory.municipalities import RejectedLine, iter_sample_records
from observatory.nace import CONFIDENCE_THRESHOLD, LiveProviderNotConfigured

SOURCE_NAME = "synthetic_public_contracts"
EVAL_SOURCE_NAME = "contract_eval"
SAMPLE_PATH = Path("data/sample/synthetic_public_contracts.csv")
CACHE_PATH = Path("ai/cache/contract_extract.json")
GOLD_PATH = Path("data/eval/gold_contracts.csv")
PROMPT_PATH = Path("ai/prompts/contract_extract_v1.txt")
PROMPT_VERSION = "contract-extract-1"
MODEL_NAME = "mock-contract-cache"

# Champs comparés à l'évaluation. L'identifiant de l'avis n'en fait pas partie.
SCORED_FIELDS = (
    "object_text",
    "awarding_authority",
    "lot_count",
    "cpv_code",
    "amount_eur",
    "nis_code",
    "winner_name",
    "enterprise_number",
)

_NOTICE_FIELDS = ("notice_id", "notice_text")
_GOLD_FIELDS = (
    "notice_id",
    "object_text",
    "awarding_authority",
    "lot_count",
    "cpv_code",
    "amount_eur",
    "nis_code",
    "winner_name",
    "enterprise_number",
    "label_verified",
)


class ContractExtraction(BaseModel):
    """Schéma strict d'un avis extrait. Un montant négatif est refusé."""

    notice_id: str = Field(min_length=1)
    object_text: str = Field(min_length=1)
    awarding_authority: str = Field(min_length=1)
    lot_count: int = Field(ge=1)
    cpv_code: str = Field(pattern=r"^\d{8}$")
    amount_eur: Decimal = Field(gt=0)
    nis_code: str = Field(pattern=r"^(91|92|93)\d{3}$")
    winner_name: str = Field(min_length=1)
    enterprise_number: str | None = None
    confidence: float = Field(ge=0, le=1)

    @field_validator("enterprise_number", mode="before")
    @classmethod
    def _blank_number_is_absent(cls, value: object) -> object:
        if value is None or str(value).strip() == "":
            return None
        return str(value).strip()

    @field_validator("enterprise_number")
    @classmethod
    def _enterprise_number_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith("0") or not belgian_check_digits_ok(value):
            raise ValueError("invalid enterprise number")
        return value


@dataclass(frozen=True)
class ContractNotice:
    """Texte d'avis, tel qu'il serait envoyé à un modèle."""

    notice_id: str
    notice_text: str
    line_number: int


@dataclass(frozen=True)
class GoldContract:
    """Libellé d'évaluation d'un avis. Pas une vérité relue."""

    notice_id: str
    fields: dict[str, str]
    label_verified: bool


@dataclass(frozen=True)
class AiCall:
    """Un appel mock, prêt à être écrit dans ``ops.ai_log``."""

    input_text: str
    output_text: str
    confidence: float
    prompt_version: str


@dataclass(frozen=True)
class PreparedContracts:
    """Avis gardés, refusés, et ceux qui attendent une relecture."""

    loaded: tuple[ContractExtraction, ...]
    rejected: tuple[RejectedLine, ...]
    review: tuple[ContractExtraction, ...]
    calls: tuple[AiCall, ...]


@dataclass(frozen=True)
class ContractEvalResult:
    """Exactitude par champ, sur des libellés non relus."""

    accuracy: float
    matched: int
    scored: int
    unverified: int
    below_threshold: int
    calls: tuple[AiCall, ...]


def load_notices(path: Path = SAMPLE_PATH) -> list[ContractNotice]:
    """Lit les textes d'avis. Le fichier vide n'est pas une erreur silencieuse.

    Parameters
    ----------
    path :
        CSV ``notice_id``, ``notice_text``.

    Returns
    -------
    list[ContractNotice]
        Avis dans l'ordre du fichier.

    Raises
    ------
    ValueError
        En-tête incomplet ou identifiant manquant.
    """
    notices: list[ContractNotice] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not set(_NOTICE_FIELDS).issubset(
            reader.fieldnames
        ):
            raise ValueError("notice file is missing notice_id or notice_text")
        for line_number, row in enumerate(reader, start=2):
            notice_id = (row.get("notice_id") or "").strip()
            notice_text = (row.get("notice_text") or "").strip()
            if not notice_id or not notice_text:
                raise ValueError(f"line {line_number} has an empty notice")
            notices.append(ContractNotice(notice_id, notice_text, line_number))
    return notices


def load_cache(path: Path = CACHE_PATH) -> dict[str, dict]:
    """Charge les extractions mock et vérifie la version du prompt.

    Parameters
    ----------
    path :
        JSON du cache.

    Returns
    -------
    dict[str, dict]
        Réponses par identifiant d'avis.

    Raises
    ------
    ValueError
        Version de prompt différente du code, ou réponses absentes.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("prompt_version") != PROMPT_VERSION:
        found = payload.get("prompt_version")
        raise ValueError(f"cache prompt {found} != {PROMPT_VERSION}")
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise TypeError("cache has no answers")
    return answers


def prepare_contracts(
    notices: list[ContractNotice],
    answers: dict[str, dict],
    allowed_nis_codes: set[str],
    *,
    mode: str = "mock",
    threshold: float = CONFIDENCE_THRESHOLD,
) -> PreparedContracts:
    """Extrait chaque avis. Invalide : quarantaine. Sous le seuil : revue.

    Parameters
    ----------
    notices :
        Textes à extraire.
    answers :
        Cache mock, une entrée par avis.
    allowed_nis_codes :
        Codes INS déjà connus, ceux de la province.
    mode :
        ``mock`` ou ``live``.
    threshold :
        Confiance en dessous de laquelle l'avis n'est pas chargé.

    Returns
    -------
    PreparedContracts
        Gardés, refusés, revue, et appels à journaliser.

    Raises
    ------
    LiveProviderNotConfigured
        ``mode`` vaut ``live`` : aucun fournisseur n'est branché.
    ValueError
        ``mode`` n'est ni ``mock`` ni ``live``.
    """
    if mode == "live":
        raise LiveProviderNotConfigured(
            "AI_MODE=live has no contract provider. Use AI_MODE=mock."
        )
    if mode != "mock":
        raise ValueError(f"unknown AI_MODE {mode}")
    prompt = _prompt_text()
    loaded: list[ContractExtraction] = []
    rejected: list[RejectedLine] = []
    review: list[ContractExtraction] = []
    calls: list[AiCall] = []
    for notice in notices:
        raw = answers.get(notice.notice_id)
        output_text = "" if raw is None else json.dumps(raw, ensure_ascii=False)
        confidence = _confidence_or_zero(raw)
        calls.append(
            AiCall(
                input_text=f"{prompt}\n\n{notice.notice_text}",
                output_text=output_text or notice.notice_id,
                confidence=confidence,
                prompt_version=PROMPT_VERSION,
            )
        )
        if raw is None:
            rejected.append(
                RejectedLine(
                    notice.line_number,
                    notice.notice_text[:500],
                    "no mock extraction",
                )
            )
            continue
        try:
            extracted = ContractExtraction.model_validate(
                {"notice_id": notice.notice_id, **raw}
            )
        except ValidationError as exc:
            rejected.append(
                RejectedLine(
                    notice.line_number,
                    notice.notice_text[:500],
                    _reason(exc),
                )
            )
            continue
        if extracted.nis_code not in allowed_nis_codes:
            rejected.append(
                RejectedLine(
                    notice.line_number,
                    notice.notice_text[:500],
                    "nis_code is not a known Namur municipality",
                )
            )
            continue
        # Strictement sous le seuil : on garde la trace, pas la ligne brute.
        if extracted.confidence < threshold:
            review.append(extracted)
            continue
        loaded.append(extracted)
    return PreparedContracts(
        loaded=tuple(loaded),
        rejected=tuple(rejected),
        review=tuple(review),
        calls=tuple(calls),
    )


def evaluate_contracts(
    gold_path: Path = GOLD_PATH,
    cache_path: Path = CACHE_PATH,
    *,
    mode: str = "mock",
    threshold: float = CONFIDENCE_THRESHOLD,
) -> ContractEvalResult:
    """Mesure l'exactitude de chaque champ sur les avis du fichier d'évaluation.

    Le taux n'est pas une exactitude validée : ``label_verified`` reste
    faux tant que les avis n'ont pas été relus.

    Parameters
    ----------
    gold_path :
        CSV des libellés.
    cache_path :
        Cache mock.
    mode :
        ``mock`` ou ``live``.
    threshold :
        Sert à compter les réponses sous le seuil, pas à les exclure du score.

    Returns
    -------
    ContractEvalResult
        Champs concordants, champs notés, libellés non relus.

    Raises
    ------
    ValueError
        Un avis du fichier d'évaluation n'a pas d'extraction valide.
    """
    gold_rows = load_gold(gold_path)
    answers = load_cache(cache_path)
    notices = [
        ContractNotice(row.notice_id, row.notice_id, index)
        for index, row in enumerate(gold_rows, start=2)
    ]
    prepared = prepare_contracts(
        notices,
        answers,
        _gold_nis_codes(gold_rows),
        mode=mode,
        threshold=threshold,
    )
    by_id = {item.notice_id: item for item in (*prepared.loaded, *prepared.review)}
    matched = 0
    scored = 0
    for row in gold_rows:
        extracted = by_id.get(row.notice_id)
        if extracted is None:
            raise ValueError(f"{row.notice_id} has no valid extraction")
        for field in SCORED_FIELDS:
            scored += 1
            if _field_matches(field, row.fields[field], extracted):
                matched += 1
    unverified = sum(1 for row in gold_rows if not row.label_verified)
    below = sum(1 for item in by_id.values() if item.confidence < threshold)
    accuracy = 0.0 if scored == 0 else matched / scored
    return ContractEvalResult(
        accuracy=accuracy,
        matched=matched,
        scored=scored,
        unverified=unverified,
        below_threshold=below,
        calls=prepared.calls,
    )


def load_gold(path: Path = GOLD_PATH) -> list[GoldContract]:
    """Lit les libellés d'évaluation.

    Parameters
    ----------
    path :
        CSV d'évaluation.

    Returns
    -------
    list[GoldContract]
        Une ligne par avis.

    Raises
    ------
    ValueError
        En-tête incomplet.
    """
    rows: list[GoldContract] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not set(_GOLD_FIELDS).issubset(
            reader.fieldnames
        ):
            raise ValueError("gold file is missing a required column")
        for row in reader:
            fields = {field: (row.get(field) or "").strip() for field in SCORED_FIELDS}
            verified = (row.get("label_verified") or "").strip().lower() == "true"
            rows.append(
                GoldContract(
                    notice_id=(row.get("notice_id") or "").strip(),
                    fields=fields,
                    label_verified=verified,
                )
            )
    return rows


def ingest_contracts(
    connection: PgConnection,
    path: Path = SAMPLE_PATH,
    *,
    mode: str = "mock",
    threshold: float = CONFIDENCE_THRESHOLD,
) -> tuple[int, int, int]:
    """Charge les avis acceptés et remplace rejets et revue de cette source.

    Parameters
    ----------
    connection :
        Connexion ouverte avec ``ingest_rw``.
    path :
        CSV des textes d'avis.
    mode :
        ``mock`` ou ``live``.
    threshold :
        Seuil de confiance.

    Returns
    -------
    tuple[int, int, int]
        Avis chargés, lignes refusées, avis en revue.
    """
    allowed = {record.nis_code for record in iter_sample_records()}
    prepared = prepare_contracts(
        load_notices(path),
        load_cache(),
        allowed,
        mode=mode,
        threshold=threshold,
    )
    _ensure_table(connection)
    _replace_rejects(connection, prepared.rejected)
    _replace_review(connection, prepared.review)
    _upsert(connection, prepared.loaded)
    _insert_logs(connection, prepared.calls, SOURCE_NAME)
    connection.commit()
    return len(prepared.loaded), len(prepared.rejected), len(prepared.review)


def log_contract_calls(
    connection: PgConnection,
    calls: tuple[AiCall, ...] | list[AiCall],
    *,
    source_name: str,
) -> int:
    """Ajoute les appels d'évaluation au journal. Ne remplace pas l'historique.

    Parameters
    ----------
    connection :
        Connexion ``ingest_rw``.
    calls :
        Appels déjà préparés.
    source_name :
        Nom écrit dans ``ops.ai_log``.

    Returns
    -------
    int
        Nombre de lignes ajoutées.
    """
    _ensure_table(connection)
    _insert_logs(connection, calls, source_name)
    connection.commit()
    return len(calls)


def _prompt_text() -> str:
    """Lit le prompt versionné. Un fichier absent casse le chargement."""
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def _confidence_or_zero(raw: dict | None) -> float:
    """Confiance du cache, ou 0 si la réponse ne se lit pas."""
    if not isinstance(raw, dict):
        return 0.0
    try:
        return float(raw.get("confidence", 0))
    except (TypeError, ValueError):
        return 0.0


def _field_matches(field: str, expected: str, extracted: ContractExtraction) -> bool:
    """Compare un champ du libellé à l'extraction, sans tenir compte du vide."""
    found = getattr(extracted, field)
    if field == "amount_eur":
        return Decimal(expected) == found
    if field == "lot_count":
        return int(expected) == found
    if field == "enterprise_number":
        return expected == (found or "")
    return expected == found


def _gold_nis_codes(rows: list[GoldContract]) -> set[str]:
    """Communes citées par le fichier d'évaluation.

    L'évaluation note l'extraction, elle ne revérifie pas le référentiel.
    """
    return {row.fields["nis_code"] for row in rows}


def _reason(exc: ValidationError) -> str:
    """Résume une erreur pydantic pour la quarantaine."""
    return "; ".join(error["msg"] for error in exc.errors())


def _ensure_table(connection: PgConnection) -> None:
    """Crée la table brute des avis. Le journal d'IA existe déjà avec NACE."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.public_contract (
            notice_id text PRIMARY KEY,
            object_text text NOT NULL,
            awarding_authority text NOT NULL,
            lot_count integer NOT NULL,
            cpv_code text NOT NULL,
            amount_eur numeric NOT NULL,
            nis_code text NOT NULL,
            winner_name text NOT NULL,
            enterprise_number text,
            confidence numeric NOT NULL,
            model_name text NOT NULL,
            prompt_version text NOT NULL,
            source_name text NOT NULL,
            CHECK (amount_eur > 0),
            CHECK (lot_count >= 1),
            CHECK (char_length(cpv_code) = 8)
        )
        """
    )


def _replace_rejects(
    connection: PgConnection,
    rejected: tuple[RejectedLine, ...],
) -> None:
    """Ne garde que les rejets de ce passage."""
    connection.execute(
        "DELETE FROM ops.rejects WHERE source_name = %s",
        (SOURCE_NAME,),
    )
    if not rejected:
        return
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO ops.rejects (source_name, line_number, payload, reason)
            VALUES (%s, %s, %s, %s)
            """,
            [
                (SOURCE_NAME, item.line_number, item.payload, item.reason)
                for item in rejected
            ],
        )


def _replace_review(
    connection: PgConnection,
    review: tuple[ContractExtraction, ...],
) -> None:
    """Remplace la file de revue des avis, pas celle des codes NACE."""
    connection.execute(
        "DELETE FROM ops.review_queue WHERE source_name = %s",
        (SOURCE_NAME,),
    )
    if not review:
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
                    item.notice_id,
                    "confidence below threshold",
                    item.object_text,
                )
                for item in review
            ],
        )


def _upsert(connection: PgConnection, loaded: tuple[ContractExtraction, ...]) -> None:
    """Upsert sur l'identifiant d'avis. Un avis retiré du fichier reste en base.

    Le passage ne supprime pas les anciens avis : la clé naturelle est
    réécrite. Un identifiant qui disparaît du fichier n'est pas effacé.
    """
    if not loaded:
        return
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO raw.public_contract (
                notice_id, object_text, awarding_authority, lot_count,
                cpv_code, amount_eur, nis_code, winner_name,
                enterprise_number, confidence, model_name, prompt_version,
                source_name
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (notice_id) DO UPDATE SET
                object_text = EXCLUDED.object_text,
                awarding_authority = EXCLUDED.awarding_authority,
                lot_count = EXCLUDED.lot_count,
                cpv_code = EXCLUDED.cpv_code,
                amount_eur = EXCLUDED.amount_eur,
                nis_code = EXCLUDED.nis_code,
                winner_name = EXCLUDED.winner_name,
                enterprise_number = EXCLUDED.enterprise_number,
                confidence = EXCLUDED.confidence,
                model_name = EXCLUDED.model_name,
                prompt_version = EXCLUDED.prompt_version,
                source_name = EXCLUDED.source_name
            """,
            [
                (
                    item.notice_id,
                    item.object_text,
                    item.awarding_authority,
                    item.lot_count,
                    item.cpv_code,
                    item.amount_eur,
                    item.nis_code,
                    item.winner_name,
                    item.enterprise_number,
                    item.confidence,
                    MODEL_NAME,
                    PROMPT_VERSION,
                    SOURCE_NAME,
                )
                for item in loaded
            ],
        )


def _insert_logs(
    connection: PgConnection,
    calls: tuple[AiCall, ...] | list[AiCall],
    source_name: str,
) -> None:
    """Ajoute une ligne de journal par avis. L'historique n'est pas effacé."""
    if not calls:
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
                    source_name,
                    item.input_text,
                    item.output_text,
                    MODEL_NAME,
                    item.prompt_version,
                    item.confidence,
                )
                for item in calls
            ],
        )
