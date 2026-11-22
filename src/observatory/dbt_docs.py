"""Copie le site statique ``dbt docs generate`` vers ``docs/dbt``.

Le dossier ``target/`` reste ignoré par git. La copie, elle, est versionnée
pour que la documentation suive le dépôt.
"""

from __future__ import annotations

import shutil
from pathlib import Path

TARGET_DIR = Path("dbt/target")
DOCS_DIR = Path("docs/dbt")
_FILES = ("index.html", "manifest.json", "catalog.json")


def copy_dbt_docs(
    source: Path = TARGET_DIR,
    destination: Path = DOCS_DIR,
) -> list[Path]:
    """Copie les trois fichiers que le site dbt ouvre dans le navigateur.

    Parameters
    ----------
    source :
        Dossier ``dbt/target`` après ``dbt docs generate``.
    destination :
        Dossier versionné ``docs/dbt``.

    Returns
    -------
    list[Path]
        Fichiers écrits.

    Raises
    ------
    FileNotFoundError
        Un des trois fichiers n'a pas été généré.
    """
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in _FILES:
        origin = source / name
        if not origin.is_file():
            raise FileNotFoundError(f"missing dbt docs file {origin.as_posix()}")
        target = destination / name
        shutil.copyfile(origin, target)
        written.append(target)
    return written
