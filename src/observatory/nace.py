"""Famille d'activité d'un code NACE : règle d'abord, cache mock ensuite.

Les sections NACE Rev. 2 qui tombent dans une seule famille de la liste
fermée ne passent pas par un modèle. Les autres lisent ``ai/cache`` quand
``AI_MODE=mock``. Aucun fournisseur live n'est branché : cela inventerait
un format d'API.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from observatory.db import PgConnection

ACTIVITY_FAMILIES = (
    "industrie",
    "logistique",
    "commerce",
    "services",
    "construction",
    "autre",
)
CONFIDENCE_THRESHOLD = 0.8
PROMPT_VERSION = "nace-family-1"
SOURCE_NAME = "nace_family"
EVAL_SOURCE_NAME = "nace_eval"
MODEL_NAME = "mock-nace-cache"

GOLD_PATH = Path("data/eval/gold_nace.csv")
NACE_CACHE = Path("ai/cache/nace_family.json")
PROMPT_PATH = Path("ai/prompts/nace_family_v1.txt")

_AI_MODES = frozenset({"mock", "live"})


class LiveProviderNotConfigured(RuntimeError):
    """``AI_MODE=live`` est demandé alors qu'aucun fournisseur n'est branché."""


class CacheAnswer(BaseModel):
    """Une réponse rejouée depuis le cache, pour un code NACE."""

    activity_family: str
    confidence: float = Field(ge=0, le=1)


class NaceCache(BaseModel):
    """Fichier ``ai/cache`` : modèle, version de prompt, réponses par code."""

    model_name: str = Field(min_length=1)
    prompt_version: str
    answers: dict[str, CacheAnswer]


@dataclass(frozen=True)
class ActivityPrediction:
    """Famille proposée pour un code, avec le motif de revue éventuel."""

    nace_code: str
    activity_family: str | None
    confidence: float
    method: str
    model_name: str | None
    prompt_version: str | None
    input_text: str | None
    output_text: str | None
    review_reason: str | None


@dataclass(frozen=True)
class ClassifyResult:
    """Bilan d'un classement écrit en base."""

    codes: int
    by_rule: int
    by_ai: int
    to_review: int


@dataclass(frozen=True)
class GoldNaceRow:
    """Ligne du fichier d'évaluation. Le libellé n'est pas une vérité métier."""

    nace_code: str
    nace_label: str
    activity_family: str
    label_verified: bool


@dataclass(frozen=True)
class NaceEvalResult:
    """Accord entre le classeur et le fichier d'évaluation."""

    scored: int
    agreed: int
    unverified: int
    below_threshold: int
    predictions: tuple[ActivityPrediction, ...]

    @property
    def agreement(self) -> float:
        """Part des codes dont la famille prédite est celle du fichier."""
        if self.scored == 0:
            return 0.0
        return self.agreed / self.scored


def classify_nace(
    nace_code: str,
    nace_label: str = "",
    *,
    mode: str = "mock",
    threshold: float = CONFIDENCE_THRESHOLD,
    cache_path: Path = NACE_CACHE,
) -> ActivityPrediction:
    """Choisit la famille d'un code NACE.

    Parameters
    ----------
    nace_code :
        Quatre chiffres, sans point.
    nace_label :
        Libellé montré au modèle. Inutile pour une règle.
    mode :
        ``mock`` (cache) ou ``live`` (non branché).
    threshold :
        Confiance en dessous de laquelle une réponse de modèle part en revue.
    cache_path :
        Fichier JSON lu seulement si la règle ne répond pas.

    Returns
    -------
    ActivityPrediction
        Famille, méthode (``rule``, ``ai`` ou ``unresolved``) et motif de revue.

    Raises
    ------
    ValueError
        ``mode`` inconnu, ou version de prompt du cache différente du code.
    LiveProviderNotConfigured
        Le code n'a pas de règle et ``mode`` vaut ``live``.
    FileNotFoundError
        Le cache ou le prompt manque alors que la règle ne répond pas.
    ValidationError
        Le JSON du cache n'a pas la forme attendue.
    """
    if mode not in _AI_MODES:
        raise ValueError(f"unknown AI_MODE {mode}")
    code = nace_code.strip()
    family = _rule_family(code)
    if family is not None:
        return ActivityPrediction(
            nace_code=code,
            activity_family=family,
            confidence=1.0,
            method="rule",
            model_name=None,
            prompt_version=None,
            input_text=None,
            output_text=family,
            review_reason=None,
        )
    if mode == "live":
        raise LiveProviderNotConfigured(
            "AI_MODE=live n'a pas de fournisseur : aucun format d'API n'est inventé."
        )
    return _from_cache(code, nace_label, threshold=threshold, cache_path=cache_path)


