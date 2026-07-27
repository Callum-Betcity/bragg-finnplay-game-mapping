"""Create an editable audit file for the remaining same-provider top candidates.

Rows are *not* final mappings until review_status is changed to ``approved``.
The source CSV preserves enough evidence to scan in BigQuery or a spreadsheet.
"""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
QUEUE_CSV = ROOT / "unmapped_bragg_games.csv"
DECISIONS_CSV = ROOT / "iterative_mapping_decisions.csv"
AUTO_ACCEPTED_CSV = ROOT / "fuzzy_game_mapping_auto_accepted.csv"
CANDIDATES_CSV = ROOT / "fuzzy_game_mapping_candidates_all.csv"
OUTPUT_CSV = ROOT / "provisional_same_provider_top_matches.csv"

KEY = "old_aggregator_game_code"


def require_columns(frame: pd.DataFrame, required: set[str], source: Path) -> None:
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{source.name} is missing columns: {sorted(missing)}")


queue = pd.read_csv(QUEUE_CSV, dtype=str).fillna("")
decisions = pd.read_csv(DECISIONS_CSV, dtype=str).fillna("")
auto = pd.read_csv(AUTO_ACCEPTED_CSV, dtype=str).fillna("")
candidates = pd.read_csv(CANDIDATES_CSV, dtype=str).fillna("")

require_columns(queue, {KEY}, QUEUE_CSV)
require_columns(decisions, {KEY}, DECISIONS_CSV)
require_columns(auto, {KEY}, AUTO_ACCEPTED_CSV)
require_columns(
    candidates,
    {
        KEY,
        "candidate_rank",
        "titan_product_id",
        "numeric_conflict",
        "match_quality",
        "token_overlap",
        "score_gap_to_second",
    },
    CANDIDATES_CSV,
)

resolved_codes = set(decisions[KEY].str.strip()) | set(auto[KEY].str.strip())
top = candidates.loc[
    candidates["candidate_rank"].eq("1")
    & ~candidates[KEY].isin(resolved_codes)
    & candidates["numeric_conflict"].str.lower().ne("true")
].copy()

for column in ("old_bets", "old_rounds", "match_quality", "token_overlap", "score_gap_to_second", "score_best"):
    if column in top:
        top[column] = pd.to_numeric(top[column], errors="coerce")

def outlier_flags(row: pd.Series) -> str:
    flags = []
    if row.get("token_overlap", 0) < 60:
        flags.append("low_coverage")
    if row.get("match_quality", 0) < 65:
        flags.append("low_quality")
    if row.get("score_gap_to_second", 0) < 3:
        flags.append("close_runner_up")
    if str(row.get("exact_normalized_title", "")).strip().lower() != "true":
        flags.append("not_exact_normalized_title")
    return ";".join(flags) or "none"

top["review_status"] = "provisionally_approved"
top["outlier_flags"] = top.apply(outlier_flags, axis=1)
top["mapping_source"] = "same_provider_top_candidate_review"
top["mapping_confidence"] = "provisional_pending_scan"
top["review_note"] = ""

columns = [
    KEY,
    "titan_product_id",
    "old_game_name",
    "old_game_provider_name",
    "old_bets",
    "old_rounds",
    "titan_product_name",
    "titan_friendly_name",
    "mapped_provider_name",
    "review_status",
    "outlier_flags",
    "mapping_source",
    "mapping_confidence",
    "review_note",
    "match_quality",
    "score_best",
    "token_overlap",
    "score_gap_to_second",
    "best_match_method",
    "exact_normalized_title",
    "family_rule_match",
]
top = top[[column for column in columns if column in top.columns]]
top = top.sort_values(["old_bets", "match_quality"], ascending=[False, False])
top.to_csv(OUTPUT_CSV, index=False)

print(f"Wrote {OUTPUT_CSV.name}: {len(top):,} provisional same-provider top matches")
print("Outlier flags:")
print(top["outlier_flags"].value_counts().to_string())
print()
print("To promote a reviewed row, set review_status to 'approved'.")
