"""Locations of the committed reference data (no heavy imports, safe for every service)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_DIR = REPO_ROOT / "data" / "reference"

BOUNDARY_PATH = REFERENCE_DIR / "pomorie_boundary.geojson"
FEATURES_PATH = REFERENCE_DIR / "osm_features.geojson"
RULES_PATH = REFERENCE_DIR / "category_rules.csv"
APP_BOUNDARY_PATH = REPO_ROOT / "app" / "public" / "pomorie_boundary.geojson"
