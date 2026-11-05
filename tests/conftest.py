"""Test configuration.

Ensures the backend package is importable and redirects storage to a temporary
directory *before* any app module (and therefore the Settings singleton) is
imported.
"""
import os
import sys
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# Isolate storage so tests never touch the real projects directory.
_TMP = Path(tempfile.gettempdir()) / "replicator_test_projects"
_TMP.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PROJECTS_DIR", str(_TMP))
