"""Load environment variables from a project ``.env`` file."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# Repo / package root (``math_ide/`` -> project root). Used as a fallback when
# ``find_dotenv`` from the cwd does not locate a file — e.g. running from /tmp.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env(*, dotenv_path: Optional[Path] = None) -> bool:
    """Load variables from a ``.env`` file into ``os.environ``.

    Searches upward from the current working directory for ``.env`` unless
    ``dotenv_path`` is given. If nothing is found, also checks the project root
    next to this package. Existing environment variables are never overwritten
    (shell exports and CI secrets take precedence).

    Returns ``True`` if a file was found and loaded, else ``False``.
    """
    from dotenv import find_dotenv, load_dotenv

    if dotenv_path is not None:
        return load_dotenv(dotenv_path, override=False)

    if load_dotenv(find_dotenv(usecwd=True), override=False):
        return True
    return load_dotenv(_PROJECT_ROOT / ".env", override=False)
