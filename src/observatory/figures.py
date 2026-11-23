"""Graphiques, schémas et carte des présentations, fond crème du thème.

Les barres viennent des mesures (fichier Statbel, marts, ``metrics.json``).
La carte reprend les contours communaux publiés et les comptes de
l'échantillon : teinte pour les sites, contour pour un avis chargé,
trait vers la commune du site de l'entreprise liée.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import FancyBboxPatch, PathPatch
from matplotlib.path import Path as MplPath

from observatory.contracts import load_cache, load_notices, prepare_contracts
from observatory.db import PgConnection
from observatory.entities import ContractWinner, EnterpriseName, resolve_winners
from observatory.establishments import ESTABLISHMENT_SAMPLE

FIGURES_DIR = Path("pictures/presentations")
POPULATION_CSV = Path("data/sample/statbel_population_namur_2025.csv")
BOUNDARIES_GEOJSON = Path("data/sample/namur_municipalities.geojson")
METRICS_PATH = Path("docs/metrics.json")
# Huit noms tiennent sur une slide. Les 38 barres rendaient les communes illisibles.
POPULATION_BARS = 8
_BG = "#f3eee6"
_INK = "#1c1610"
_ACCENT = "#8a6a12"
_PAPER = "#fffaf3"
_GOLD = "#e7d7a8"


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
    axis.tick_params(colors=_INK, labelsize=12)
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
    """Écrit les barres qui se lisent dans les marts.

    La population communale est dessinée à part, depuis l'extrait versionné,
    pour ne garder que les communes lisibles sur une slide.

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
    families = family_rows(connection)
    family_path = directory / "establishments_by_family.png"
    save_bars(
        [family for family, _sites in families],
        [sites for _family, sites in families],
        title="Établissements synthétiques par famille d'activité",
        xlabel="Établissements",
        path=family_path,
    )
    written = [family_path]
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


def write_didactic_figures(
    directory: Path = FIGURES_DIR,
    *,
    population_csv: Path = POPULATION_CSV,
    metrics: dict | None = None,
) -> list[Path]:
    """Écrit les schémas, la population lisible et la carte, sans base.

    Parameters
    ----------
    directory :
        Dossier ``pictures/presentations``.
    population_csv :
        Extrait Statbel versionné.
    metrics :
        Mesures déjà lues. Sinon ``docs/metrics.json``.

    Returns
    -------
    list[Path]
        PNG écrits.

    Raises
    ------
    ValueError
        Une mesure attendue manque, ou l'extrait communal est vide.
    """
    directory.mkdir(parents=True, exist_ok=True)
    payload = metrics if metrics is not None else _read_metrics()
    names, values, year = _top_population(population_csv)
    population_path = directory / "municipality_population.png"
    save_bars(
        names,
        values,
        title=f"Population {year}, communes les plus peuplées",
        xlabel="Habitants",
        path=population_path,
    )
    return [
        population_path,
        _problem_map(directory / "namur_contracts_sites.png"),
        _schema_two_keys(directory / "schema_two_keys.png"),
        _schema_pipeline(directory / "schema_pipeline.png"),
        _schema_pipeline_tech(directory / "schema_pipeline_tech.png"),
        _schema_model(directory / "schema_model.png"),
        _schema_model_tech(directory / "schema_model_tech.png"),
        _schema_link(directory / "schema_link.png"),
        _schema_quality(directory / "schema_quality.png", payload),
        _schema_fields(directory / "schema_fields.png", payload),
        _schema_nace(directory / "schema_nace.png"),
        _schema_snapshot(directory / "schema_snapshot.png"),
    ]


def _read_metrics(path: Path = METRICS_PATH) -> dict:
    """Lit les mesures. Les effectifs dessinés en sortent."""
    return json.loads(path.read_text(encoding="utf-8"))


def _metric(payload: dict, *keys: str) -> int:
    """Descend dans le JSON. Lève si la clé n'est pas un entier."""
    current: object = payload
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"mesure absente : {'.'.join(keys)}")
        current = current[key]
    if isinstance(current, bool) or not isinstance(current, int):
        raise TypeError(f"mesure illisible : {'.'.join(keys)}")
    return current


