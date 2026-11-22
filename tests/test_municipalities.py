"""Population communale : agrégation Statbel, quarantaine, upsert."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from observatory.config import Settings
from observatory.db import connect
from observatory.municipalities import (
    NAMUR_PROVINCE_NIS_CODE,
    RAW_ZIP,
    SAMPLE_CSV,
    SOURCE_NAME,
    MunicipalityPopulation,
    _aggregate_statbel_lines,
    ingest_population,
    iter_sample_records,
    load_population,
)

# Une ligne Statbel : 21 colonnes pipe, population en dernière position.


def _statbel_line(
    nis_code: str,
    name: str,
    province: str,
    population: str,
) -> str:
    """Fabrique une ligne pipe avec le code, le nom français, la province et le total."""
    parts = ["x"] * 21
    parts[0] = nis_code
    parts[2] = name
    parts[6] = province
    parts[20] = population
    return "|".join(parts)


def test_namur_cells_are_summed_and_other_provinces_ignored() -> None:
    """Deux cellules de Namur s'additionnent. Anvers n'entre pas dans la dimension."""
    lines = [
        "CD_REFNIS|header",
        _statbel_line("92094", "Namur", NAMUR_PROVINCE_NIS_CODE, "10"),
        _statbel_line("92094", "Namur", NAMUR_PROVINCE_NIS_CODE, "5"),
        _statbel_line("11001", "Aartselaar", "10000", "99"),
    ]
    records, rejected = _aggregate_statbel_lines(lines)
    assert rejected == []
    assert len(records) == 1
    assert records[0].nis_code == "92094"
    assert records[0].population == 15
    assert records[0].municipality_name == "Namur"


def test_invalid_population_is_quarantined_and_the_file_continues() -> None:
    """Une population illisible est refusée, la commune suivante est gardée."""
    lines = [
        _statbel_line("92094", "Namur", NAMUR_PROVINCE_NIS_CODE, "pas-un-nombre"),
        _statbel_line("91005", "Anhée", NAMUR_PROVINCE_NIS_CODE, "3"),
    ]
    records, rejected = _aggregate_statbel_lines(lines)
    assert len(rejected) == 1
    assert "92094" in rejected[0].payload
    assert len(records) == 1
    assert records[0].nis_code == "91005"


def test_wrong_column_count_is_quarantined() -> None:
    """Une ligne trop courte ne casse pas la lecture."""
    records, rejected = _aggregate_statbel_lines(["seulement|trois|champs"])
    assert records == []
    assert len(rejected) == 1
    assert "columns" in rejected[0].reason


def test_sample_csv_rejects_a_bad_row(tmp_path: Path) -> None:
    """Dans l'extrait, une ligne hors contrat va en quarantaine."""
    path = tmp_path / "population.csv"
    path.write_text(
        "nis_code,municipality_name,province_nis_code,population,reference_year\n"
        "92094,Namur,90000,10,2025\n"
        "92094,Namur,90000,-1,2025\n"
        "11001,Aartselaar,10000,4,2025\n",
        encoding="utf-8",
    )
    records, rejected = load_population(path)
    assert [record.nis_code for record in records] == ["92094"]
    assert len(rejected) == 2


def test_sample_file_covers_namur_only() -> None:
    """L'extrait versionné ne contient que des communes namuroises, sans doublon."""
    records = list(iter_sample_records())
    assert records
    codes = [record.nis_code for record in records]
    assert codes == sorted(set(codes))
    for record in records:
        assert record.province_nis_code == NAMUR_PROVINCE_NIS_CODE
        assert record.population > 0
        assert record.reference_year == 2025


def test_zip_matches_sample_when_the_archive_is_present() -> None:
    """Si le zip Statbel est là, l'extrait versionné doit être son agrégat exact."""
    if not RAW_ZIP.exists():
        pytest.skip("zip Statbel absent")
    from_zip, rejected = load_population(RAW_ZIP)
    from_sample = list(iter_sample_records())
    assert rejected == []
    assert from_zip == from_sample


def _connect_or_skip(settings: Settings) -> psycopg.Connection:
    """Ouvre la base avec le rôle d'ingestion, ou saute le test si elle est arrêtée."""
    try:
        return connect(
            settings,
            user=settings.ingest_user,
            password=settings.ingest_password,
        )
    except psycopg.OperationalError as exc:
        text = str(exc).lower()
        offline = (
            "could not connect" in text
            or "connection refused" in text
            or "timeout" in text
            or "could not translate" in text
        )
        if offline:
            pytest.skip(f"Postgres indisponible : {exc}")
        raise


@pytest.mark.integration
def test_ingest_is_idempotent_and_keeps_valid_rows(tmp_path: Path) -> None:
    """Rejouer le chargement ne duplique pas les communes, et une ligne fausse est isolée."""
    settings = Settings.from_env()
    if not settings.ingest_password:
        pytest.skip("INGEST_PASSWORD vide")
    sample = list(iter_sample_records())
    bad_path = tmp_path / "bad.csv"
    bad_path.write_text(
        "nis_code,municipality_name,province_nis_code,population,reference_year\n"
        f"{sample[0].nis_code},{sample[0].municipality_name},90000,1,2025\n"
        "abc,Inconnue,90000,1,2025\n",
        encoding="utf-8",
    )
    with _connect_or_skip(settings) as connection:
        try:
            bad_result = ingest_population(connection, bad_path)
            assert bad_result.loaded == 1
            assert bad_result.rejected == 1
            stored = connection.execute(
                """
                SELECT count(*)
                FROM ops.rejects
                WHERE source_name = %s
                """,
                (SOURCE_NAME,),
            ).fetchone()
            assert stored is not None
            assert stored[0] == 1
        finally:
            ingest_population(connection, SAMPLE_CSV)
        count_row = connection.execute(
            "SELECT count(*), coalesce(sum(population), 0) FROM raw.municipality_population"
        ).fetchone()
        again = ingest_population(connection, SAMPLE_CSV)
    assert count_row is not None
    assert count_row[0] == len(sample)
    assert count_row[1] == sum(record.population for record in sample)
    assert again.loaded == len(sample)
    assert again.rejected == 0


def test_municipality_model_rejects_a_code_outside_namur() -> None:
    """Le contrat de la dimension refuse un code INS hors province."""
    with pytest.raises(ValueError):
        MunicipalityPopulation(
            nis_code="11001",
            municipality_name="Aartselaar",
            province_nis_code="90000",
            population=1,
            reference_year=2025,
        )
