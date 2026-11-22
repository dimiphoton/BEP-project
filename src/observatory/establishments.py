"""Établissements synthétiques, rattachés aux communes réelles de Namur.

La BCE Open Data ne se télécharge pas sans compte. Ce module charge
l'échantillon ``synthetic_establishments`` à la place.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

from observatory.db import PgConnection
from observatory.municipalities import IngestResult, RejectedLine, iter_sample_records

ESTABLISHMENT_COUNT = 300
ENTERPRISE_COUNT = 250
SOURCE_NAME = "synthetic_establishments"
ESTABLISHMENT_SAMPLE = Path("data/sample/synthetic_establishments.csv")

# Codes NACE réels, affectés au hasard contrôlé : ce n'est pas l'activité observée.
_NACE_CODES = ("1011", "4120", "4321", "4711", "4941", "5210", "6201", "6820")
_GENERATOR_SEED = 20251122

_CSV_FIELDS = (
    "establishment_number",
    "enterprise_number",
    "enterprise_name",
    "establishment_name",
    "nis_code",
    "nace_code",
)


class EstablishmentRecord(BaseModel):
    """Un établissement synthétique situé dans une commune de Namur."""

    establishment_number: str
    enterprise_number: str
    enterprise_name: str = Field(min_length=1)
    establishment_name: str = Field(min_length=1)
    nis_code: str = Field(pattern=r"^(91|92|93)\d{3}$")
    nace_code: str = Field(pattern=r"^\d{4}$")

    @field_validator("establishment_number")
    @classmethod
    def _establishment_number_ok(cls, value: str) -> str:
        if not value.startswith("2") or not belgian_check_digits_ok(value):
            raise ValueError("invalid establishment number")
        return value

    @field_validator("enterprise_number")
    @classmethod
    def _enterprise_number_ok(cls, value: str) -> str:
        if not value.startswith("0") or not belgian_check_digits_ok(value):
            raise ValueError("invalid enterprise number")
        return value


class EnterpriseRecord(BaseModel):
    """Entreprise déduite des établissements, une ligne par numéro BCE."""

    enterprise_number: str
    enterprise_name: str = Field(min_length=1)
    nace_code: str = Field(pattern=r"^\d{4}$")


def belgian_check_digits_ok(number: str) -> bool:
    """Vérifie la clé des numéros BCE : 97 moins le reste du numéro sur 97.

    Parameters
    ----------
    number :
        Dix chiffres, clé comprise.

    Returns
    -------
    bool
        True si la clé correspond aux huit premiers chiffres.
    """
    if len(number) != 10 or not number.isdigit():
        return False
    expected = 97 - (int(number[:8]) % 97)
    return int(number[8:]) == expected


def belgian_number(first_eight: str) -> str:
    """Ajoute la clé BCE à huit chiffres.

    Parameters
    ----------
    first_eight :
        Huit chiffres, sans la clé.

    Returns
    -------
    str
        Numéro sur dix chiffres.
    """
    check = 97 - (int(first_eight) % 97)
    return f"{first_eight}{check:02d}"


def build_synthetic_establishments(
    nis_codes: list[str],
) -> list[EstablishmentRecord]:
    """Construit 300 établissements sur les communes fournies.

    Les 50 derniers établissements sont un second site des 50 premières
    entreprises, pour que le fait et la dimension n'aient pas le même grain.

    Parameters
    ----------
    nis_codes :
        Codes INS réels, en général les 38 communes de la province.

    Returns
    -------
    list[EstablishmentRecord]
        Établissements triés par numéro.
    """
    if not nis_codes:
        raise ValueError("nis_codes is empty")
    codes = sorted(set(nis_codes))
    rng = random.Random(_GENERATOR_SEED)
    enterprises: list[tuple[str, str, str]] = []
    for index in range(1, ENTERPRISE_COUNT + 1):
        number = belgian_number(f"0{index:07d}")
        name = f"Synthetic firm {index:03d}"
        nace = _NACE_CODES[(index - 1) % len(_NACE_CODES)]
        enterprises.append((number, name, nace))

    rows: list[EstablishmentRecord] = []
    for index in range(1, ESTABLISHMENT_COUNT + 1):
        enterprise_index = (
            index if index <= ENTERPRISE_COUNT else index - ENTERPRISE_COUNT
        )
        enterprise_number, enterprise_name, nace = enterprises[enterprise_index - 1]
        rows.append(
            EstablishmentRecord(
                establishment_number=belgian_number(f"2{index:07d}"),
                enterprise_number=enterprise_number,
                enterprise_name=enterprise_name,
                establishment_name=f"Synthetic site {index:03d}",
                nis_code=rng.choice(codes),
                nace_code=nace,
            )
        )
    rows.sort(key=lambda record: record.establishment_number)
    return rows


def load_establishments(
    path: Path,
    allowed_nis_codes: set[str],
) -> tuple[list[EstablishmentRecord], list[EnterpriseRecord], list[RejectedLine]]:
    """Lit le CSV. Une ligne invalide part en quarantaine, les autres restent.

    Une commune absente de ``allowed_nis_codes`` est refusée même si le
    code a la forme d'un INS namurois : l'établissement doit viser une
    commune déjà connue.

    Parameters
    ----------
    path :
        CSV synthétique.
    allowed_nis_codes :
        Codes INS acceptés, ceux de ``dim_municipality``.

    Returns
    -------
    tuple[list[EstablishmentRecord], list[EnterpriseRecord], list[RejectedLine]]
        Établissements gardés, entreprises déduites, lignes refusées.
    """
    rejected: list[RejectedLine] = []
    kept: list[EstablishmentRecord] = []
    enterprises: dict[str, EnterpriseRecord] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for line_number, row in enumerate(reader, start=2):
            payload = ",".join(row.get(field, "") or "" for field in _CSV_FIELDS)
            try:
                record = EstablishmentRecord(
                    establishment_number=(
                        row.get("establishment_number") or ""
                    ).strip(),
                    enterprise_number=(row.get("enterprise_number") or "").strip(),
                    enterprise_name=(row.get("enterprise_name") or "").strip(),
                    establishment_name=(row.get("establishment_name") or "").strip(),
                    nis_code=(row.get("nis_code") or "").strip(),
                    nace_code=(row.get("nace_code") or "").strip(),
                )
            except ValidationError as exc:
                rejected.append(RejectedLine(line_number, payload[:500], _reason(exc)))
                continue
            if record.nis_code not in allowed_nis_codes:
                rejected.append(
                    RejectedLine(
                        line_number,
                        payload[:500],
                        "nis_code is not a known Namur municipality",
                    )
                )
                continue
            known = enterprises.get(record.enterprise_number)
            if known is None:
                enterprises[record.enterprise_number] = EnterpriseRecord(
                    enterprise_number=record.enterprise_number,
                    enterprise_name=record.enterprise_name,
                    nace_code=record.nace_code,
                )
            elif known.enterprise_name != record.enterprise_name:
                rejected.append(
                    RejectedLine(
                        line_number,
                        payload[:500],
                        "enterprise name conflicts with a previous row",
                    )
                )
                continue
            kept.append(record)
    kept.sort(key=lambda record: record.establishment_number)
    enterprise_rows = sorted(
        enterprises.values(),
        key=lambda record: record.enterprise_number,
    )
    return kept, enterprise_rows, rejected


def write_establishment_csv(records: list[EstablishmentRecord], path: Path) -> None:
    """Écrit l'échantillon versionné.

    Parameters
    ----------
    records :
        Établissements déjà validés.
    path :
        Destination du CSV.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.model_dump())