def _top_population(
    path: Path,
    limit: int = POPULATION_BARS,
) -> tuple[list[str], list[int], int]:
    """Les communes les plus peuplées de l'extrait, et leur année.

    Parameters
    ----------
    path :
        CSV ``municipality_name``, ``population``, ``reference_year``.
    limit :
        Nombre de barres. Au-delà, les noms ne tiennent plus sur une slide.

    Returns
    -------
    tuple[list[str], list[int], int]
        Noms, habitants, année. Ordre décroissant.

    Raises
    ------
    ValueError
        Fichier vide, ou plusieurs années dans les lignes gardées.
    """
    rows: list[tuple[str, int, int]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("municipality_name") or "").strip()
            population = int(raw["population"])
            year = int(raw["reference_year"])
            if name:
                rows.append((name, population, year))
    if not rows:
        raise ValueError(f"extrait communal vide : {path}")
    rows.sort(key=lambda item: (-item[1], item[0]))
    kept = rows[:limit]
    years = {year for _name, _population, year in kept}
    if len(years) != 1:
        raise ValueError("plusieurs années dans l'extrait communal")
    return (
        [name for name, _population, _year in kept],
        [population for _name, population, _year in kept],
        years.pop(),
    )


def _canvas() -> tuple[plt.Figure, plt.Axes]:
    """Feuille crème, repère 0–100, sans axes."""
    figure, axis = plt.subplots(figsize=(11.2, 5.6))
    figure.patch.set_facecolor(_BG)
    axis.set_facecolor(_BG)
    axis.set_xlim(0, 100)
    axis.set_ylim(0, 100)
    axis.axis("off")
    return figure, axis


