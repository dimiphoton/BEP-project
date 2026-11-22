"""Population communale : fichier Statbel, validation, quarantaine, upsert."""

from __future__ import annotations

import csv
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from observatory.db import PgConnection

# Province de Namur dans le référentiel REFNIS Statbel.
NAMUR_PROVINCE_NIS_CODE = "90000"
REFERENCE_YEAR = 2025
SOURCE_NAME = "statbel_tf_soc_pop_struct_2025"

RAW_ZIP = Path("data/raw/TF_SOC_POP_STRUCT_2025.zip")
SAMPLE_CSV = Path("data/sample/statbel_population_namur_2025.csv")

# Colonnes du TXT pipe Statbel « Population par lieu de résidence… ».
_EXPECTED_COLUMNS = 21
_COLUMN_NIS = 0
_COLUMN_NAME_FR = 2
_COLUMN_PROVINCE = 6
_COLUMN_POPULATION = 20

_CSV_FIELDS = (
    "nis_code",
    "municipality_name",
    "province_nis_code",
    "population",
    "reference_year",
)


class StatbelCell(BaseModel):
    """Une cellule du fichier détaillé (âge, sexe, nationalité, état civil)."""

    nis_code: str = Field(pattern=r"^\d{5}$")
    municipality_name: str = Field(min_length=1)
    province_nis_code: str = Field(pattern=r"^\d{5}$")
    population: int = Field(ge=0)


class MunicipalityPopulation(BaseModel):
    """Population totale d'une commune de la province de Namur."""

    nis_code: str = Field(pattern=r"^(91|92|93)\d{3}$")
    municipality_name: str = Field(min_length=1)
    province_nis_code: str = Field(pattern=r"^90000$")
    population: int = Field(ge=0)
    reference_year: int = Field(ge=2000, le=2100)


@dataclass(frozen=True)
class RejectedLine:
    """Ligne refusée, avec le motif qui partira dans ``ops.rejects``."""

    line_number: int
    payload: str
    reason: str


@dataclass(frozen=True)
class IngestResult:
    """Bilan d'un chargement."""

    loaded: int
    rejected: int
    source: Path


def resolve_population_source() -> Path:
    """Choisit le zip Statbel s'il est là, sinon l'extrait versionné.

    Returns
    -------
    Path
        Fichier à lire.

    Raises
    ------
    FileNotFoundError
        Ni le zip ni l'échantillon ne sont sur le disque.
    """
    if RAW_ZIP.exists():
        return RAW_ZIP
    if SAMPLE_CSV.exists():
        return SAMPLE_CSV
    raise FileNotFoundError(
        "Aucun fichier de population. Attendus : "
        f"{RAW_ZIP.as_posix()} ou {SAMPLE_CSV.as_posix()}."
    )


def load_population(
    path: Path,
) -> tuple[list[MunicipalityPopulation], list[RejectedLine]]:
    """Lit un zip Statbel ou un CSV déjà agrégé.

    Le zip détaille chaque commune par âge, sexe, nationalité et état civil.
    Seule la province de Namur est gardée, puis la population est sommée.
    Les autres provinces ne sont pas des rejets : elles sont hors périmètre.
    Une ligne illisible va en quarantaine, le reste du fichier continue.

    Parameters
    ----------
    path :
        Zip ``.txt`` pipe, ou CSV ``nis_code,municipality_name,...``.

    Returns
    -------
    tuple[list[MunicipalityPopulation], list[RejectedLine]]
        Communes valides, triées par code INS, et lignes refusées.
    """
    if path.suffix.lower() == ".zip":
        return _load_statbel_zip(path)
    return _load_sample_csv(path)


