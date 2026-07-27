"""Run a catalogue and activity-timing audit over the unified import mapping."""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
MAPPING_CSV = ROOT / "unified_game_mapping_for_bigquery.csv"
OLD_CSV = ROOT / "old_bragg_games_source.csv"
TITAN_CSV = ROOT / "titan_product_mapping_source.csv"
OUTPUT_CSV = ROOT / "unified_game_mapping_audit.csv"
KEY = "old_aggregator_game_code"


def normalise(value: object) -> str:
    return "".join(char.lower() for char in str(value) if char.isalnum())


mapping = pd.read_csv(MAPPING_CSV, dtype=str).fillna("")
old = pd.read_csv(OLD_CSV, dtype=str).fillna("")
titan = pd.read_csv(TITAN_CSV, dtype=str).fillna("")

if mapping[KEY].duplicated().any() or mapping["titan_product_id"].eq("").any():
    raise ValueError("Unified mapping must have one nonblank Titan ID per old code.")

old = old.drop_duplicates(subset=[KEY])[
    [KEY, "old_min_end_time", "old_max_end_time", "old_game_provider_name"]
].rename(columns={"old_game_provider_name": "source_provider_name"})
titan = titan.drop_duplicates(subset=["titan_product_id"])[
    ["titan_product_id", "titan_product_name", "mapped_provider_name", "RELEASE_DATE"]
]

audit = mapping.merge(old, on=KEY, how="left", validate="one_to_one").merge(
    titan, on="titan_product_id", how="left", validate="many_to_one"
)
audit["titan_product_found"] = audit["titan_product_name"].ne("")
audit["provider_exact_match"] = audit.apply(
    lambda row: normalise(row["old_game_provider_name"])
    == normalise(row["mapped_provider_name"]),
    axis=1,
)
release = pd.to_datetime(audit["RELEASE_DATE"], errors="coerce", utc=True)
first_seen = pd.to_datetime(audit["old_min_end_time"], errors="coerce", utc=True)
audit["release_after_first_old_activity"] = (release > first_seen).fillna(False)

audit["audit_status"] = "pass"
audit.loc[~audit["titan_product_found"], "audit_status"] = "BLOCKER_missing_titan_product"
audit.loc[
    audit["titan_product_found"] & audit["release_after_first_old_activity"], "audit_status"
] = "review_release_after_activity"
audit.loc[
    audit["titan_product_found"]
    & ~audit["release_after_first_old_activity"]
    & ~audit["provider_exact_match"],
    "audit_status",
] = "review_cross_provider"

audit = audit.sort_values(["audit_status", "mapping_source", "old_bets", KEY])
audit.to_csv(OUTPUT_CSV, index=False)
print(f"Wrote {OUTPUT_CSV.name}: {len(audit):,} mappings")
print(audit["audit_status"].value_counts().to_string())
