"""Audit the combined approved Bragg-to-Titan mapping before warehouse promotion.

Produces a row-level CSV that preserves the decision provenance and surfaces
reviewable conditions without silently dropping any approved mapping.
"""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
MAPPING_CSV = ROOT / "approved_game_mapping_seed.csv"
OLD_SOURCE_CSV = ROOT / "old_bragg_games_source.csv"
TITAN_SOURCE_CSV = ROOT / "titan_product_mapping_source.csv"
OUTPUT_CSV = ROOT / "approved_game_mapping_audit.csv"


def normalise(value: object) -> str:
    return "".join(char.lower() for char in str(value) if char.isalnum())


mappings = pd.read_csv(MAPPING_CSV, dtype=str).fillna("")
old = pd.read_csv(OLD_SOURCE_CSV, dtype=str).fillna("")
titan = pd.read_csv(TITAN_SOURCE_CSV, dtype=str).fillna("")

key = "old_aggregator_game_code"
if mappings[key].duplicated().any():
    raise ValueError("Approved mapping contains duplicate old game codes.")
if mappings["titan_product_id"].eq("").any():
    raise ValueError("Approved mapping contains blank Titan product IDs.")

old = old.drop_duplicates(subset=[key])[
    [key, "old_min_end_time", "old_max_end_time", "old_game_provider_name"]
].rename(columns={"old_game_provider_name": "source_provider_name"})
titan = titan.drop_duplicates(subset=["titan_product_id"])[
    [
        "titan_product_id",
        "titan_product_name",
        "titan_friendly_name",
        "mapped_provider_name",
        "RELEASE_DATE",
        "DISCONTINUED",
        "DISCONTINUED_DATE",
    ]
]

audit = mappings.merge(old, on=key, how="left", validate="one_to_one").merge(
    titan, on="titan_product_id", how="left", validate="many_to_one"
)

audit["titan_product_found"] = audit["titan_product_name"].ne("")
audit["provider_exact_match"] = audit.apply(
    lambda row: normalise(row["old_game_provider_name"])
    == normalise(row["mapped_provider_name"]),
    axis=1,
)
release = pd.to_datetime(audit["RELEASE_DATE"], errors="coerce", utc=True)
old_first_seen = pd.to_datetime(audit["old_min_end_time"], errors="coerce", utc=True)
audit["release_after_first_old_activity"] = (release > old_first_seen).fillna(False)

def audit_status(row: pd.Series) -> str:
    if not row["titan_product_found"]:
        return "BLOCKER_missing_titan_product"
    if row["release_after_first_old_activity"]:
        return "review_release_after_activity"
    if not row["provider_exact_match"]:
        return "review_cross_provider"
    return "pass"


audit["audit_status"] = audit.apply(audit_status, axis=1)
audit = audit.sort_values(
    ["audit_status", "mapping_source", "old_bets", key],
    ascending=[True, True, False, True],
)

audit.to_csv(OUTPUT_CSV, index=False)
print(f"Wrote {OUTPUT_CSV.name}: {len(audit):,} mappings")
print(audit["audit_status"].value_counts().to_string())
print("\\nMappings by source:")
print(audit["mapping_source"].value_counts().to_string())
