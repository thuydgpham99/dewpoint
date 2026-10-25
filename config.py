"""Environment + model configuration.

The assignment requires the app to look for .env first in the repo folder,
then in the folder one level above (the teaching staff keep their .env there).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_DIR = Path(__file__).resolve().parent
PARENT_DIR = REPO_DIR.parent
GRANDPARENT_DIR = PARENT_DIR.parent

# Variables we expect to come from .env. A shell that exports one of these as
# an EMPTY string would otherwise block python-dotenv from setting it, because
# load_dotenv(override=False) treats "already present" as "already set". We
# clear the empty ones first so a real value in .env can land.
EXPECTED_KEYS = ("PORTKEY_API_KEY", "PORTKEY_BASE_URL", "PORTKEY_MODEL", "OPENAI_API_KEY")


def _drop_empty_env_vars() -> None:
    for name in EXPECTED_KEYS:
        if name in os.environ and not os.environ[name].strip():
            del os.environ[name]


def load_env() -> str:
    """Load .env from the repo folder first, then one level up.

    Returns a short string naming where the key came from, for the UI banner.
    """
    _drop_empty_env_vars()

    # Order required by the assignment: repo folder, then one level above.
    # A third location is checked only as a local convenience and never takes
    # priority over the two the assignment specifies.
    candidates = [
        (REPO_DIR / ".env", "repo folder"),
        (PARENT_DIR / ".env", "one level above"),
        (GRANDPARENT_DIR / ".env", "two levels above"),
    ]
    for path, label in candidates:
        if path.exists():
            load_dotenv(path, override=False)
            if os.getenv("PORTKEY_API_KEY"):
                return f"{label} ({path})"

    # Fall back to anything already exported in the shell.
    return "shell environment" if os.getenv("PORTKEY_API_KEY") else "NOT FOUND"


ENV_SOURCE = load_env()

PORTKEY_API_KEY = os.getenv("PORTKEY_API_KEY", "")
PORTKEY_BASE_URL = os.getenv("PORTKEY_BASE_URL", "https://api.portkey.ai/v1")

# The course sets the model in .env (PORTKEY_MODEL). We read it rather than
# hardcoding, so the app follows the course configuration.
MODEL = os.getenv("PORTKEY_MODEL", "gpt-5.6-luna")

# Overspending controls (see the Safety section of the report).
MAX_TOKENS_PER_RUN = 6000
MAX_AGENT_CALLS_PER_RUN = 5
MAX_INPUT_CHARS = 4000