def ingest_population(connection: PgConnection, path: Path) -> IngestResult:
    """Charge les communes dans ``raw`` et les rejets dans ``ops``.

    L'upsert suit ``nis_code``. Les rejets de cette source sont remplacés
    par ceux du passage en cours : la quarantaine décrit le dernier run.

    Parameters
    ----------
    connection :
        Connexion ouverte avec le rôle ``ingest_rw``.
    path :
        Fichier Statbel ou extrait CSV.

    Returns
    -------
    IngestResult
        Nombre de communes écrites et de lignes refusées.
    """
    records, rejected = load_population(path)
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
    if records:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO raw.municipality_population (
                    nis_code, municipality_name, province_nis_code,
                    population, reference_year, source_name
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (nis_code) DO UPDATE SET
                    municipality_name = EXCLUDED.municipality_name,
                    province_nis_code = EXCLUDED.province_nis_code,
                    population = EXCLUDED.population,
                    reference_year = EXCLUDED.reference_year,
                    source_name = EXCLUDED.source_name
                """,
                [
                    (
                        record.nis_code,
                        record.municipality_name,
                        record.province_nis_code,
                        record.population,
                        record.reference_year,
                        SOURCE_NAME,
                    )
                    for record in records
                ],
            )
    connection.commit()
    return IngestResult(loaded=len(records), rejected=len(rejected), source=path)


def _load_statbel_zip(
    path: Path,
) -> tuple[list[MunicipalityPopulation], list[RejectedLine]]:
    """Agrège le TXT pipe contenu dans le zip Statbel."""
    with zipfile.ZipFile(path) as archive:
        text_names = [name for name in archive.namelist() if name.endswith(".txt")]
        if len(text_names) != 1:
            raise ValueError(f"Expected one txt in {path.name}, found {text_names}")
        with archive.open(text_names[0]) as handle:
            lines = handle.read().decode("utf-8-sig").splitlines()
    return _aggregate_statbel_lines(lines)


def _aggregate_statbel_lines(
    lines: list[str],
) -> tuple[list[MunicipalityPopulation], list[RejectedLine]]:
    """Somme la population des cellules de la province de Namur."""
    rejected: list[RejectedLine] = []
    # La première cellule fixe le nom français. Les suivantes ajoutent des habitants.
    buckets: dict[str, dict[str, object]] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("CD_REFNIS"):
            continue
        try:
            cell = _parse_statbel_line(stripped)
        except (ValueError, ValidationError) as exc:
            rejected.append(RejectedLine(line_number, stripped[:500], _reason(exc)))
            continue
        if cell.province_nis_code != NAMUR_PROVINCE_NIS_CODE:
            continue
        current = buckets.get(cell.nis_code)
        if current is None:
            buckets[cell.nis_code] = {
                "nis_code": cell.nis_code,
                "municipality_name": cell.municipality_name,
                "province_nis_code": cell.province_nis_code,
                "population": cell.population,
            }
            continue
        current["population"] = int(current["population"]) + cell.population

    records: list[MunicipalityPopulation] = []
    for nis_code in sorted(buckets):
        payload = buckets[nis_code]
        try:
            records.append(
                MunicipalityPopulation(
                    nis_code=str(payload["nis_code"]),
                    municipality_name=str(payload["municipality_name"]),
                    province_nis_code=str(payload["province_nis_code"]),
                    population=int(payload["population"]),
                    reference_year=REFERENCE_YEAR,
                )
            )
        except ValidationError as exc:
            rejected.append(RejectedLine(0, str(payload), _reason(exc)))
    return records, rejected


def _parse_statbel_line(line: str) -> StatbelCell:
    """Découpe une ligne pipe et valide la cellule.

    Raises
    ------
    ValueError
        Le nombre de colonnes n'est pas celui du fichier Statbel.
    ValidationError
        Code INS, nom ou population illisibles.
    """
    parts = line.split("|")
    if len(parts) != _EXPECTED_COLUMNS:
        raise ValueError(f"expected {_EXPECTED_COLUMNS} columns, got {len(parts)}")
    return StatbelCell(
        nis_code=parts[_COLUMN_NIS].strip(),
        municipality_name=parts[_COLUMN_NAME_FR].strip(),
        province_nis_code=parts[_COLUMN_PROVINCE].strip(),
        population=parts[_COLUMN_POPULATION].strip(),
    )


def _load_sample_csv(
    path: Path,
) -> tuple[list[MunicipalityPopulation], list[RejectedLine]]:
    """Lit l'extrait CSV. Chaque ligne est dans le périmètre, ou en quarantaine."""
    rejected: list[RejectedLine] = []
    records: list[MunicipalityPopulation] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for line_number, row in enumerate(reader, start=2):
            payload = ",".join(row.get(field, "") for field in _CSV_FIELDS)
            try:
                records.append(
                    MunicipalityPopulation(
                        nis_code=(row.get("nis_code") or "").strip(),
                        municipality_name=(row.get("municipality_name") or "").strip(),
                        province_nis_code=(row.get("province_nis_code") or "").strip(),
                        population=(row.get("population") or "").strip(),
                        reference_year=(row.get("reference_year") or "").strip(),
                    )
                )
            except ValidationError as exc:
                rejected.append(RejectedLine(line_number, payload[:500], _reason(exc)))
    records.sort(key=lambda record: record.nis_code)
    return records, rejected


def write_sample_csv(records: list[MunicipalityPopulation], path: Path) -> None:
    """Écrit l'extrait versionné, trié par code INS.

    Parameters
    ----------
    records :
        Communes déjà validées.
    path :
        Destination du CSV.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for record in sorted(records, key=lambda item: item.nis_code):
            writer.writerow(record.model_dump())


def _ensure_tables(connection: PgConnection) -> None:
    """Crée la table brute et la quarantaine si elles n'existent pas encore."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.municipality_population (
            nis_code text PRIMARY KEY,
            municipality_name text NOT NULL,
            province_nis_code text NOT NULL,
            population integer NOT NULL CHECK (population >= 0),
            reference_year integer NOT NULL,
            source_name text NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ops.rejects (
            reject_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source_name text NOT NULL,
            line_number integer,
            payload text NOT NULL,
            reason text NOT NULL,
            rejected_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def _reason(exc: Exception) -> str:
    """Résume une erreur pydantic ou une ligne mal formée."""
    if isinstance(exc, ValidationError):
        return "; ".join(error["msg"] for error in exc.errors())
    return str(exc)


def iter_sample_records(path: Path = SAMPLE_CSV) -> Iterator[MunicipalityPopulation]:
    """Itère les communes de l'extrait, sans les lignes refusées.

    Parameters
    ----------
    path :
        CSV versionné.

    Yields
    ------
    MunicipalityPopulation
        Une commune valide.
    """
    records, rejected = _load_sample_csv(path)
    if rejected:
        raise ValueError(f"{path} contains {len(rejected)} invalid rows")
    yield from records
