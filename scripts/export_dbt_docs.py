"""Génère la doc dbt et la copie dans ``docs/dbt``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from observatory.config import ensure_dotenv
from observatory.dbt_docs import copy_dbt_docs


def main() -> int:
    """Lance ``dbt docs generate`` puis copie index, manifest et catalog."""
    ensure_dotenv()
    dbt_name = "dbt.exe" if sys.platform == "win32" else "dbt"
    dbt_exe = Path(sys.executable).with_name(dbt_name)
    if not dbt_exe.exists():
        print('dbt is not installed. Run: pip install -e ".[dev]"')
        return 1
    completed = subprocess.run(
        [
            str(dbt_exe),
            "docs",
            "generate",
            "--project-dir",
            "dbt",
            "--profiles-dir",
            "dbt",
        ],
        check=False,
    )
    if completed.returncode != 0:
        return completed.returncode
    written = copy_dbt_docs()
    for path in written:
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
