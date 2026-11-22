"""Établissements synthétiques : clé BCE, commune réelle, upsert."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from observatory.config import Settings
from observatory.db import connect
from observatory.establishments import (
    ENTERPRISE_COUNT,
    ESTABLISHMENT_COUNT,
    ESTABLISHMENT_SAMPLE,
    SOURCE_NAME,
    belgian_check_digits_ok,
    belgian_number,
    build_synthetic_establishments,
    ingest_establishments,
    load_establishments,
    write_establishment_csv,
)
from observatory.municipalities import (
    SAMPLE_CSV,
    ingest_population,
    iter_sample_records,
)


def _nis_codes() -> list[str]:
    return sorted(record.nis_code for record in iter_sample_records())


def test_belgian_check_digits_round_trip() -> None:
    """La clé ajoutée est celle que le contrôle accepte."""
    number = belgian_number("01234567")
    assert belgian_check_digits_ok(number)
    assert not belgian_check_digits_ok(number[:-1] + "00")


def test_synthetic_sample_has_300_sites_on_real_municipalities() -> None:
    """L'échantillon versionné est exactement le générateur, sur les communes Namur."""
    codes = _nis_codes()
    generated = build_synthetic_establishments(codes)
    loaded, enterprises, rejected = load_establishments(
        ESTABLISHMENT_SAMPLE,
        set(codes),
    )
    assert rejected == []
    assert loaded == generated
    assert len(loaded) == ESTABLISHMENT_COUNT
    assert len(enterprises) == ENTERPRISE_COUNT
    assert {row.nis_code for row in loaded} <= set(codes)


def test_unknown_municipality_is_quarantined(tmp_path: Path) -> None:
    """Un code INS hors liste est refusé, l'établissement suivant est gardé."""
    codes = _nis_codes()
    good = build_synthetic_establishments(codes)[0]
    path = tmp_path / "mixed.csv"
    write_establishment_csv(
        [
            good,
            good.model_copy(
                update={
                    "nis_code": "91004",
                    "establishment_number": belgian_number("20000002"),
                }
            ),
        ],
        path,
    )
    # 91004 a la forme d'un INS namurois mais n'est pas une commune du référentiel.
    kept, _enterprises, rejected = load_establishments(path, set(codes))
    assert [row.establishment_number for row in kept] == [good.establishment_number]
    assert len(rejected) == 1
    assert "not a known Namur municipality" in rejected[0].reason


def test_bad_check_digit_is_quarantined(tmp_path: Path) -> None:
    """Un numéro BCE faux ne bloque pas le reste du fichier."""
    codes = _nis_codes()
    good = build_synthetic_establishments(codes)[0]
    path = tmp_path / "bad_number.csv"
    path.write_text(
        "establishment_number,enterprise_number,enterprise_name,establishment_name,nis_code,nace_code\n"
        f"{good.establishment_number},{good.enterprise_number},{good.enterprise_name},"
        f"{good.establishment_name},{good.nis_code},{good.nace_code}\n"
        f"2000000000,{good.enterprise_number},{good.enterprise_name},"
        f"Synthetic site bad,{good.nis_code},{good.nace_code}\n",
        encoding="utf-8",
    )
    kept, _enterprises, rejected = load_establishments(path, set(codes))
    assert len(kept) == 1
    assert len(rejected) == 1


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
def test_ingest_keeps_every_establishment_on_a_known_municipality(
    tmp_path: Path,
) -> None:
    """Aucun établissement chargé n'a une commune absente du référentiel."""
    settings = Settings.from_env()
    if not settings.ingest_password:
        pytest.skip("INGEST_PASSWORD vide")
    codes = set(_nis_codes())
    good = build_synthetic_establishments(sorted(codes))[0]
    bad_path = tmp_path / "one_bad.csv"
    write_establishment_csv(
        [good.model_copy(update={"nis_code": "91004"})],
        bad_path,
    )
    with _connect_or_skip(settings) as connection:
        ingest_population(connection, SAMPLE_CSV)
        try:
            bad_result = ingest_establishments(connection, bad_path)
            assert bad_result.loaded == 0
            assert bad_result.rejected == 1
            stored = connection.execute(
                "SELECT count(*) FROM ops.rejects WHERE source_name = %s",
                (SOURCE_NAME,),
            ).fetchone()
            assert stored is not None
            assert stored[0] == 1
        finally:
            ingest_establishments(connection, ESTABLISHMENT_SAMPLE)
        orphan = connection.execute(
            """
            SELECT count(*)
            FROM raw.establishment AS establishment
            LEFT JOIN raw.municipality_population AS municipality
                ON establishment.nis_code = municipality.nis_code
            WHERE municipality.nis_code IS NULL
            """
        ).fetchone()
        again = ingest_establishments(connection, ESTABLISHMENT_SAMPLE)
    assert orphan is not None
    assert orphan[0] == 0
    assert again.loaded == ESTABLISHMENT_COUNT
    assert again.rejected == 0
