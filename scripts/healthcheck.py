"""Échec si une source suivie est périmée ou si son volume chute de plus de 50 %."""

from __future__ import annotations

from observatory.healthcheck import main

if __name__ == "__main__":
    raise SystemExit(main())
