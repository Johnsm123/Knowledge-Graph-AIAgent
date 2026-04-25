"""Run the idempotent care-gap hygiene pass against the live Aura DB."""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.care_gap_cleanup import cleanup_all


if __name__ == "__main__":
    stats = cleanup_all()
    print(json.dumps(stats, indent=2, default=str))