def ingest_establishments(connection: PgConnection, path: Path) -> IngestResult:
    """Charge entreprises et établissements, et remplace les rejets de la source.

    Parameters
    ----------
    connection :
        Connexion ouverte avec ``ingest_rw``.
    path :
        CSV synthétique.

    Returns
    -------
    IngestResult
        Nombre d'établissements écrits et de lignes refusées.
    """
    allowed = {record.nis_code for record in iter_sample_records()}
    establishments, enterprises, rejected = load_establishments(path, allowed)
    _ensure_tables(connection)
    connection.execute(
        "DELETE FROM ops.rejects WHERE source_name = %s",
        (SOURCE_NAME,),
    )
    if rejected:
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
    if enterprises:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO raw.enterprise (
                    enterprise_number, enterprise_name, nace_code, source_name
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (enterprise_number) DO UPDATE SET
                    enterprise_name = EXCLUDED.enterprise_name,
                    nace_code = EXCLUDED.nace_code,
                    source_name = EXCLUDED.source_name
                """,
                [
                    (
                        record.enterprise_number,
                        record.enterprise_name,
                        record.nace_code,
                        SOURCE_NAME,
                    )
                    for record in enterprises
                ],
            )
    if establishments:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO raw.establishment (
                    establishment_number, enterprise_number, establishment_name,
                    nis_code, nace_code, source_name
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (establishment_number) DO UPDATE SET
                    enterprise_number = EXCLUDED.enterprise_number,
                    establishment_name = EXCLUDED.establishment_name,
                    nis_code = EXCLUDED.nis_code,
                    nace_code = EXCLUDED.nace_code,
                    source_name = EXCLUDED.source_name
                """,
                [
                    (
                        record.establishment_number,
                        record.enterprise_number,
                        record.establishment_name,
                        record.nis_code,
                        record.nace_code,
                        SOURCE_NAME,
                    )
                    for record in establishments
                ],
            )
    connection.commit()
    return IngestResult(
        loaded=len(establishments),
        rejected=len(rejected),
        source=path,
    )


def _ensure_tables(connection: PgConnection) -> None:
    """Crée les tables brutes entreprises et établissements."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.enterprise (
            enterprise_number text PRIMARY KEY,
            enterprise_name text NOT NULL,
            nace_code text NOT NULL,
            source_name text NOT NULL,
            CHECK (char_length(enterprise_number) = 10)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.establishment (
            establishment_number text PRIMARY KEY,
            enterprise_number text NOT NULL,
            establishment_name text NOT NULL,
            nis_code text NOT NULL,
            nace_code text NOT NULL,
            source_name text NOT NULL,
            CHECK (char_length(establishment_number) = 10)
        )
        """
    )


def _reason(exc: ValidationError) -> str:
    """Résume une erreur pydantic pour la quarantaine."""
    return "; ".join(error["msg"] for error in exc.errors())
