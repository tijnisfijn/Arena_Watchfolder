"""Shared test configuration."""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so 'import watchfolder' etc. work
sys.path.insert(0, str(Path(__file__).parent.parent))
