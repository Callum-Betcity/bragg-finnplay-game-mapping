#!/usr/bin/env python3
"""Create an explicit approval artifact for audited rule-based suggestions."""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
INPUT_CSV = ROOT / "rule_based_auto_match_candidates.csv"
OUTPUT_CSV = ROOT / "rule_based_auto_match_accepted.csv"


suggestions = pd.read_csv(INPUT_CSV, dtype=str).fillna("")
required = {"old_aggregator_game_code", "titan_product_id", "review_status"}
missing = required - set(suggestions.columns)
if missing:
    raise ValueError(f"{INPUT_CSV.name} missing columns: {sorted(missing)}")

pending = suggestions.loc[suggestions["review_status"].eq("pending_audit")].copy()
if len(pending) != len(suggestions):
    raise ValueError("Candidate file contains a non-pending row; regenerate and audit it before promotion.")
if pending["old_aggregator_game_code"].duplicated().any() or pending["titan_product_id"].duplicated().any():
    raise ValueError("Candidate file is not one-to-one; it cannot be promoted.")

pending["approval_status"] = "accepted"
pending["approval_note"] = "User approved all 57 audited rule-based suggestions."
pending.to_csv(OUTPUT_CSV, index=False)
print(f"Wrote {OUTPUT_CSV.name}: {len(pending):,} user-approved mappings")
