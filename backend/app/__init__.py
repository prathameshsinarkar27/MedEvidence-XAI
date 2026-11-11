"""MedEvidence-XAI backend (research/educational prototype)."""

import sys
from pathlib import Path

__version__ = "0.8.0"

# The pure-Python `document_processing` library lives at the repository root (next to `backend/`),
# so make the root importable however the app is started (uvicorn from backend/, alembic, pytest).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))