def load_gold(path: Path = GOLD_PATH) -> list[GoldNaceRow]:
    """Lit le fichier d'évaluation.

    Parameters
    ----------
    path :
        CSV ``nace_code``, ``nace_label``, ``activity_family``, ``label_verified``.

    Returns
    -------
    list[GoldNaceRow]
        Lignes dans l'ordre du fichier.

    Raises
    ------
    ValueError
        Code en double, famille hors liste, ou ``label_verified`` illisible.
    """
    rows: list[GoldNaceRow] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            code = (raw.get("nace_code") or "").strip()
            label = (raw.get("nace_label") or "").strip()
            family = (raw.get("activity_family") or "").strip()
            flag = (raw.get("label_verified") or "").strip().lower()
            if code in seen:
                raise ValueError(f"duplicate nace code {code}")
            if not label:
                raise ValueError(f"missing label for {code}")
            if family not in ACTIVITY_FAMILIES:
                raise ValueError(f"activity family outside the closed list: {family}")
            if flag not in {"true", "false"}:
                raise ValueError(f"label_verified must be true or false for {code}")
            seen.add(code)
            rows.append(
                GoldNaceRow(
                    nace_code=code,
                    nace_label=label,
                    activity_family=family,
                    label_verified=flag == "true",
                )
            )
    return rows


def evaluate_gold(
    path: Path = GOLD_PATH,
    *,
    mode: str = "mock",
    threshold: float = CONFIDENCE_THRESHOLD,
) -> NaceEvalResult:
    """Compare le classeur au fichier d'évaluation.

    Le taux n'est pas une exactitude validée : ``label_verified`` reste faux
    tant que les libellés n'ont pas été relus.

    Parameters
    ----------
    path :
        CSV d'évaluation.
    mode :
        ``mock`` ou ``live``.
    threshold :
        Seuil de confiance transmis au classeur.

    Returns
    -------
    NaceEvalResult
        Accord, libellés non relus, et prédictions dans l'ordre du fichier.
    """
    rows = load_gold(path)
    predictions = tuple(
        classify_nace(
            row.nace_code,
            row.nace_label,
            mode=mode,
            threshold=threshold,
        )
        for row in rows
    )
    agreed = sum(
        1
        for row, prediction in zip(rows, predictions, strict=True)
        if prediction.activity_family == row.activity_family
    )
    return NaceEvalResult(
        scored=len(rows),
        agreed=agreed,
        unverified=sum(1 for row in rows if not row.label_verified),
        below_threshold=sum(
            1 for prediction in predictions if prediction.review_reason
        ),
        predictions=predictions,
    )


def classify_loaded_enterprises(
    connection: PgConnection,
    *,
    mode: str = "mock",
    threshold: float = CONFIDENCE_THRESHOLD,
) -> ClassifyResult:
    """Classe les codes NACE présents dans ``raw.enterprise``.

    Parameters
    ----------
    connection :
        Connexion ouverte avec ``ingest_rw``.
    mode :
        ``mock`` ou ``live``.
    threshold :
        Seuil de la file de revue.

    Returns
    -------
    ClassifyResult
        Nombre de codes, ventilés par méthode et par file de revue.
    """
    found = connection.execute(
        "SELECT DISTINCT nace_code FROM raw.enterprise ORDER BY nace_code"
    ).fetchall()
    codes = [row[0] for row in found]
    return classify_codes(
        connection,
        codes,
        source_name=SOURCE_NAME,
        mode=mode,
        threshold=threshold,
        replace_review=True,
    )


