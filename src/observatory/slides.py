"""Contrôle des decks FR avant qu'un chiffre manuscrit ne s'y glisse.

Les decks EN ne sont pas lus. ``generated_at`` n'est pas une mesure :
ses chiffres ne rendent pas un nombre licite dans une slide.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ALLOWED_CLASSES = frozenset(
    {"cover", "split", "full", "chart", "actions", "dark", "cta"}
)
FORBIDDEN_TITLES = frozenset({"résultats", "méthodologie", "stack", "motivation"})
SYNTHETIC_PHRASE = "échantillon synthétique"
PRESENTATIONS_DIR = Path("docs/presentations")
METRICS_PATH = Path("docs/metrics.json")
ALLOWLIST_PATH = Path("docs/presentations/numbers-allowlist.txt")

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_CLASS = re.compile(r"<!--\s*_class:\s*([A-Za-z0-9_-]+)\s*-->")
_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_BRACKETS = re.compile(r"\[[^\]]*\]")
_NUMBER = re.compile(r"\d{2,}")
_GENERATED_AT = re.compile(r'"generated_at"\s*:\s*"[^"]*"')
_BULLET = re.compile(r"^\s*[-*]\s+\S")
_FORBIDDEN_SNIPPETS = (
    "TBD",
    "à compléter",
    "à définir",
    "lorem",
    "TODO",
    "{{",
    "undefined",
    "NaN",
    "Ã©",
    "Ã ",
    "â€",
)


def french_decks(directory: Path = PRESENTATIONS_DIR) -> list[Path]:
    """Liste les sources Marp françaises, pas les decks EN.

    Parameters
    ----------
    directory :
        Dossier ``docs/presentations``.

    Returns
    -------
    list[Path]
        Fichiers ``*-fr.md``, triés.
    """
    return sorted(directory.glob("*-fr.md"))


def check_deck(
    text: str,
    *,
    filename: str,
    metrics_text: str,
    allowlist: set[str],
    data_origin: dict,
    base_dir: Path,
) -> list[str]:
    """Vérifie un deck. Une liste vide veut dire qu'il passe.

    Parameters
    ----------
    text :
        Source Marp complète.
    filename :
        Nom utilisé dans les messages et pour la fourchette de slides.
    metrics_text :
        Contenu brut de ``metrics.json``.
    allowlist :
        Nombres autorisés en plus des mesures.
    data_origin :
        Objet ``data_origin`` du JSON.
    base_dir :
        Dossier du fichier, pour résoudre les images.

    Returns
    -------
    list[str]
        Erreurs, dans l'ordre de lecture.
    """
    errors: list[str] = []
    front, slides = _split(text)
    if front is None:
        return [f"{filename}: frontmatter manquant"]
    if not re.search(r"(?m)^marp:\s*true\s*$", front):
        errors.append(f"{filename}: marp n'est pas true")
    if not re.search(r"(?m)^theme:\s*portfolio\s*$", front):
        errors.append(f"{filename}: theme n'est pas portfolio")
    expected = _expected_slide_count(filename)
    if expected is None:
        errors.append(f"{filename}: public inconnu (technique ou recruteur)")
    elif not expected[0] <= len(slides) <= expected[1]:
        low, high = expected
        errors.append(f"{filename}: {len(slides)} slides, attendu {low}–{high}")
    metric_numbers = _metric_numbers(metrics_text)
    synthetic = any(value == "synthetic" for value in data_origin.values())
    synthetic_ok = False
    for index, slide in enumerate(slides, start=1):
        where = f"{filename} slide {index}"
        classes = _CLASS.findall(slide)
        if len(classes) != 1 or classes[0] not in ALLOWED_CLASSES:
            shown = ", ".join(classes) or "aucune"
            errors.append(f"{where}: classe invalide ({shown})")
        visible = _COMMENT.sub("", slide)
        errors.extend(_placeholders(visible, where))
        errors.extend(_images(visible, where, base_dir))
        errors.extend(_numbers(visible, index, where, metric_numbers, allowlist))
        title = _title(visible)
        if title.casefold() in FORBIDDEN_TITLES:
            errors.append(f"{where}: titre interdit ({title})")
        words = visible.split()
        if len(words) > 70:
            errors.append(f"{where}: {len(words)} mots, maximum 70")
        bullets = [line for line in visible.splitlines() if _BULLET.match(line)]
        if len(bullets) > 6:
            errors.append(f"{where}: {len(bullets)} puces, maximum 6")
        if SYNTHETIC_PHRASE in visible and (
            (classes and classes[0] == "cover") or "limites" in visible.casefold()
        ):
            synthetic_ok = True
    if synthetic and not synthetic_ok:
        errors.append(
            f"{filename}: source synthétique sans « {SYNTHETIC_PHRASE} » "
            "en couverture ou sur la slide limites"
        )
    return errors


def load_allowlist(path: Path = ALLOWLIST_PATH) -> set[str]:
    """Lit les nombres autorisés hors mesures. Les lignes ``#`` sont ignorées.

    Parameters
    ----------
    path :
        Fichier texte, un jeton par ligne.

    Returns
    -------
    set[str]
        Jetons. Fichier absent : ensemble vide.
    """
    if not path.is_file():
        return set()
    allowed: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        token = line.strip()
        if token and not token.startswith("#"):
            allowed.add(token)
    return allowed


def check_directory(
    directory: Path = PRESENTATIONS_DIR,
    metrics_path: Path = METRICS_PATH,
    allowlist_path: Path = ALLOWLIST_PATH,
) -> list[str]:
    """Contrôle tous les decks FR d'un dossier.

    Parameters
    ----------
    directory :
        Dossier des sources Marp.
    metrics_path :
        JSON des mesures.
    allowlist_path :
        Nombres en plus des mesures.

    Returns
    -------
    list[str]
        Erreurs de tous les decks.
    """
    if not metrics_path.is_file():
        return [f"fichier absent : {metrics_path.as_posix()}"]
    metrics_text = metrics_path.read_text(encoding="utf-8")
    try:
        payload = json.loads(metrics_text)
    except json.JSONDecodeError as exc:
        return [f"{metrics_path.as_posix()} illisible : {exc}"]
    origin = payload.get("data_origin")
    if not isinstance(origin, dict):
        return [f"{metrics_path.as_posix()}: data_origin manquant"]
    allowlist = load_allowlist(allowlist_path)
    errors: list[str] = []
    decks = french_decks(directory)
    if not decks:
        errors.append(f"aucun deck FR dans {directory.as_posix()}")
    for path in decks:
        errors.extend(
            check_deck(
                path.read_text(encoding="utf-8"),
                filename=path.name,
                metrics_text=metrics_text,
                allowlist=allowlist,
                data_origin=origin,
                base_dir=path.parent,
            )
        )
    return errors


def _split(text: str) -> tuple[str | None, list[str]]:
    """Sépare le frontmatter des slides. ``---` sur sa propre ligne."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, []
    end = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = index
            break
    if end is None:
        return None, []
    front = "\n".join(lines[1:end])
    slides: list[str] = []
    current: list[str] = []
    for line in lines[end + 1 :]:
        if line.strip() == "---":
            slides.append("\n".join(current))
            current = []
        else:
            current.append(line)
    if current or slides:
        slides.append("\n".join(current))
    return front, slides


def _expected_slide_count(filename: str) -> tuple[int, int] | None:
    """Fourchette selon le public nommé dans le fichier."""
    if "technique" in filename:
        return 16, 18
    if "recruteur" in filename:
        return 12, 14
    return None


def _metric_numbers(metrics_text: str) -> str:
    """Retire l'horodatage pour qu'un jour du calendrier ne devienne pas une mesure."""
    return _GENERATED_AT.sub("", metrics_text)


def _placeholders(visible: str, where: str) -> list[str]:
    """Repère les crochets qui ne sont pas un lien, et les mots interdits."""
    errors: list[str] = []
    for match in _BRACKETS.finditer(visible):
        after = visible[match.end() :]
        if not after.lstrip().startswith("("):
            errors.append(f"{where}: crochet non lié {match.group()}")
    folded = visible.casefold()
    for snippet in _FORBIDDEN_SNIPPETS:
        if snippet == "lorem":
            present = "lorem" in folded
        else:
            present = snippet in visible
        if present:
            errors.append(f"{where}: texte interdit ({snippet})")
    return errors


def _images(visible: str, where: str, base_dir: Path) -> list[str]:
    """Une image commentée est déjà retirée. Une URL distante est refusée."""
    errors: list[str] = []
    for match in _IMAGE.finditer(visible):
        target = match.group(1).strip()
        if target.startswith(("http://", "https://")):
            errors.append(f"{where}: image distante {target}")
            continue
        path = (base_dir / target).resolve()
        if not path.is_file():
            errors.append(f"{where}: image absente {target}")
    return errors


def _numbers(
    visible: str,
    slide_index: int,
    where: str,
    metrics_text: str,
    allowlist: set[str],
) -> list[str]:
    """Un nombre d'au moins deux chiffres doit venir d'une mesure ou de la liste."""
    errors: list[str] = []
    for match in _NUMBER.finditer(visible):
        token = match.group()
        value = int(token)
        if 2020 <= value <= 2030:
            continue
        line = visible.splitlines()[visible[: match.start()].count("\n")]
        if value == slide_index and line.strip() == token:
            continue
        if token in allowlist:
            continue
        if re.search(rf"(?<!\d){token}(?!\d)", metrics_text):
            continue
        errors.append(f"{where}: nombre absent des mesures ({token})")
    return errors


def _title(visible: str) -> str:
    """Recolle les lignes ``#`` d'une slide en un seul titre."""
    parts = [line[2:].strip() for line in visible.splitlines() if line.startswith("# ")]
    return re.sub(r"\s+", " ", " ".join(parts)).strip()
