"""Make the project root importable so tests can use `remo` and `scripts`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
