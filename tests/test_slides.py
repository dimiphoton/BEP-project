"""Le contrôle des slides lit des decks fictifs, pas encore les vrais."""

from __future__ import annotations

import json
from pathlib import Path

from observatory.dbt_docs import copy_dbt_docs
from observatory.figures import save_bars
from observatory.metrics import count_dbt_tests
from observatory.slides import check_deck, french_decks

_METRICS = {
    "counts": {"establishments": 300},
    "data_origin": {"establishments": "synthetic", "municipalities": "real"},
    "generated_at": "2026-11-22T22:00:00+00:00",
}


def _metrics_text() -> str:
    return json.dumps(_METRICS)


def _deck(slides: list[str]) -> str:
    body = "\n---\n\n".join(slides)
    return f"---\nmarp: true\ntheme: portfolio\n---\n\n{body}\n"


def _slide(klass: str, title: str, body: str = "Une phrase sans chiffre.") -> str:
    return f"<!-- _class: {klass} -->\n\n# {title}\n\n{body}\n"


def _valid(count: int = 16) -> str:
    slides = [
        _slide(
            "cover",
            "La question tient en une phrase",
            "Ceci est un échantillon synthétique pour la démonstration.",
        )
    ]
    slides.extend(
        _slide("dark", "Une assertion qui tient") for _index in range(2, count + 1)
    )
    return _deck(slides)


def _check(text: str, *, filename: str = "presentation-technique-fr.md", **kwargs):
    options = {
        "metrics_text": _metrics_text(),
        "allowlist": set(),
        "data_origin": _METRICS["data_origin"],
        "base_dir": Path("."),
    }
    options.update(kwargs)
    return check_deck(text, filename=filename, **options)


def test_valid_technique_deck_passes() -> None:
    """Seize slides, thème portfolio, phrase synthétique : rien à redire."""
    assert _check(_valid()) == []


def test_recruiter_range_and_unknown_audience() -> None:
    """Le recruteur tient sur 12 à 14 slides. Un autre nom de fichier est refusé."""
    assert _check(_valid(12), filename="presentation-recruteur-fr.md") == []
    assert _check(_valid(10), filename="notes-fr.md") == [
        "notes-fr.md: public inconnu (technique ou recruteur)"
    ]


def test_theme_class_and_slide_count() -> None:
    """Le thème, la classe et la fourchette sont des erreurs distinctes."""
    broken = _valid().replace("theme: portfolio", "theme: default", 1)
    assert any("theme" in line for line in _check(broken))
    short = _valid(15)
    assert any("15 slides" in line for line in _check(short))
    bad_class = _valid().replace("_class: dark", "_class: photo", 1)
    assert any("classe invalide" in line for line in _check(bad_class))


def test_placeholders_links_and_broken_encoding() -> None:
    """Un lien Markdown passe. Un crochet nu, TBD ou un mojibake, non."""
    linked = _valid().replace(
        "Une phrase sans chiffre.",
        "Lire [le dépôt](https://example.com).",
        1,
    )
    assert _check(linked) == []
    bracket = _valid().replace("Une phrase sans chiffre.", "Voir [plus tard].", 1)
    assert any("crochet" in line for line in _check(bracket))
    todo = _valid().replace("Une phrase sans chiffre.", "Encore TBD ici.", 1)
    assert any("TBD" in line for line in _check(todo))
    mojibake = _valid().replace("Une phrase sans chiffre.", "Texte Ã© cassé.", 1)
    assert any("Ã©" in line for line in _check(mojibake))


def test_images_comments_and_remote_urls(tmp_path: Path) -> None:
    """Une image commentée est ignorée. Une URL distante ou un fichier absent, non."""
    picture = tmp_path / "graphe.png"
    picture.write_bytes(b"png")
    local = _valid().replace(
        "Une phrase sans chiffre.",
        "<!-- ![x](manquant.png) -->\n\n![graphe](graphe.png)",
        1,
    )
    assert _check(local, base_dir=tmp_path) == []
    remote = _valid().replace(
        "Une phrase sans chiffre.",
        "![loin](https://example.com/a.png)",
        1,
    )
    assert any("distante" in line for line in _check(remote, base_dir=tmp_path))
    missing = _valid().replace(
        "Une phrase sans chiffre.",
        "![manque](absent.png)",
        1,
    )
    assert any("absente" in line for line in _check(missing, base_dir=tmp_path))


