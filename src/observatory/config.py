"""Lecture de la configuration locale (.env), sans secret en dur."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

ENV_PATH = Path(".env")
ENV_EXAMPLE_PATH = Path(".env.example")


def _confidence_threshold() -> float:
    """Lit le seuil de revue. Une valeur illisible arrête le programme."""
    raw = os.environ.get("AI_CONFIDENCE_THRESHOLD", "0.8")
    try:
        threshold = float(raw)
    except ValueError as exc:
        raise SystemExit(f"AI_CONFIDENCE_THRESHOLD is not a number ({raw}).") from exc
    if not 0 <= threshold <= 1:
        raise SystemExit("AI_CONFIDENCE_THRESHOLD must be between 0 and 1.")
    return threshold


def ensure_dotenv(
    env_path: Path = ENV_PATH,
    example_path: Path = ENV_EXAMPLE_PATH,
) -> None:
    """Crée `.env` depuis l'exemple s'il manque, puis charge les variables.

    Les variables déjà présentes dans l'environnement ne sont pas écrasées.

    Parameters
    ----------
    env_path :
        Fichier d'environnement local, ignoré par git.
    example_path :
        Modèle versionné. Les mots de passe qu'il contient sont locaux.
    """
    if not env_path.exists() and example_path.exists():
        env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    if not env_path.exists():
        return
    _load_env_file(env_path)


def _load_env_file(path: Path) -> None:
    """Charge un fichier KEY=VALUE. Ignore les lignes vides et les commentaires."""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class Settings(BaseModel):
    """Paramètres de connexion lus depuis l'environnement."""

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "observatory"
    postgres_user: str = "observatory"
    postgres_password: str = ""
    ingest_user: str = "ingest_rw"
    ingest_password: str = ""
    dbt_user: str = "dbt_rw"
    dbt_password: str = ""
    reader_user: str = "reader_ro"
    reader_password: str = ""
    ai_mode: str = "mock"
    ai_confidence_threshold: float = 0.8

    @classmethod
    def from_env(cls) -> Settings:
        """Construit les paramètres après chargement de `.env`.

        Returns
        -------
        Settings
            Connexions administrateur, ingestion, dbt et lecture.
        """
        ensure_dotenv()
        return cls(
            postgres_host=os.environ.get("POSTGRES_HOST", "localhost"),
            postgres_port=int(os.environ.get("POSTGRES_PORT", "5432")),
            postgres_db=os.environ.get("POSTGRES_DB", "observatory"),
            postgres_user=os.environ.get("POSTGRES_USER", "observatory"),
            postgres_password=os.environ.get("POSTGRES_PASSWORD", ""),
            ingest_user=os.environ.get("INGEST_USER", "ingest_rw"),
            ingest_password=os.environ.get("INGEST_PASSWORD", ""),
            dbt_user=os.environ.get("DBT_USER", "dbt_rw"),
            dbt_password=os.environ.get("DBT_PASSWORD", ""),
            reader_user=os.environ.get("READER_USER", "reader_ro"),
            reader_password=os.environ.get("READER_PASSWORD", ""),
            ai_mode=os.environ.get("AI_MODE", "mock").strip().lower() or "mock",
            ai_confidence_threshold=_confidence_threshold(),
        )

    def require(self, *fields: str) -> None:
        """Arrête le programme si un mot de passe attendu est vide.

        Parameters
        ----------
        fields :
            Noms d'attributs de ce modèle, par exemple ``postgres_password``.

        Raises
        ------
        SystemExit
            Un des champs est une chaîne vide.
        """
        missing = [name for name in fields if not getattr(self, name)]
        if missing:
            joined = ", ".join(missing)
            raise SystemExit(f"Empty password ({joined}). Copy .env.example to .env.")