def _finish(figure: plt.Figure, path: Path) -> Path:
    """Enregistre le schéma et ferme la figure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=140, facecolor=figure.get_facecolor(), bbox_inches="tight")
    plt.close(figure)
    return path


def _box(
    axis: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    *,
    fill: str = _PAPER,
    size: int = 13,
    dashed: bool = False,
) -> None:
    """Rectangle arrondi et son texte, centré."""
    axis.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.2,rounding_size=1.2",
            linewidth=1.6,
            edgecolor=_INK,
            facecolor=fill,
            linestyle="--" if dashed else "-",
        )
    )
    axis.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=size,
        color=_INK,
        linespacing=1.35,
    )


def _arrow(axis: plt.Axes, start: tuple[float, float], end: tuple[float, float]) -> None:
    """Flèche droite entre deux points du repère."""
    axis.annotate(
        "",
        xy=end,
        xytext=start,
        arrowprops={"arrowstyle": "-|>", "color": _INK, "lw": 1.5},
    )


def _schema_two_keys(path: Path) -> Path:
    """Deux listes, deux clés : commune et entreprise."""
    figure, axis = _canvas()
    _box(axis, 6, 58, 36, 30, "Sites des parcs\noù est l'établissement", size=15)
    _box(axis, 58, 58, 36, 30, "Avis de marchés\nqui a gagné, et où", size=15)
    _box(
        axis,
        18,
        8,
        64,
        34,
        "Ils se rejoignent par\nla commune, code INS\net l'entreprise, n° BCE",
        fill=_GOLD,
        size=16,
    )
    _arrow(axis, (24, 58), (40, 42))
    _arrow(axis, (76, 58), (60, 42))
    return _finish(figure, path)


def _schema_pipeline(path: Path) -> Path:
    """Trajet en langage clair, avec la ligne écartée."""
    figure, axis = _canvas()
    steps = (
        (4, "Fichier"),
        (28, "Contrôle"),
        (52, "Base brute"),
        (76, "Modèle"),
    )
    for left, label in steps:
        _box(axis, left, 48, 20, 28, label, size=15, fill=_GOLD if label == "Modèle" else _PAPER)
    for left in (24, 48, 72):
        _arrow(axis, (left, 62), (left + 4, 62))
    _box(axis, 28, 8, 20, 24, "Ligne écartée\nle reste continue", dashed=True, size=13)
    _arrow(axis, (38, 48), (38, 32))
    return _finish(figure, path)


def _schema_pipeline_tech(path: Path) -> Path:
    """Même trajet, avec les schémas Postgres."""
    figure, axis = _canvas()
    steps = (
        (3, "Fichier"),
        (22, "Contrôle"),
        (41, "raw"),
        (60, "staging"),
        (79, "marts"),
    )
    for left, label in steps:
        fill = _GOLD if label == "marts" else _PAPER
        _box(axis, left, 55, 16, 26, label, size=14, fill=fill)
    for left in (19, 38, 57, 76):
        _arrow(axis, (left, 68), (left + 3, 68))
    _box(axis, 14, 10, 28, 26, "ops.rejects\nligne invalide", dashed=True, size=13)
    _box(axis, 52, 10, 34, 26, "ops.review_queue\nsous le seuil, pas publié", dashed=True, size=13)
    # Les deux portes partent du contrôle, avant l'écriture dans raw.
    _arrow(axis, (30, 55), (28, 36))
    _arrow(axis, (30, 55), (69, 36))
    return _finish(figure, path)


def _schema_model(path: Path) -> Path:
    """Le site joint les deux référentiels. L'avis joint la commune, pas toujours l'entreprise."""
    figure, axis = _canvas()
    _box(axis, 6, 70, 40, 22, "Commune\npopulation réelle", size=14)
    _box(axis, 54, 70, 40, 22, "Entreprise\nnom et activité", size=14)
    _box(axis, 30, 38, 40, 22, "Site\néchantillon", fill=_GOLD, size=14)
    _box(axis, 6, 6, 40, 22, "Avis\néchantillon", size=14)
    _arrow(axis, (42, 60), (26, 70))
    _arrow(axis, (58, 60), (74, 70))
    # À gauche du site : l'avis rejoint la commune sans traverser le site.
    _arrow(axis, (26, 28), (26, 70))
    # Contour pointillé : l'entreprise seulement si le lien tient.
    axis.plot([46, 98, 98], [17, 17, 81], color=_INK, lw=1.4, linestyle="--")
    _arrow(axis, (98, 81), (94, 81))
    axis.text(72, 24, "si la preuve suffit", fontsize=12, color=_INK, ha="center")
    return _finish(figure, path)


def _schema_model_tech(path: Path) -> Path:
    """Faits, dimensions, et le mart qui croise les deux clés."""
    figure, axis = _canvas()
    _box(axis, 4, 70, 28, 22, "dim_municipality\nnis_code", size=12)
    _box(axis, 36, 70, 28, 22, "fact_establishment\nsite", fill=_GOLD, size=12)
    _box(axis, 68, 70, 28, 22, "dim_enterprise\nn° BCE", size=12)
    _box(axis, 4, 36, 28, 22, "fact_public_contract\navis", fill=_GOLD, size=11)
    _box(
        axis,
        40,
        8,
        52,
        20,
        "mart_contracts_by_municipality\nmême commune et même entreprise",
        size=12,
    )
    _arrow(axis, (36, 81), (32, 81))
    _arrow(axis, (64, 81), (68, 81))
    _arrow(axis, (18, 58), (18, 70))
    _arrow(axis, (32, 42), (48, 28))
    _arrow(axis, (50, 70), (58, 28))
    return _finish(figure, path)


def _schema_link(path: Path) -> Path:
    """Quatre issues d'un attributaire. Pas de seuil chiffré : ce n'est pas une mesure."""
    figure, axis = _canvas()
    _box(axis, 4, 36, 28, 28, "Attributaire\nde l'avis", size=15)
    _box(axis, 48, 74, 46, 18, "Numéro déjà connu → lien", fill=_GOLD, size=14)
    _box(axis, 48, 52, 46, 18, "Nom identique → lien", fill=_GOLD, size=14)
    _box(axis, 48, 30, 46, 18, "Nom proche → une personne", dashed=True, size=14)
    _box(axis, 48, 8, 46, 18, "Nom éloigné → pas de lien", dashed=True, size=14)
    _arrow(axis, (32, 58), (48, 83))
    _arrow(axis, (32, 52), (48, 61))
    _arrow(axis, (32, 46), (48, 39))
    _arrow(axis, (32, 40), (48, 17))
    return _finish(figure, path)


def _schema_quality(path: Path, metrics: dict) -> Path:
    """Trois portes pour un avis. Les effectifs viennent des mesures."""
    loaded = _metric(metrics, "counts", "public_contracts")
    rejected = _metric(metrics, "rejects", "synthetic_public_contracts")
    waiting = _metric(metrics, "ai", "extraction_below_threshold")
    figure, axis = _canvas()
    _box(axis, 4, 36, 28, 28, "Avis extrait", size=15)
    _box(axis, 48, 70, 46, 20, f"Invalide → quarantaine\n{rejected}", dashed=True, size=14)
    _box(axis, 48, 40, 46, 20, f"Sous le seuil → revue\n{waiting}", dashed=True, size=14)
    _box(axis, 48, 10, 46, 20, f"Tenu → chargé dans le modèle\n{loaded}", fill=_GOLD, size=14)
    _arrow(axis, (32, 58), (48, 80))
    _arrow(axis, (32, 50), (48, 50))
    _arrow(axis, (32, 42), (48, 20))
    return _finish(figure, path)


def _schema_fields(path: Path, metrics: dict) -> Path:
    """Champs concordants et champ écarté, lus dans les mesures."""
    matched = _metric(metrics, "ai", "extraction_fields_matched")
    scored = _metric(metrics, "ai", "extraction_fields_scored")
    missed = scored - matched
    if missed < 0:
        raise ValueError("plus de champs concordants que de champs comparés")
    figure, axis = _canvas()
    _box(axis, 6, 28, 42, 44, f"{matched}\nconcordent", fill=_GOLD, size=20)
    _box(axis, 54, 28, 40, 44, f"{missed}\nécarté", dashed=True, size=20)
    return _finish(figure, path)


def _schema_nace(path: Path) -> Path:
    """Règle d'abord, cache ensuite, revue si la confiance baisse."""
    figure, axis = _canvas()
    _box(axis, 4, 36, 26, 28, "Code NACE", size=15)
    _box(axis, 44, 62, 50, 24, "Section déjà claire\n→ règle, publié", fill=_GOLD, size=14)
    _box(axis, 44, 34, 50, 22, "Sinon → cache", size=14)
    _box(axis, 44, 6, 50, 22, "Confiance basse → revue", dashed=True, size=14)
    _arrow(axis, (30, 58), (44, 74))
    _arrow(axis, (30, 48), (44, 45))
    _arrow(axis, (69, 34), (69, 28))
    return _finish(figure, path)


