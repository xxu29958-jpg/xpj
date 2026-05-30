import sys
from pathlib import Path

# Make the ``backend_manager`` package importable when pytest collects from desktop/tests.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
