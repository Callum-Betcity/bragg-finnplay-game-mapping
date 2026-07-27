#!/usr/bin/env python3
"""Build auditable, conservative rule-based match suggestions.

This script is intentionally dry-run only. It never edits the unified mapping,
the manual decision log, or the existing fuzzy auto-accepted file.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
RULES_JSON = ROOT / "mapping_rules.json"
OLD_CSV = ROOT / "unmapped_bragg_games.csv"
OLD_ACTIVITY_CSV = ROOT / "old_bragg_games_source.csv"
TITAN_CSV = ROOT / "titan_product_mapping_source.csv"
DECISIONS_CSV = ROOT / "iterative_mapping_decisions.csv"
UNIFIED_CSV = ROOT / "unified_game_mapping_for_bigquery.csv"
FUZZY_AUTO_CSV = ROOT / "fuzzy_game_mapping_auto_accepted.csv"
OUTPUT_CSV = ROOT / "rule_based_auto_match_candidates.csv"
DEFERRED_CSV = ROOT / "rule_based_deferred_review.csv"
NO_EXACT_CSV = ROOT / "rule_based_no_exact_match.csv"


def key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def raw_tokens(value: object) -> list[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(value or ""))
    return re.findall(r"[a-z]+|\d+", text.lower())


def expand_tokens(tokens: list[str], abbreviations: dict[str, list[str]]) -> list[str]:
    expanded: list[str] = []
    for token in tokens:
        expanded.extend(abbreviations.get(token, [token]))
    return expanded


def drop_one_prefix(tokens: list[str], prefixes: list[str]) -> list[str]:
    if tokens and tokens[0] in prefixes:
        return tokens[1:]
    return tokens


def product_inner_prefix(product_name: object) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", str(product_name or "")) if part]
    # Wrapper prefixes (MG, RG, Oryx, OGS, QT, ISB, ST8, SPH) precede studio.
    if len(parts) >= 2 and key(parts[0]) in {
        "mg", "rg", "oryx", "ogs", "qt", "isb", "st8", "sph"
    }:
        return key(parts[1])
    return key(parts[0]) if parts else ""


def read_ids(path: Path, column: str) -> set[str]:
    if not path.exists():
        return set()
    frame = pd.read_csv(path, dtype=str).fillna("")
    return set(frame[column].astype(str)) if column in frame else set()


def main() -> None:
    config = json.loads(RULES_JSON.read_text())
    aliases = {key(k): key(v) for k, v in config["provider_aliases"].items()}
    abbreviations = {
        key(k): [key(item) for item in values]
        for k, values in config["title_abbreviations"].items()
    }
    source_prefixes = {
        key(provider): [key(item) for item in values]
        for provider, values in config["source_provider_prefixes"].items()
    }
    titan_prefixes = {
        key(provider): {key(item) for item in values}
        for provider, values in config["titan_studio_product_prefixes"].items()
    }
    route_review = {key(item) for item in config["provider_route_review_keys"]}
    manual_only_routes = {
        key(item) for item in config.get("manual_only_provider_route_candidates", [])
    }

    old = pd.read_csv(OLD_CSV, dtype=str).fillna("")
    titan = pd.read_csv(TITAN_CSV, dtype=str).fillna("")
    activity = pd.read_csv(OLD_ACTIVITY_CSV, dtype=str).fillna("")

    resolved_codes = (
        read_ids(DECISIONS_CSV, "old_aggregator_game_code")
        | read_ids(UNIFIED_CSV, "old_aggregator_game_code")
        | read_ids(FUZZY_AUTO_CSV, "old_aggregator_game_code")
    )
    used_titan_ids = read_ids(UNIFIED_CSV, "titan_product_id") | read_ids(
        FUZZY_AUTO_CSV, "titan_product_id"
    )

    first_seen = {}
    if {"old_aggregator_game_code", "old_min_end_time"} <= set(activity.columns):
        first_seen = activity.set_index("old_aggregator_game_code")[
            "old_min_end_time"
        ].to_dict()

    def canonical_provider(value: object) -> str:
        normalized = key(value)
        return aliases.get(normalized, normalized)

    titan = titan.drop_duplicates("titan_product_id").copy()
    title_index: dict[tuple[tuple[str, int], ...], list[int]] = defaultdict(list)
    titan_token_counters: list[Counter[str]] = []
    for idx, row in titan.iterrows():
        title = row["titan_friendly_name"] or row["cleaned_product_name"]
        counter = Counter(expand_tokens(raw_tokens(title), abbreviations))
        titan_token_counters.append(counter)
        title_index[tuple(sorted(counter.items()))].append(idx)

    # Pandas indices may not be positional after de-duplication.
    titan = titan.reset_index(drop=True)
    title_index.clear()
    for idx, row in titan.iterrows():
        title = row["titan_friendly_name"] or row["cleaned_product_name"]
        counter = Counter(expand_tokens(raw_tokens(title), abbreviations))
        title_index[tuple(sorted(counter.items()))].append(idx)

    candidates: list[dict[str, object]] = []
    deferred: list[dict[str, object]] = []
    no_exact: list[dict[str, object]] = []

    for _, source in old.iterrows():
        code = source["old_aggregator_game_code"]
        if code in resolved_codes:
            continue

        provider = canonical_provider(source["old_game_provider_name"])
        source_tokens = expand_tokens(raw_tokens(source["old_game_name"]), abbreviations)
        source_tokens = drop_one_prefix(source_tokens, source_prefixes.get(provider, []))
        signature = tuple(sorted(Counter(source_tokens).items()))
        exact_indices = title_index.get(signature, [])
        exact_ids = "|".join(
            str(titan.loc[idx, "titan_product_id"]) for idx in exact_indices[:10]
        )

        if provider in route_review:
            deferred.append({
                "old_aggregator_game_code": code,
                "old_game_name": source["old_game_name"],
                "old_game_provider_name": source["old_game_provider_name"],
                "reason": "provider_route_review",
                "candidate_count": len(exact_indices),
                "candidate_titan_product_ids": exact_ids,
                "rule_ids": "R004",
            })
            continue

        if provider in manual_only_routes:
            deferred.append({
                "old_aggregator_game_code": code,
                "old_game_name": source["old_game_name"],
                "old_game_provider_name": source["old_game_provider_name"],
                "reason": "provisional_provider_route",
                "candidate_count": len(exact_indices),
                "candidate_titan_product_ids": exact_ids,
                "rule_ids": "R014",
            })
            continue

        if not exact_indices:
            no_exact.append({
                "old_aggregator_game_code": code,
                "old_game_name": source["old_game_name"],
                "old_game_provider_name": source["old_game_provider_name"],
                "old_bets": source.get("old_bets", ""),
                "old_rounds": source.get("old_rounds", ""),
                "reason": "no_exact_normalized_title_candidate",
                "rule_ids": "R001|R007",
            })
            continue

        scored: list[tuple[int, int, list[str]]] = []
        for idx in exact_indices:
            target = titan.loc[idx]
            target_id = str(target["titan_product_id"])
            evidence = ["exact_title_tokens"]
            score = 100

            target_provider = canonical_provider(target["mapped_provider_name"])
            if provider and provider == target_provider:
                score += 30
                evidence.append("provider_identity")

            prefixes = titan_prefixes.get(provider, set())
            if prefixes and product_inner_prefix(target["titan_product_name"]) in prefixes:
                score += 25
                evidence.append("scoped_studio_product_prefix")

            if target_id in used_titan_ids:
                score -= 1000
                evidence.append("titan_id_already_used")

            scored.append((score, idx, evidence))

        scored.sort(key=lambda item: (-item[0], str(titan.loc[item[1], "titan_product_id"])))
        best_score = scored[0][0]
        best = [item for item in scored if item[0] == best_score]
        usable = [item for item in best if "titan_id_already_used" not in item[2]]

        if len(usable) != 1 or best_score < 125:
            deferred.append({
                "old_aggregator_game_code": code,
                "old_game_name": source["old_game_name"],
                "old_game_provider_name": source["old_game_provider_name"],
                "reason": "ambiguous_exact_title" if len(best) > 1 else "insufficient_provider_evidence",
                "candidate_count": len(scored),
                "candidate_titan_product_ids": "|".join(
                    str(titan.loc[item[1], "titan_product_id"]) for item in scored[:10]
                ),
                "rule_ids": "R001|R003|R005|R006",
            })
            continue

        _, idx, evidence = usable[0]
        target = titan.loc[idx]
        release = pd.to_datetime(target.get("RELEASE_DATE", ""), errors="coerce", utc=True)
        observed = pd.to_datetime(first_seen.get(code, ""), errors="coerce", utc=True)
        if pd.notna(release) and pd.notna(observed) and release > observed:
            deferred.append({
                "old_aggregator_game_code": code,
                "old_game_name": source["old_game_name"],
                "old_game_provider_name": source["old_game_provider_name"],
                "reason": "release_after_first_old_activity",
                "candidate_count": len(scored),
                "candidate_titan_product_ids": str(target["titan_product_id"]),
                "rule_ids": "R012",
            })
            continue

        candidates.append({
            "old_aggregator_game_code": code,
            "old_game_name": source["old_game_name"],
            "old_game_provider_name": source["old_game_provider_name"],
            "old_bets": source.get("old_bets", ""),
            "old_rounds": source.get("old_rounds", ""),
            "titan_product_id": target["titan_product_id"],
            "titan_product_name": target["titan_product_name"],
            "titan_friendly_name": target["titan_friendly_name"],
            "mapped_provider_name": target["mapped_provider_name"],
            "match_basis": "unique_exact_title_with_provider_or_studio_evidence",
            "evidence": "|".join(evidence),
            "rule_ids": "R001|R002|R003|R007|R012|R015",
            "review_status": "pending_audit",
        })

    # A one-to-one mapping is required. If this run independently proposes the
    # same Titan ID more than once, move every affected row back to review.
    candidate_frame = pd.DataFrame(candidates)
    if not candidate_frame.empty:
        duplicate_ids = set(
            candidate_frame.loc[
                candidate_frame["titan_product_id"].duplicated(keep=False),
                "titan_product_id",
            ].astype(str)
        )
        if duplicate_ids:
            retained = []
            for row in candidates:
                if str(row["titan_product_id"]) not in duplicate_ids:
                    retained.append(row)
                    continue
                deferred.append({
                    "old_aggregator_game_code": row["old_aggregator_game_code"],
                    "old_game_name": row["old_game_name"],
                    "old_game_provider_name": row["old_game_provider_name"],
                    "reason": "duplicate_titan_id_within_dry_run",
                    "candidate_count": 1,
                    "candidate_titan_product_ids": row["titan_product_id"],
                    "rule_ids": "R015",
                })
            candidates = retained

    candidate_columns = [
        "old_aggregator_game_code", "old_game_name", "old_game_provider_name",
        "old_bets", "old_rounds", "titan_product_id", "titan_product_name",
        "titan_friendly_name", "mapped_provider_name", "match_basis", "evidence",
        "rule_ids", "review_status",
    ]
    deferred_columns = [
        "old_aggregator_game_code", "old_game_name", "old_game_provider_name",
        "reason", "candidate_count", "candidate_titan_product_ids", "rule_ids",
    ]
    no_exact_columns = [
        "old_aggregator_game_code", "old_game_name", "old_game_provider_name",
        "old_bets", "old_rounds", "reason", "rule_ids",
    ]
    pd.DataFrame(candidates, columns=candidate_columns).to_csv(OUTPUT_CSV, index=False)
    pd.DataFrame(deferred, columns=deferred_columns).to_csv(DEFERRED_CSV, index=False)
    pd.DataFrame(no_exact, columns=no_exact_columns).to_csv(NO_EXACT_CSV, index=False)

    print(f"Wrote {len(candidates):,} pending candidates to {OUTPUT_CSV.name}")
    print(f"Wrote {len(deferred):,} deferred rows to {DEFERRED_CSV.name}")
    print(f"Wrote {len(no_exact):,} no-exact-title rows to {NO_EXACT_CSV.name}")
    if candidates:
        print("No existing mapping or decision files were modified.")


if __name__ == "__main__":
    main()