def _schema_snapshot(path: Path) -> Path:
    """Historique par contrôle du nom et du code, sans date inventée."""
    figure, axis = _canvas()
    _box(axis, 6, 32, 34, 36, "Chargement\nnom\ncode NACE", size=15)
    _box(axis, 58, 32, 36, 36, "Chargement suivant\nmêmes deux colonnes", size=15)
    _arrow(axis, (40, 50), (58, 50))
    _box(
        axis,
        18,
        4,
        64,
        22,
        "Si l'un change, une nouvelle version.\nLa source n'a pas de date.",
        fill=_GOLD,
        size=14,
    )
    return _finish(figure, path)


def _problem_map(path: Path) -> Path:
    """Carte de la province : sites, avis chargés, site de l'entreprise liée.

    Les contours viennent du GeoJSON communal. La teinte compte les sites
    du CSV. Le contour épais marque une commune d'un avis chargé par les
    mêmes règles que l'ingestion. Le trait part de cette commune vers un
    site de l'entreprise liée, quand le lien existe.

    Parameters
    ----------
    path :
        PNG de destination.

    Returns
    -------
    Path
        Le fichier écrit.

    Raises
    ------
    ValueError
        Contour, site ou avis manquant pour un code INS chargé.
    """
    features = _boundary_features()
    site_counts, sites_by_enterprise, enterprises = _site_index()
    loaded = _loaded_contracts(allowed={item["nis"] for item in features})
    names = {item["nis"]: item["name"] for item in features}
    shapes = {item["nis"]: item["rings"] for item in features}
    missing = {item.nis_code for item in loaded} - set(shapes)
    if missing:
        raise ValueError(f"avis chargé sans contour : {sorted(missing)}")
    links = resolve_winners(
        [
            ContractWinner(item.notice_id, item.winner_name, item.enterprise_number)
            for item in loaded
        ],
        enterprises,
    )
    by_notice = {item.notice_id: item.nis_code for item in loaded}
    moves: list[tuple[str, str]] = []
    for link in links:
        if link.status != "linked" or not link.enterprise_number:
            continue
        origin = by_notice[link.notice_id]
        for destination in sorted(sites_by_enterprise.get(link.enterprise_number, ())):
            if destination != origin:
                moves.append((origin, destination))
    return _draw_problem_map(path, features, site_counts, names, set(by_notice.values()), moves)


