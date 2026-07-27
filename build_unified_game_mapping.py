"""Combine prior approved mappings with newly reviewed mappings for BigQuery.

Only mappings that are already approved and unambiguous are promoted.  Any
conflict is deliberately exported separately and excluded from the import file.
"""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
EXISTING_CSV = ROOT / "bragg_finnplay_mapping_reviewed_2.csv"
SEED_CSV = ROOT / "approved_game_mapping_seed.csv"
TITAN_CSV = ROOT / "titan_product_mapping_source.csv"
OUTPUT_CSV = ROOT / "unified_game_mapping_for_bigquery.csv"
CONFLICTS_CSV = ROOT / "unified_game_mapping_conflicts.csv"
KEY = "old_aggregator_game_code"


def require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{name} missing columns: {sorted(missing)}")


existing_raw = pd.read_csv(EXISTING_CSV, dtype=str).fillna("")
seed = pd.read_csv(SEED_CSV, dtype=str).fillna("")
titan = pd.read_csv(TITAN_CSV, dtype=str).fillna("")
require(existing_raw, {KEY, "final_titan_product_id", "needs_review"}, EXISTING_CSV.name)
require(seed, {KEY, "titan_product_id", "mapping_source", "mapping_confidence"}, SEED_CSV.name)

existing = existing_raw.loc[
    existing_raw["final_titan_product_id"].str.strip().ne("")
    & existing_raw["needs_review"].str.strip().str.lower().eq("false")
].copy()
existing = existing.rename(columns={"final_titan_product_id": "titan_product_id"})

existing_ids = existing.groupby(KEY)["titan_product_id"].agg(lambda ids: sorted(set(ids)))
seed_ids = seed.set_index(KEY)["titan_product_id"]
titan_ids = set(titan["titan_product_id"])

conflict_rows = []
resolved_codes: set[str] = set()
unresolved_codes: set[str] = set()
for code, prior_ids in existing_ids.items():
    seed_id = seed_ids.get(code)
    has_internal_conflict = len(prior_ids) > 1
    disagrees_with_seed = seed_id is not None and set(prior_ids) != {seed_id}
    if not (has_internal_conflict or disagrees_with_seed):
        continue

    # A newly reviewed mapping is allowed to replace a legacy value only when
    # its Titan ID is real and every contradictory legacy ID is absent from the
    # current Titan catalogue.  This catches stale/non-Titan IDs without
    # masking genuine current-catalogue disagreements.
    alternatives = set(prior_ids) - ({seed_id} if seed_id else set())
    can_use_seed = bool(seed_id in titan_ids and all(value not in titan_ids for value in alternatives))
    if can_use_seed:
        resolution = "resolved_use_new_reviewed_seed"
        resolved_codes.add(code)
    else:
        resolution = "excluded_unresolved_conflict"
        unresolved_codes.add(code)
    conflict_rows.append(
        {
            KEY: code,
            "preexisting_titan_product_ids": " | ".join(prior_ids),
            "new_seed_titan_product_id": seed_id or "",
            "resolution": resolution,
        }
    )

existing = existing.loc[~existing[KEY].isin(resolved_codes | unresolved_codes)].copy()
existing = existing.drop_duplicates(subset=[KEY], keep="first")
seed = seed.loc[~seed[KEY].isin(unresolved_codes)].copy()

existing_output = pd.DataFrame(
    {
        KEY: existing[KEY],
        "titan_product_id": existing["titan_product_id"],
        "old_game_name": existing.get("old_game_name", ""),
        "old_game_provider_name": existing.get("old_game_provider_name", ""),
        "old_bets": existing.get("old_bets", ""),
        "old_rounds": existing.get("old_rounds", ""),
        "mapping_source": "preexisting_reviewed_mapping",
        "mapping_confidence": existing.get("final_mapping_confidence", ""),
        "decision_status": existing.get("final_mapping_source", ""),
        "note": existing.get("usage_decision", ""),
    }
)
seed_output = seed[
    [
        KEY,
        "titan_product_id",
        "old_game_name",
        "old_game_provider_name",
        "old_bets",
        "old_rounds",
        "mapping_source",
        "mapping_confidence",
        "decision_status",
        "note",
    ]
]

# Same-ID overlap is harmless; retain the newer seed row so its detailed
# provenance wins.  Existing-only rows retain the original review provenance.
combined = pd.concat([existing_output, seed_output], ignore_index=True)
combined = combined.drop_duplicates(subset=[KEY], keep="last")
if combined[KEY].duplicated().any() or combined["titan_product_id"].eq("").any():
    raise ValueError("Unified mapping validation failed.")

combined = combined.sort_values(["mapping_source", "old_bets", KEY], ascending=[True, False, True])
# BigQuery's CSV loader does not accept quoted embedded newlines unless its
# allow-quoted-newlines option is enabled.  Keep the human-readable notes on
# one physical record line for a portable staging file.
for column in combined.columns:
    combined[column] = combined[column].astype(str).str.replace(r"[\r\n\t]+", " ", regex=True)
combined.to_csv(OUTPUT_CSV, index=False)

conflicts = pd.DataFrame(conflict_rows)
conflicts.to_csv(CONFLICTS_CSV, index=False)

print(f"Wrote {OUTPUT_CSV.name}: {len(combined):,} safe mappings")
print(f"Wrote {CONFLICTS_CSV.name}: {len(conflicts):,} reviewed conflicts")
print(f"Unresolved conflicts excluded: {len(unresolved_codes):,}")
print(combined["mapping_source"].value_counts().to_string())