def test_numbers_come_from_metrics_allowlist_or_years() -> None:
    """42 doit être mesuré. 2025 est une année. Le numéro de slide seul passe."""
    numbered = _valid().replace("Une phrase sans chiffre.", "On en compte 42.", 1)
    assert any("42" in line for line in _check(numbered))
    allowed = _check(numbered, allowlist={"42"})
    assert allowed == []
    measured = _check(
        numbered,
        metrics_text=json.dumps({"counts": {"answer": 42}}),
    )
    assert measured == []
    year = _valid().replace("Une phrase sans chiffre.", "Référence 2025.", 1)
    assert _check(year) == []
    # La slide 10 ne contient que son numéro, sur une ligne : ce n'est pas une mesure.
    slides = [
        _slide(
            "cover",
            "La question tient en une phrase",
            "Ceci est un échantillon synthétique pour la démonstration.",
        )
    ]
    for index in range(2, 17):
        body = "10" if index == 10 else "Une phrase sans chiffre."
        slides.append(_slide("dark", "Une assertion qui tient", body))
    assert _check(_deck(slides)) == []


def test_title_length_and_bullets() -> None:
    """Un libellé, 71 mots ou 7 puces font échouer la slide."""
    titled = _valid().replace("# Une assertion qui tient", "# Résultats", 1)
    assert any("titre interdit" in line for line in _check(titled))
    words = " ".join(["mot"] * 71)
    long = _valid().replace("Une phrase sans chiffre.", words, 1)
    assert any("mots" in line for line in _check(long))
    bullets = "\n".join(f"- puce {index}" for index in range(7))
    listed = _valid().replace("Une phrase sans chiffre.", bullets, 1)
    assert any("puces" in line for line in _check(listed))


def test_synthetic_origin_must_be_named_on_the_cover() -> None:
    """Une origine synthetic oblige la phrase sur la couverture ou la slide limites."""
    quiet = _valid().replace("échantillon synthétique", "jeu de démonstration", 1)
    assert any("échantillon synthétique" in line for line in _check(quiet))
    real_only = _check(quiet, data_origin={"municipalities": "real"})
    assert real_only == []


def test_french_deck_glob_ignores_english(tmp_path: Path) -> None:
    """Seuls les fichiers ``*-fr.md`` sont contrôlés."""
    (tmp_path / "presentation-technique-fr.md").write_text("---\n", encoding="utf-8")
    (tmp_path / "presentation-technique-en.md").write_text("---\n", encoding="utf-8")
    found = [path.name for path in french_decks(tmp_path)]
    assert found == ["presentation-technique-fr.md"]


def test_dbt_test_counts_ignore_models() -> None:
    """Seuls les nœuds ``test.`` comptent, pas le ``success`` d'un modèle."""
    payload = {
        "results": [
            {"unique_id": "test.observatory.one", "status": "pass"},
            {"unique_id": "test.observatory.two", "status": "fail"},
            {"unique_id": "test.observatory.three", "status": "error"},
            {"unique_id": "model.observatory.dim", "status": "success"},
        ]
    }
    assert count_dbt_tests(payload) == (1, 2)


def test_save_bars_writes_a_png(tmp_path: Path) -> None:
    """Le graphe sort sur disque, fond inclus, sans fenêtre."""
    target = tmp_path / "bars.png"
    save_bars(
        ["Anhée", "Namur"],
        [10, 30],
        title="Population des deux communes",
        xlabel="Habitants",
        path=target,
    )
    assert target.is_file()
    assert target.stat().st_size > 1000


def test_copy_dbt_docs_requires_the_three_files(tmp_path: Path) -> None:
    """La copie emporte index, manifest et catalog, pas le reste de target."""
    source = tmp_path / "target"
    source.mkdir()
    for name in ("index.html", "manifest.json", "catalog.json", "compiled.sql"):
        (source / name).write_text(name, encoding="utf-8")
    destination = tmp_path / "docs"
    written = copy_dbt_docs(source, destination)
    assert [path.name for path in written] == [
        "index.html",
        "manifest.json",
        "catalog.json",
    ]
    assert not (destination / "compiled.sql").exists()