def _boundary_features() -> list[dict]:
    """Lit les communes de Namur. Chaque entrée a un code, un nom, des anneaux."""
    if not BOUNDARIES_GEOJSON.is_file():
        raise ValueError(f"contours absents : {BOUNDARIES_GEOJSON}")
    payload = json.loads(BOUNDARIES_GEOJSON.read_text(encoding="utf-8"))
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError(f"contours vides : {BOUNDARIES_GEOJSON}")
    parsed: list[dict] = []
    for feature in features:
        props = feature.get("properties") or {}
        nis = str(props.get("nis") or "").strip()
        name = str(props.get("name") or "").strip()
        rings = list(_geometry_rings(feature.get("geometry") or {}))
        if not nis or not name or not rings:
            raise ValueError(f"contour incomplet : {nis or name}")
        parsed.append({"nis": nis, "name": name, "rings": rings})
    return parsed


def _geometry_rings(geometry: dict):
    """Anneaux extérieurs et trous, un polygone à la fois."""
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    polygons = [coordinates] if kind == "Polygon" else coordinates
    if kind not in {"Polygon", "MultiPolygon"}:
        raise ValueError(f"géométrie inattendue : {kind}")
    yield from polygons


def _site_index() -> tuple[dict[str, int], dict[str, set[str]], list[EnterpriseName]]:
    """Compte les sites et retient le nom de chaque entreprise du CSV."""
    counts: dict[str, int] = {}
    sites_by_enterprise: dict[str, set[str]] = {}
    enterprises: list[EnterpriseName] = []
    seen: set[str] = set()
    with ESTABLISHMENT_SAMPLE.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            nis = (raw.get("nis_code") or "").strip()
            number = (raw.get("enterprise_number") or "").strip()
            name = (raw.get("enterprise_name") or "").strip()
            if not nis or not number:
                continue
            counts[nis] = counts.get(nis, 0) + 1
            sites_by_enterprise.setdefault(number, set()).add(nis)
            if number not in seen:
                seen.add(number)
                enterprises.append(EnterpriseName(number, name))
    if not counts:
        raise ValueError(f"aucun site : {ESTABLISHMENT_SAMPLE}")
    return counts, sites_by_enterprise, enterprises


def _loaded_contracts(allowed: set[str]):
    """Avis qui passeraient le chargement, avec les mêmes règles que l'ingestion."""
    prepared = prepare_contracts(load_notices(), load_cache(), allowed)
    if not prepared.loaded:
        raise ValueError("aucun avis chargé pour la carte")
    return prepared.loaded


