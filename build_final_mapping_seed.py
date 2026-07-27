"""Build the approved mapping seed used for the single final warehouse join.

This intentionally does not modify iterative_mapping_decisions.csv: that file
remains the human-review audit log while fuzzy_game_mapping_auto_accepted.csv
remains the automated-review audit log.
"""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
QUEUE_CSV = ROOT / "unmapped_bragg_games.csv"
DECISIONS_CSV = ROOT / "iterative_mapping_decisions.csv"
AUTO_ACCEPTED_CSV = ROOT / "fuzzy_game_mapping_auto_accepted.csv"
PROVISIONAL_REVIEW_CSV = ROOT / "provisional_same_provider_top_matches.csv"
RULE_BASED_ACCEPTED_CSV = ROOT / "rule_based_auto_match_accepted.csv"
OUTPUT_CSV = ROOT / "approved_game_mapping_seed.csv"

KEY = "old_aggregator_game_code"


def require_columns(frame: pd.DataFrame, columns: set[str], source: Path) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{source.name} is missing columns: {sorted(missing)}")


queue = pd.read_csv(QUEUE_CSV, dtype=str).fillna("")
require_columns(queue, {KEY, "old_game_name", "old_game_provider_name", "old_bets", "old_rounds"}, QUEUE_CSV)
queue = queue.drop_duplicates(subset=[KEY]).copy()

decisions = pd.read_csv(DECISIONS_CSV, dtype=str).fillna("")
require_columns(decisions, {KEY, "titan_product_id", "status", "note"}, DECISIONS_CSV)
manual = decisions.loc[
    decisions["status"].eq("accepted") & decisions["titan_product_id"].str.strip().ne("")
].copy()
manual = manual.assign(
    mapping_source="manual_iterative_review",
    mapping_confidence="reviewed",
    decision_status="accepted",
)

auto = pd.read_csv(AUTO_ACCEPTED_CSV, dtype=str).fillna("")
require_columns(
    auto,
    {KEY, "titan_product_id"},
    AUTO_ACCEPTED_CSV,
)
# The matcher emits these fields in current runs.  Also support the earlier
# compact audit export already loaded into BigQuery by assigning the same,
# approved provenance during promotion.
if "mapping_source" not in auto:
    auto["mapping_source"] = "conservative_batch_matcher"
if "mapping_confidence" not in auto:
    auto["mapping_confidence"] = "exact_or_high_coverage"
if "status" not in auto:
    auto["status"] = "auto_accepted"
auto = auto.assign(
    decision_status=auto["status"],
    note="",
)

keep = [KEY, "titan_product_id", "mapping_source", "mapping_confidence", "decision_status", "note"]
approved = pd.concat([manual[keep], auto[keep]], ignore_index=True)

# Provisional same-provider suggestions are deliberately opt-in.  They become
# final mappings only after the reviewer changes review_status to "approved".
if PROVISIONAL_REVIEW_CSV.exists():
    provisional = pd.read_csv(PROVISIONAL_REVIEW_CSV, dtype=str).fillna("")
    require_columns(provisional, {KEY, "titan_product_id", "review_status"}, PROVISIONAL_REVIEW_CSV)
    provisional = provisional.loc[
        provisional["review_status"].str.strip().str.lower().eq("approved")
        & provisional["titan_product_id"].str.strip().ne("")
    ].copy()
    provisional = provisional.assign(
        mapping_source=provisional.get("mapping_source", "same_provider_top_candidate_review"),
        mapping_confidence="reviewed_provisional_top_candidate",
        decision_status="approved",
        note=provisional.get("review_note", ""),
    )
    approved = pd.concat([approved, provisional[keep]], ignore_index=True)

# Rule-based suggestions are kept in a separate approval artifact so that the
# original dry-run output remains reproducible and manual notebook decisions
# retain their own provenance.
if RULE_BASED_ACCEPTED_CSV.exists():
    rule_based = pd.read_csv(RULE_BASED_ACCEPTED_CSV, dtype=str).fillna("")
    require_columns(rule_based, {KEY, "titan_product_id", "approval_status"}, RULE_BASED_ACCEPTED_CSV)
    rule_based = rule_based.loc[
        rule_based["approval_status"].str.strip().str.lower().eq("accepted")
        & rule_based["titan_product_id"].str.strip().ne("")
    ].copy()
    rule_based = rule_based.assign(
        mapping_source="user_approved_rule_based_exact_match",
        mapping_confidence="exact_title_with_scoped_studio_evidence",
        decision_status="accepted",
        note=rule_based.get("approval_note", ""),
    )
    approved = pd.concat([approved, rule_based[keep]], ignore_index=True)

# One old code may appear in only one approved source.  A duplicate with the
# same Titan ID is harmless and is collapsed; conflicting IDs must be resolved
# before the warehouse update.
conflicts = (
    approved.groupby(KEY)["titan_product_id"]
    .nunique()
    .loc[lambda series: series > 1]
)
if not conflicts.empty:
    raise ValueError(
        "Conflicting approved Titan IDs for old codes: "
        + ", ".join(conflicts.index.tolist()[:20])
    )
approved = approved.drop_duplicates(subset=[KEY], keep="first")

approved = approved.merge(
    queue[[KEY, "old_game_name", "old_game_provider_name", "old_bets", "old_rounds"]],
    on=KEY,
    how="left",
    validate="one_to_one",
)
if approved["old_game_name"].eq("").any():
    missing = approved.loc[approved["old_game_name"].eq(""), KEY].tolist()
    raise ValueError(f"Approved codes missing from {QUEUE_CSV.name}: {missing[:20]}")

approved = approved[
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
].sort_values(["mapping_source", "old_bets", KEY], ascending=[True, False, True])

approved.to_csv(OUTPUT_CSV, index=False)
print(f"Wrote {OUTPUT_CSV.name}: {len(approved):,} approved mappings")
print(approved["mapping_source"].value_counts().to_string())