def classify_codes(
    connection: PgConnection,
    codes: list[str],
    *,
    source_name: str,
    mode: str = "mock",
    threshold: float = CONFIDENCE_THRESHOLD,
    replace_review: bool = True,
) -> ClassifyResult:
    """Classe une liste de codes et remplace la file de revue de la source.

    Parameters
    ----------
    connection :
        Connexion ouverte avec ``ingest_rw``.
    codes :
        Codes NACE, les doublons sont ignorés.
    source_name :
        Valeur écrite dans ``raw.nace_activity`` et ``ops.ai_log``.
    mode :
        ``mock`` ou ``live``.
    threshold :
        Seuil de la file de revue.
    replace_review :
        Si vrai, la file de cette source redevient exactement les codes
        sous le seuil de cet appel.

    Returns
    -------
    ClassifyResult
        Bilan de cet appel.
    """
    unique_codes = list(dict.fromkeys(codes))
    predictions = [
        classify_nace(code, mode=mode, threshold=threshold) for code in unique_codes
    ]
    _write_predictions(
        connection,
        predictions,
        source_name=source_name,
        replace_review=replace_review,
    )
    return _summarize(predictions)


def log_ai_calls(
    connection: PgConnection,
    predictions: tuple[ActivityPrediction, ...] | list[ActivityPrediction],
    *,
    source_name: str,
) -> int:
    """Ajoute au journal les appels qui ne sont pas une règle.

    Parameters
    ----------
    connection :
        Connexion ouverte avec ``ingest_rw``.
    predictions :
        Résultats déjà calculés. Les règles ne sont pas journalisées.
    source_name :
        Origine de l'appel, par exemple ``nace_eval``.

    Returns
    -------
    int
        Nombre de lignes ajoutées.
    """
    calls = [item for item in predictions if item.method != "rule"]
    _ensure_tables(connection)
    _insert_logs(connection, calls, source_name)
    connection.commit()
    return len(calls)


def _rule_family(nace_code: str) -> str | None:
    """Famille certaine d'après la section NACE, sinon ``None``.

    Sections couvertes : C industrie, F construction, G commerce,
    H logistique, I à N services. Le reste (agriculture, extractif,
    énergie, eau et déchets, administration, éducation, santé, arts)
    n'a pas une seule famille dans la liste : on ne devine pas ici.
    """
    if len(nace_code) != 4 or not nace_code.isdigit():
        return None
    division = int(nace_code[:2])
    if 10 <= division <= 33:
        return "industrie"
    if 41 <= division <= 43:
        return "construction"
    if 45 <= division <= 47:
        return "commerce"
    if 49 <= division <= 53:
        return "logistique"
    if 55 <= division <= 56 or 58 <= division <= 66 or division == 68:
        return "services"
    if 69 <= division <= 75 or 77 <= division <= 82:
        return "services"
    return None


def _from_cache(
    nace_code: str,
    nace_label: str,
    *,
    threshold: float,
    cache_path: Path,
) -> ActivityPrediction:
    """Rejoue la réponse du cache, ou signale une absence."""
    cache = load_nace_cache(cache_path)
    prompt = _prompt(nace_code, nace_label)
    answer = cache.answers.get(nace_code)
    if answer is None:
        return _unresolved(
            nace_code,
            prompt,
            cache,
            output_text="unresolved",
            review_reason="no cached answer",
        )
    if answer.activity_family not in ACTIVITY_FAMILIES:
        return _unresolved(
            nace_code,
            prompt,
            cache,
            output_text=answer.activity_family,
            review_reason="activity family outside the closed list",
        )
    reason = None
    if answer.confidence < threshold:
        reason = "confidence below threshold"
    return ActivityPrediction(
        nace_code=nace_code,
        activity_family=answer.activity_family,
        confidence=answer.confidence,
        method="ai",
        model_name=cache.model_name,
        prompt_version=cache.prompt_version,
        input_text=prompt,
        output_text=answer.activity_family,
        review_reason=reason,
    )


def _unresolved(
    nace_code: str,
    prompt: str,
    cache: NaceCache,
    *,
    output_text: str,
    review_reason: str,
) -> ActivityPrediction:
    """Réponse inutilisable : pas de famille, et une place en revue."""
    return ActivityPrediction(
        nace_code=nace_code,
        activity_family=None,
        confidence=0.0,
        method="unresolved",
        model_name=cache.model_name,
        prompt_version=cache.prompt_version,
        input_text=prompt,
        output_text=output_text,
        review_reason=review_reason,
    )


