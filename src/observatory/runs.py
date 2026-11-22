"""Journal ``ops.run_log`` : début, fin, volume et statut d'un passage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from observatory.db import PgConnection

_OPEN_STATUSES = frozenset({"success", "failed"})


@dataclass(frozen=True)
class RunRecord:
    """Un passage déjà écrit, lu du plus récent au plus ancien."""

    source_name: str
    status: str
    finished_at: datetime | None
    rows_read: int | None
    rows_rejected: int | None


def start_run(connection: PgConnection, source_name: str) -> int:
    """Ouvre un passage au statut ``running``.

    Parameters
    ----------
    connection :
        Connexion ouverte avec ``ingest_rw``.
    source_name :
        Source suivie, par exemple le nom du fichier Statbel.

    Returns
    -------
    int
        Identifiant du passage, à repasser à ``finish_run``.
    """
    ensure_run_log(connection)
    row = connection.execute(
        """
        INSERT INTO ops.run_log (source_name, started_at, status)
        VALUES (%s, clock_timestamp(), 'running')
        RETURNING run_id
        """,
        (source_name,),
    ).fetchone()
    connection.commit()
    if row is None:
        raise RuntimeError("run_log did not return an id")
    return int(row[0])


def finish_run(
    connection: PgConnection,
    run_id: int,
    *,
    rows_read: int | None,
    rows_rejected: int | None,
    status: str,
) -> None:
    """Ferme un passage avec son volume et son statut.

    Parameters
    ----------
    connection :
        Connexion ouverte avec ``ingest_rw``.
    run_id :
        Identifiant rendu par ``start_run``.
    rows_read :
        Lignes lues. ``None`` si le passage a cassé avant le décompte.
    rows_rejected :
        Lignes refusées, parmi celles qui ont été lues.
    status :
        ``success`` ou ``failed``.

    Raises
    ------
    ValueError
        Statut inconnu, succès sans décompte, ou plus de rejets que de lignes.
    """
    if status not in _OPEN_STATUSES:
        raise ValueError(f"unknown run status {status}")
    if status == "success" and (rows_read is None or rows_rejected is None):
        raise ValueError("a success needs row counts")
    if (
        rows_read is not None
        and rows_rejected is not None
        and rows_rejected > rows_read
    ):
        raise ValueError("rows_rejected exceeds rows_read")
    connection.execute(
        """
        UPDATE ops.run_log
        SET finished_at = clock_timestamp(),
            rows_read = %s,
            rows_rejected = %s,
            status = %s
        WHERE run_id = %s
        """,
        (rows_read, rows_rejected, status, run_id),
    )
    connection.commit()


def latest_runs(
    connection: PgConnection,
    sources: tuple[str, ...],
) -> dict[str, list[RunRecord]]:
    """Lit les passages des sources demandées, du plus récent au plus ancien.

    Parameters
    ----------
    connection :
        Connexion ouverte avec ``ingest_rw``.
    sources :
        Noms suivis. Une source absente du journal a une liste vide.

    Returns
    -------
    dict[str, list[RunRecord]]
        Une liste par source, dans l'ordre de ``sources``.
    """
    ensure_run_log(connection)
    grouped = {name: [] for name in sources}
    if not sources:
        return grouped
    rows = connection.execute(
        """
        SELECT source_name, status, finished_at, rows_read, rows_rejected
        FROM ops.run_log
        WHERE source_name = ANY(%s)
        ORDER BY run_id DESC
        """,
        (list(sources),),
    ).fetchall()
    for source_name, status, finished_at, rows_read, rows_rejected in rows:
        grouped[source_name].append(
            RunRecord(
                source_name=source_name,
                status=status,
                finished_at=finished_at,
                rows_read=rows_read,
                rows_rejected=rows_rejected,
            )
        )
    return grouped


def ensure_run_log(connection: PgConnection) -> None:
    """Crée ``ops.run_log`` si elle n'existe pas encore."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ops.run_log (
            run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source_name text NOT NULL,
            started_at timestamptz NOT NULL,
            finished_at timestamptz,
            rows_read integer,
            rows_rejected integer,
            status text NOT NULL,
            CHECK (status IN ('running', 'success', 'failed')),
            CHECK (rows_read IS NULL OR rows_read >= 0),
            CHECK (
                rows_read IS NULL
                OR rows_rejected IS NULL
                OR rows_rejected <= rows_read
            ),
            CHECK (
                status <> 'success'
                OR (
                    finished_at IS NOT NULL
                    AND rows_read IS NOT NULL
                    AND rows_rejected IS NOT NULL
                )
            )
        )
        """
    )
