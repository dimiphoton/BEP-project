"""Graphiques des présentations, lus dans les marts, fond crème du thème.

Les titres ne contiennent pas un effectif recopié : l'axe porte les
valeurs mesurées. Le fond est ``--bg`` du thème portfolio.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from observatory.db import PgConnection

FIGURES_DIR = Path("pictures/presentations")
_BG = "#f3eee6"
_INK = "#1c1610"
_ACCENT = "#8a6a12"


def save_bars(
    labels: list[str],
    values: list[int],
    *,
    title: str,
    xlabel: str,
    path: Path,
) -> None:
    """Enregistre un barres horizontales, fond crème, sans cadre blanc.

    Parameters
    ----------
    labels :
        Catégories, de la plus grande à la plus petite à l'affichage.
    values :
        Mesures, même ordre que ``labels``.
    title :
        Phrase affichée au-dessus. Pas d'effectif recopié dedans.
    xlabel :
        Unité de l'axe.
    path :
        PNG de destination.

    Raises
    ------
    ValueError
        Aucune ligne à dessiner.
    """
    if not labels or len(labels) != len(values):
        raise ValueError("bars need one value per label")
    path.parent.mkdir(parents=True, exist_ok=True)
    height = max(3.2, 0.32 * len(labels) + 1.2)
    figure, axis = plt.subplots(figsize=(8.2, height))
    figure.patch.set_facecolor(_BG)
    axis.set_facecolor(_BG)
    axis.barh(labels, values, color=_ACCENT)
    axis.invert_yaxis()
    axis.set_title(title, color=_INK, loc="left", pad=12)
    axis.set_xlabel(xlabel, color=_INK)
    axis.tick_params(colors=_INK)
    for spine in ("top", "right"):
        axis.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        axis.spines[spine].set_color(_INK)
    figure.tight_layout()
    figure.savefig(path, dpi=140, facecolor=figure.get_facecolor())
    plt.close(figure)


def population_rows(connection: PgConnection) -> list[tuple[str, int, int]]:
    """Lit la population communale déjà agrégée dans le mart.

    Parameters
    ----------
    connection :
        Connexion qui lit ``marts``.

    Returns
    -------
    list[tuple[str, int, int]]
        Nom, population, année de référence, population décroissante.
    """
    rows = connection.execute(
        """
        SELECT municipality_name, population, reference_year
        FROM marts.dim_municipality
        ORDER BY population DESC, municipality_name
        """
    ).fetchall()
    return [(str(name), int(population), int(year)) for name, population, year in rows]


def family_rows(connection: PgConnection) -> list[tuple[str, int]]:
    """Compte les établissements par famille d'activité.

    Parameters
    ----------
    connection :
        Connexion qui lit ``marts``.

    Returns
    -------
    list[tuple[str, int]]
        Famille et nombre d'établissements, effectif décroissant.
    """
    rows = connection.execute(
        """
        SELECT enterprise.activity_family, count(*) AS sites
        FROM marts.fact_establishment AS site
        JOIN marts.dim_enterprise AS enterprise
          ON site.enterprise_number = enterprise.enterprise_number
        GROUP BY enterprise.activity_family
        ORDER BY sites DESC, enterprise.activity_family
        """
    ).fetchall()
    return [(str(family), int(sites)) for family, sites in rows]


def link_rows(connection: PgConnection) -> list[tuple[str, int]]:
    """Compte les avis liés, à relire, ou sans lien.

    Parameters
    ----------
    connection :
        Connexion qui lit ``raw``.

    Returns
    -------
    list[tuple[str, int]]
        Trois issues, dans un ordre fixe. Vide si la table n'existe pas.
    """
    found = connection.execute(
        "SELECT to_regclass('raw.contract_enterprise_link')"
    ).fetchone()
    if found is None or found[0] is None:
        return []
    rows = connection.execute(
        """
        SELECT status, count(*)
        FROM raw.contract_enterprise_link
        GROUP BY status
        """
    ).fetchall()
    totals = {str(status): int(total) for status, total in rows}
    labels = (
        ("linked", "lié"),
        ("review", "à relire"),
        ("unmatched", "sans lien"),
    )
    return [(label, totals.get(status, 0)) for status, label in labels]


def write_figures(
    connection: PgConnection,
    directory: Path = FIGURES_DIR,
) -> list[Path]:
    """Écrit les graphiques utilisés dans les decks.

    Parameters
    ----------
    connection :
        Connexion qui lit ``marts``.
    directory :
        Dossier ``pictures/presentations``.

    Returns
    -------
    list[Path]
        PNG écrits.
    """
    population = population_rows(connection)
    years = {year for _name, _population, year in population}
    if len(years) == 1:
        year = years.pop()
        population_title = f"Population {year} des communes de la province de Namur"
    else:
        population_title = "Population des communes de la province de Namur"
    population_path = directory / "municipality_population.png"
    save_bars(
        [name for name, _population, _year in population],
        [population_value for _name, population_value, _year in population],
        title=population_title,
        xlabel="Habitants",
        path=population_path,
    )
    families = family_rows(connection)
    family_path = directory / "establishments_by_family.png"
    save_bars(
        [family for family, _sites in families],
        [sites for _family, sites in families],
        title="Établissements synthétiques par famille d'activité",
        xlabel="Établissements",
        path=family_path,
    )
    written = [population_path, family_path]
    links = link_rows(connection)
    if links:
        link_path = directory / "contracts_by_link.png"
        save_bars(
            [label for label, _total in links],
            [total for _label, total in links],
            title="Avis synthétiques selon le lien à l'entreprise",
            xlabel="Avis",
            path=link_path,
        )
        written.append(link_path)
    return written