def load_nace_cache(path: Path = NACE_CACHE) -> NaceCache:
    """Charge le cache mock et vérifie la version du prompt.

    Parameters
    ----------
    path :
        JSON du cache.

    Returns
    -------
    NaceCache
        Réponses indexées par code NACE.

    Raises
    ------
    ValueError
        La version du prompt ne correspond pas au code.
    ValidationError
        Le JSON n'a pas la forme attendue.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    cache = NaceCache.model_validate(payload)
    if cache.prompt_version != PROMPT_VERSION:
        raise ValueError(f"cache prompt {cache.prompt_version} != {PROMPT_VERSION}")
    return cache


def _prompt(nace_code: str, nace_label: str) -> str:
    """Remplit le prompt versionné. Le libellé vide devient un marqueur."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    label = nace_label.strip() or "libellé inconnu"
    return text.replace("{nace_code}", nace_code).replace("{nace_label}", label)


def _write_predictions(
    connection: PgConnection,
    predictions: list[ActivityPrediction],
    *,
    source_name: str,
    replace_review: bool,
) -> None:
    """Upsert des familles, journal des appels, file de revue du dernier passage."""
    _ensure_tables(connection)
    kept = [item for item in predictions if item.activity_family is not None]
    if kept:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO raw.nace_activity (
                    nace_code, activity_family, method, confidence,
                    model_name, prompt_version, source_name
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (nace_code) DO UPDATE SET
                    activity_family = EXCLUDED.activity_family,
                    method = EXCLUDED.method,
                    confidence = EXCLUDED.confidence,
                    model_name = EXCLUDED.model_name,
                    prompt_version = EXCLUDED.prompt_version,
                    source_name = EXCLUDED.source_name
                """,
                [
                    (
                        item.nace_code,
                        item.activity_family,
                        item.method,
                        item.confidence,
                        item.model_name,
                        item.prompt_version,
                        source_name,
                    )
                    for item in kept
                ],
            )
    _insert_logs(
        connection,
        [item for item in predictions if item.method != "rule"],
        source_name,
    )
    if replace_review:
        connection.execute(
            "DELETE FROM ops.review_queue WHERE source_name = %s",
            (source_name,),
        )
        queued = [item for item in predictions if item.review_reason]
        if queued:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO ops.review_queue (
                        source_name, entity_key, reason, payload
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    [
                        (
                            source_name,
                            item.nace_code,
                            item.review_reason,
                            item.input_text or item.nace_code,
                        )
                        for item in queued
                    ],
                )
    connection.commit()


def _insert_logs(
    connection: PgConnection,
    calls: list[ActivityPrediction],
    source_name: str,
) -> None:
    """Ajoute une ligne de journal par appel. Une règle n'est pas un appel."""
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
                    item.input_text or "",
                    item.output_text or "",
                    item.model_name or MODEL_NAME,
                    item.prompt_version or PROMPT_VERSION,
                    item.confidence,
                )
                for item in calls
            ],
        )


def _summarize(predictions: list[ActivityPrediction]) -> ClassifyResult:
    """Compte règles, réponses de cache et lignes à relire."""
    return ClassifyResult(
        codes=len(predictions),
        by_rule=sum(1 for item in predictions if item.method == "rule"),
        by_ai=sum(1 for item in predictions if item.method == "ai"),
        to_review=sum(1 for item in predictions if item.review_reason),
    )


def _ensure_tables(connection: PgConnection) -> None:
    """Crée la table de familles, le journal d'appels et la file de revue."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.nace_activity (
            nace_code text PRIMARY KEY,
            activity_family text NOT NULL,
            method text NOT NULL,
            confidence numeric NOT NULL,
            model_name text,
            prompt_version text,
            source_name text NOT NULL,
            CHECK (activity_family IN (
                'industrie', 'logistique', 'commerce',
                'services', 'construction', 'autre'
            )),
            CHECK (method IN ('rule', 'ai')),
            CHECK (confidence >= 0 AND confidence <= 1),
            CHECK (char_length(nace_code) = 4)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ops.ai_log (
            ai_log_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source_name text NOT NULL,
            input_text text NOT NULL,
            output_text text NOT NULL,
            model_name text NOT NULL,
            prompt_version text NOT NULL,
            confidence numeric NOT NULL,
            called_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ops.review_queue (
            review_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source_name text NOT NULL,
            entity_key text NOT NULL,
            reason text NOT NULL,
            payload text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
