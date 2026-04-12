#!/usr/bin/env python
"""Fetch live odds from Sportybet and Odds API."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.pipeline import run_live_fetch

if __name__ == "__main__":
    run_live_fetch()
