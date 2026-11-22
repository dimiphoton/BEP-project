"""Refuse un deck FR qui n'est pas encore montrable."""

from __future__ import annotations

from observatory.slides import check_directory


def main() -> int:
    """Affiche les erreurs et sort 1 dès qu'il y en a une."""
    errors = check_directory()
    if errors:
        for line in errors:
            print(line)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