def _draw_problem_map(
    path: Path,
    features: list[dict],
    site_counts: dict[str, int],
    names: dict[str, str],
    contract_nis: set[str],
    moves: list[tuple[str, str]],
) -> Path:
    """Dessine la province. Le trait ne reste pas dans la commune de l'avis."""
    path.parent.mkdir(parents=True, exist_ok=True)
    largest = max(site_counts.values())
    scale = LinearSegmentedColormap.from_list("sites", ["#fffaf3", "#e7d7a8", "#8a6a12"])
    # Format 16:9 : la province à gauche, la légende en grand à droite.
    figure = plt.figure(figsize=(13.4, 7.4))
    figure.patch.set_facecolor(_BG)
    axis = figure.add_axes((0.01, 0.03, 0.64, 0.94))
    axis.set_facecolor(_BG)
    centroids: dict[str, tuple[float, float]] = {}
    for feature in features:
        nis = feature["nis"]
        share = 0 if largest == 0 else site_counts.get(nis, 0) / largest
        color = scale(0.15 + 0.85 * share)
        awarded = nis in contract_nis
        for rings in feature["rings"]:
            patch = PathPatch(
                _ring_path(rings),
                facecolor=color,
                edgecolor=_INK if awarded else "#c9bfb2",
                linewidth=2.2 if awarded else 0.45,
                joinstyle="round",
                zorder=2 if awarded else 1,
            )
            axis.add_patch(patch)
        centroids[nis] = _centroid(feature["rings"][0][0])
    for origin, destination in moves:
        start = centroids[origin]
        end = centroids[destination]
        axis.annotate(
            "",
            xy=end,
            xytext=start,
            arrowprops={
                "arrowstyle": "-|>",
                "color": _INK,
                "lw": 0.7,
                "alpha": 0.85,
                "shrinkA": 2,
                "shrinkB": 2,
                "connectionstyle": "arc3,rad=0.12",
            },
            zorder=3,
        )
    for nis in sorted(contract_nis):
        x_pos, y_pos = centroids[nis]
        axis.text(
            x_pos,
            y_pos,
            names[nis],
            ha="center",
            va="center",
            fontsize=8,
            color=_INK,
            zorder=4,
            path_effects=[path_effects.withStroke(linewidth=3, foreground=_BG)],
        )
    axis.set_aspect("equal")
    axis.autoscale_view()
    axis.axis("off")
    axis.margins(0.02)
    _map_legend(figure, names, contract_nis)
    figure.savefig(path, dpi=140, facecolor=figure.get_facecolor())
    plt.close(figure)
    return path


def _map_legend(figure: plt.Figure, names: dict[str, str], contract_nis: set[str]) -> None:
    """Légende à droite. Les noms restent lisibles quand la carte rétrécit."""
    ordered = sorted(contract_nis, key=lambda nis: names[nis])
    listed = "\n".join(names[nis] for nis in ordered)
    figure.text(
        0.68,
        0.92,
        "Comment lire",
        color=_INK,
        fontsize=16,
        fontweight="bold",
        ha="left",
        va="top",
    )
    figure.text(
        0.68,
        0.82,
        "Teinte : sites de l'échantillon\n"
        "Contour noir : un avis chargé\n"
        "Trait : site de l'entreprise liée,\n"
        "ailleurs que la commune de l'avis",
        color=_INK,
        fontsize=13,
        ha="left",
        va="top",
        linespacing=1.45,
    )
    figure.text(
        0.68,
        0.52,
        "Communes des avis chargés",
        color=_INK,
        fontsize=16,
        fontweight="bold",
        ha="left",
        va="top",
    )
    figure.text(
        0.68,
        0.42,
        listed,
        color=_INK,
        fontsize=13,
        ha="left",
        va="top",
        linespacing=1.35,
    )
    figure.text(
        0.68,
        0.06,
        "Contours communaux Statbel, 2025.",
        color=_INK,
        fontsize=11,
        ha="left",
        va="bottom",
    )


def _ring_path(rings: list) -> MplPath:
    """Un polygone, trous compris. L'anneau suivant est un trou."""
    vertices: list[tuple[float, float]] = []
    codes: list[int] = []
    for ring in rings:
        if len(ring) < 3:
            continue
        points = [(float(x_pos), float(y_pos)) for x_pos, y_pos in ring]
        if points[0] != points[-1]:
            points.append(points[0])
        vertices.append(points[0])
        codes.append(MplPath.MOVETO)
        for point in points[1:-1]:
            vertices.append(point)
            codes.append(MplPath.LINETO)
        vertices.append(points[-1])
        codes.append(MplPath.CLOSEPOLY)
    return MplPath(vertices, codes)


def _centroid(ring: list) -> tuple[float, float]:
    """Centre moyen de l'anneau extérieur, assez bon pour un nom."""
    points = ring[:-1] if ring[0] == ring[-1] else ring
    count = len(points)
    return (
        sum(float(point[0]) for point in points) / count,
        sum(float(point[1]) for point in points) / count,
    )
