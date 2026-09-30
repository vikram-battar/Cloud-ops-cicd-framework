"""Make the repo root importable so `import ops` works from tests/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
