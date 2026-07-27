import re
import pandas as pd
from rapidfuzz import fuzz, process

# Run the batch pass only against the unresolved queue.  This avoids reprocessing
# the full historical source and keeps the audit focused on genuinely new matches.
OLD_GAMES_CSV = "unmapped_bragg_games.csv"
TITAN_PRODUCTS_CSV = "titan_product_mapping_source.csv"
EXISTING_MAPPING_CSV = "bragg_finnplay_mapping_reviewed.csv"  # optional
DECISIONS_CSV = "iterative_mapping_decisions.csv"  # optional manual-review audit log

OUTPUT_ALL = "fuzzy_game_mapping_candidates_all.csv"
OUTPUT_REVIEW = "fuzzy_game_mapping_candidates_review.csv"
OUTPUT_AUTO_ACCEPTED = "fuzzy_game_mapping_auto_accepted.csv"

# Fast native RapidFuzz prefilter.  The detailed scorer then evaluates the best
# candidates only, preserving a credible runner-up comparison without repeatedly
# running Python/regex work against every product in a large provider catalogue.
CANDIDATE_PREFILTER_LIMIT = 100


# -----------------------------
# Normalisation helpers
# -----------------------------

PROVIDER_PREFIXES = [
    "evold", "evo", "ev", "evr", "evn", "netee", "ne", "rtg", "rt",
    "png", "pg",
    "ppd", "ppn", "pp",
    "plsm", "pls",
    "mgsm", "mgsd", "mgs", "mg",
    "gtb", "gt",
    "stk", "stl",
    "relax", "rg",
    "gc",
    "hks", "hg",
    "ogs",
    "oryx",
    "egt", "amu",
    "am",
    "bp", "bl",
    "swintt", "swi",
    "ztr",
]

PROVIDER_ALIAS = {
    "playngo": "playngo",
    "playngo": "playngo",
    "playn go": "playngo",
    "png": "playngo",
    "pg": "playngo",

    "pragmaticplay": "pragmaticplay",
    "pp": "pragmaticplay",
    "ppn": "pragmaticplay",
    "ppd": "pragmaticplay",

    "evolution": "evolution",
    "evol": "evolution",
    "evold": "evolution",
    "evr": "evolution",
    "evn": "evolution",
    "netent": "evolution",
    "redtiger": "evolution",

    "greentube": "greentube",
    "gtb": "greentube",
    "gt": "greentube",

    "gamesglobal": "gamesglobal",
    "games global": "gamesglobal",
    "mgs": "gamesglobal",
    "mg": "gamesglobal",
    "mgsm": "gamesglobal",
    "mgsd": "gamesglobal",

    "stakelogic": "stakelogic",
    "stk": "stakelogic",
    "stl": "stakelogic",

    "relaxgaming": "relaxgaming",
    "relax gaming": "relaxgaming",
    "relax": "relaxgaming",
    "rg": "relaxgaming",

    "amusnetinteractive": "amusnet",
    "amusnet interactive": "amusnet",
    "amusnet": "amusnet",
    "egt": "amusnet",

    "blueprintgaming": "blueprint",
    "blueprint gaming": "blueprint",
    "bp": "blueprint",
    "bl": "blueprint",

    "zitro": "zitro",
    "ztr": "zitro",
}

# Only established, title-level abbreviations belong here.  Keep this short: an
# over-broad expansion is more dangerous than leaving a record for review.
ABBREVIATIONS = {
    "jk": "jackpot king",
    "jpk": "jackpot king",
    "jp": "jackpot",
    "mw": "megaways",
    "megs": "megaways",
    "del": "deluxe",
}

# Verified from the Pragmatic Live Blackjack Azure family.  This is deliberately
# scoped below; it must not become a global number-to-letter substitution rule.
AZURE_ORDINALS = {"1": "a", "2": "b", "3": "c", "4": "d", "5": "e"}


def norm_provider(value: str) -> str:
    if pd.isna(value):
        return ""
    s = str(value).lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return PROVIDER_ALIAS.get(s, s)


def basic_norm(value: str) -> str:
    if pd.isna(value):
        return ""
    s = str(value).lower()
    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def strip_provider_prefix(name: str) -> str:
    """
    Removes common leading provider/product prefixes from normalised names.
    Example:
      gtbsilverluxbigwinspinner -> silverluxbigwinspinner
      pngbookofdead -> bookofdead
      ppngatesofolympus -> gatesofolympus
    """
    s = basic_norm(name)

    changed = True
    while changed:
        changed = False
        for prefix in sorted(PROVIDER_PREFIXES, key=len, reverse=True):
            if s.startswith(prefix) and len(s) > len(prefix) + 3:
                s = s[len(prefix):]
                changed = True
                break

    return s


def tokenish(value: str) -> str:
    """
    A looser readable token string for rapidfuzz token scores.
    """
    if pd.isna(value):
        return ""
    s = str(value)
    s = s.replace("_", " ")
    s = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    # Titan product IDs often use a lowercase version marker without a boundary,
    # e.g. HyperGoldv94.  Treat only v+digits as a version token.
    s = re.sub(r"(?<=[a-z])v(?=\d)", " v", s)
    s = re.sub(r"([a-z])([0-9])", r"\1 \2", s)
    s = s.lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokens(value: str, expand: bool = True) -> list[str]:
    """CamelCase-aware tokens, optionally expanding established abbreviations."""
    if pd.isna(value):
        return []
    s = str(value).replace("&", " and ")
    s = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"(?<=[a-z])v(?=\d)", " v", s)
    s = re.sub(r"([a-z])([0-9])", r"\1 \2", s)
    s = re.sub(r"([0-9])([a-z])", r"\1 \2", s)
    raw = re.sub(r"[^a-z0-9]+", " ", s.lower()).split()
    if not expand:
        return raw
    return [expanded for token in raw for expanded in ABBREVIATIONS.get(token, token).split()]


def compact_tokens(value: str, expand: bool = True) -> str:
    return "".join(tokens(value, expand=expand))


def strip_leading_provider_tokens(value: str) -> list[str]:
    """Remove only known source/provider prefixes from a title comparison."""
    result = tokens(value, expand=False)
    prefixes = set(PROVIDER_PREFIXES) | set(PROVIDER_ALIAS)
    while result and result[0] in prefixes:
        result = result[1:]
    return result


def title_key(value: str) -> str:
    """Strict title key used only for safe exact-title acceptance."""
    return "".join(strip_leading_provider_tokens(value))


def azure_ordinal_match(old_name: str, product_name: str, friendly_name: str) -> bool:
    """Match only the verified Pragmatic Live Blackjack Azure ordinal family."""
    old_terms = set(tokens(old_name, expand=False))
    target_terms = set(tokens(product_name, expand=False)) | set(tokens(friendly_name, expand=False))
    required = {"live", "blackjack", "azure"}
    if not required.issubset(old_terms) or not required.issubset(target_terms):
        return False
    ordinal = next((number for number in AZURE_ORDINALS if number in old_terms), None)
    return bool(ordinal and AZURE_ORDINALS[ordinal] in target_terms)


def name_features(value: str) -> dict:
    """Precompute name representations so batch matching does not re-tokenise Titan rows."""
    raw_tokens = tokens(value, expand=False)
    expanded_tokens = tokens(value, expand=True)
    return {
        "raw_tokens": raw_tokens,
        "expanded_tokens": expanded_tokens,
        "raw_text": " ".join(raw_tokens),
        "expanded_text": " ".join(expanded_tokens),
        "raw_compact": "".join(raw_tokens),
        "expanded_compact": "".join(expanded_tokens),
        "expanded_set": set(expanded_tokens),
        "title_key": "".join(strip_leading_provider_tokens(value)),
        "numbers": numeric_tokens(value),
    }


def azure_ordinal_feature_match(old_features: dict, product_features: dict, friendly_features: dict) -> bool:
    old_terms = set(old_features["raw_tokens"])
    target_terms = set(product_features["raw_tokens"]) | set(friendly_features["raw_tokens"])
    required = {"live", "blackjack", "azure"}
    if not required.issubset(old_terms) or not required.issubset(target_terms):
        return False
    ordinal = next((number for number in AZURE_ORDINALS if number in old_terms), None)
    return bool(ordinal and AZURE_ORDINALS[ordinal] in target_terms)


def score_name_features(old_features: dict, product_features: dict, friendly_features: dict) -> dict:
    """Score already-tokenised old/product/friendly names."""
    comparisons = []
    for label, target in (("product", product_features), ("friendly", friendly_features)):
        for suffix, old_text, target_text, old_compact, target_compact in (
            ("literal", old_features["raw_text"], target["raw_text"], old_features["raw_compact"], target["raw_compact"]),
            ("expanded", old_features["expanded_text"], target["expanded_text"], old_features["expanded_compact"], target["expanded_compact"]),
        ):
            comparisons.append((f"{label}_token_set_{suffix}", fuzz.token_set_ratio(old_text, target_text)))
            comparisons.append((f"{label}_partial_{suffix}", fuzz.partial_ratio(old_compact, target_compact)))

    best_match_method, best_score = max(comparisons, key=lambda item: item[1])
    product_score = max(score for method, score in comparisons if method.startswith("product_"))
    friendly_score = max(score for method, score in comparisons if method.startswith("friendly_"))
    titan_terms = product_features["expanded_set"] | friendly_features["expanded_set"]
    shared_terms = old_features["expanded_set"] & titan_terms
    token_overlap = round(100 * len(shared_terms) / max(1, len(old_features["expanded_set"])), 2)
    target_token_coverage = round(100 * len(shared_terms) / max(1, len(titan_terms)), 2)
    family_rule_match = azure_ordinal_feature_match(old_features, product_features, friendly_features)
    match_quality = round(0.4 * best_score + 0.6 * token_overlap, 2)
    if family_rule_match:
        match_quality = max(match_quality, 99.0)
    return {
        "score_best": round(best_score, 2),
        "score_product": product_score,
        "score_friendly": friendly_score,
        "best_match_method": best_match_method,
        "token_overlap": token_overlap,
        "target_token_coverage": target_token_coverage,
        "match_quality": match_quality,
        "family_rule_match": family_rule_match,
        "exact_normalized_title": old_features["title_key"] in {
            product_features["title_key"], friendly_features["title_key"]
        },
    }


def numeric_tokens(value: str) -> set[str]:
    if pd.isna(value):
        return set()
    return set(re.findall(r"\d+", str(value)))


def score_names(old_name: str, titan_product_name: str, titan_friendly_name: str) -> dict:
    """
    Scores old name against both Titan PRODUCT_NAME and FRIENDLY_NAME.
    Returns the best score plus the specific comparison that produced it.
    """
    old_norm = basic_norm(old_name)
    old_core = strip_provider_prefix(old_name)
    old_tok = tokenish(old_name)

    product_norm = basic_norm(titan_product_name)
    product_core = strip_provider_prefix(titan_product_name)
    product_tok = tokenish(titan_product_name)

    friendly_norm = basic_norm(titan_friendly_name)
    friendly_core = strip_provider_prefix(titan_friendly_name)
    friendly_tok = tokenish(titan_friendly_name)

    comparisons = []
    for label, value in (("product", titan_product_name), ("friendly", titan_friendly_name)):
        for expanded in (False, True):
            old_terms = tokens(old_name, expand=expanded)
            target_terms = tokens(value, expand=expanded)
            comparisons.append((
                f"{label}_token_set_" + ("expanded" if expanded else "literal"),
                fuzz.token_set_ratio(" ".join(old_terms), " ".join(target_terms)),
            ))
            comparisons.append((
                f"{label}_partial_" + ("expanded" if expanded else "literal"),
                fuzz.partial_ratio(compact_tokens(old_name, expanded), compact_tokens(value, expanded)),
            ))

    best_match_method, best_score = max(comparisons, key=lambda item: item[1])
    product_score = max(score for method, score in comparisons if method.startswith("product_"))
    friendly_score = max(score for method, score in comparisons if method.startswith("friendly_"))

    old_terms = set(tokens(old_name, expand=True))
    titan_terms = set(tokens(titan_product_name, expand=True)) | set(tokens(titan_friendly_name, expand=True))
    token_overlap = round(100 * len(old_terms & titan_terms) / max(1, len(old_terms)), 2)
    family_rule_match = azure_ordinal_match(old_name, titan_product_name, titan_friendly_name)
    match_quality = round(0.4 * best_score + 0.6 * token_overlap, 2)
    if family_rule_match:
        match_quality = max(match_quality, 99.0)

    return {
        "score_best": round(best_score, 2),
        "score_product": product_score,
        "score_friendly": friendly_score,
        "best_match_method": best_match_method,
        "token_overlap": token_overlap,
        "match_quality": match_quality,
        "family_rule_match": family_rule_match,
        "exact_normalized_title": title_key(old_name) in {
            title_key(titan_product_name), title_key(titan_friendly_name)
        },
        "old_name_norm": old_norm,
        "old_name_core": old_core,
        "product_name_norm": product_norm,
        "product_name_core": product_core,
        "friendly_name_norm": friendly_norm,
        "friendly_name_core": friendly_core,
    }


def has_numeric_conflict(old_name: str, titan_product_name: str, titan_friendly_name: str) -> bool:
    """
    Flags cases like Blackjack 2 -> Blackjack 1, Royal Coins 2 -> Royal Coins 3.
    Empty numeric set on one side is not automatically a conflict because many product IDs include version/RTP.
    """
    old_nums = numeric_tokens(old_name)
    product_nums = numeric_tokens(titan_product_name)
    friendly_nums = numeric_tokens(titan_friendly_name)

    titan_nums = product_nums.union(friendly_nums)

    if not old_nums or not titan_nums:
        return False

    # RTP/version numbers like 92/94/96 are common and may be legitimate.
    ignore = {"92", "94", "96"}
    old_reduced = old_nums - ignore
    titan_reduced = titan_nums - ignore

    if not old_reduced or not titan_reduced:
        return False

    return old_reduced != titan_reduced


# -----------------------------
# Load data
# -----------------------------

old = pd.read_csv(OLD_GAMES_CSV, dtype=str)
titan = pd.read_csv(TITAN_PRODUCTS_CSV, dtype=str)

# Numeric fields
for col in ["old_rounds", "old_bets", "old_wins"]:
    if col in old.columns:
        old[col] = pd.to_numeric(old[col], errors="coerce").fillna(0)

# Provider normalisation
old["old_provider_key"] = old["old_game_provider_name"].apply(norm_provider)
titan["titan_provider_key"] = titan["mapped_provider_name"].apply(norm_provider)

# Name fields fallback
titan["titan_product_name"] = titan["titan_product_name"].fillna("")
titan["titan_friendly_name"] = titan["titan_friendly_name"].fillna("")
titan["_product_features"] = titan["titan_product_name"].map(name_features)
titan["_friendly_features"] = titan["titan_friendly_name"].map(name_features)
titan["_search_text"] = titan.apply(
    lambda row: f"{row['_product_features']['expanded_text']} {row['_friendly_features']['expanded_text']}",
    axis=1,
)


# -----------------------------
# Candidate generation
# -----------------------------

candidate_rows = []

# Block mostly by provider. Also allow cross-provider wrapper matching later for very high scores.
providers = sorted(set(old["old_provider_key"].dropna()) | set(titan["titan_provider_key"].dropna()))

for provider_key in providers:
    old_block = old[old["old_provider_key"] == provider_key]
    titan_block = titan[titan["titan_provider_key"] == provider_key]

    if old_block.empty or titan_block.empty:
        continue

    titan_records = titan_block.to_dict("records")
    titan_choices = [record["_search_text"] for record in titan_records]

    for _, old_row in old_block.iterrows():
        old_name = old_row["old_game_name"]
        old_features = name_features(old_name)
        shortlisted = process.extract(
            old_features["expanded_text"],
            titan_choices,
            scorer=fuzz.token_set_ratio,
            limit=min(CANDIDATE_PREFILTER_LIMIT, len(titan_choices)),
        )

        scored = []
        for _, _, choice_index in shortlisted:
            t_row = titan_records[choice_index]
            scores = score_name_features(
                old_features,
                t_row["_product_features"],
                t_row["_friendly_features"],
            )

            numeric_conflict = has_numeric_conflict(
                old_name,
                t_row["titan_product_name"],
                t_row["titan_friendly_name"],
            )

            scored.append({
                **old_row.to_dict(),
                **{
                    "titan_product_id": t_row["titan_product_id"],
                    "titan_product_name": t_row["titan_product_name"],
                    "titan_friendly_name": t_row["titan_friendly_name"],
                    "titan_provider_id": t_row.get("titan_provider_id"),
                    "titan_provider_name_raw": t_row.get("titan_provider_name_raw"),
                    "mapped_provider_code": t_row.get("mapped_provider_code"),
                    "mapped_provider_name": t_row.get("mapped_provider_name"),
                    "provider_exact_match": True,
                    "numeric_conflict": numeric_conflict,
                },
                **scores,
            })

        top = sorted(scored, key=lambda x: x["score_best"], reverse=True)[:5]
        candidate_rows.extend(top)


candidates = pd.DataFrame(candidate_rows)

# Rank and second-best gap
candidates = candidates.sort_values(
    ["old_aggregator_game_code", "old_game_name", "old_game_provider_name", "match_quality", "score_best", "token_overlap"],
    ascending=[True, True, True, False, False, False],
)

candidates["candidate_rank"] = (
    candidates
    .groupby(["old_aggregator_game_code", "old_game_name", "old_game_provider_name"])
    .cumcount() + 1
)

top_scores = (
    candidates
    .pivot_table(
        index=["old_aggregator_game_code", "old_game_name", "old_game_provider_name"],
        columns="candidate_rank",
        values="match_quality",
        aggfunc="first",
    )
    .reset_index()
    .rename(columns={1: "top_score", 2: "second_score"})
)

candidates = candidates.merge(
    top_scores,
    on=["old_aggregator_game_code", "old_game_name", "old_game_provider_name"],
    how="left",
)

candidates["score_gap_to_second"] = candidates["top_score"] - candidates["second_score"].fillna(0)


# -----------------------------
# Existing mapping conflict check
# -----------------------------

try:
    existing = pd.read_csv(EXISTING_MAPPING_CSV, dtype=str)
    existing = existing[
        existing["final_titan_product_id"].notna()
        & (existing["final_titan_product_id"] != "")
    ].copy()

    existing_key_cols = [
        "old_aggregator_game_code",
        "old_game_name",
        "old_game_provider_name",
        "final_titan_product_id",
        "final_mapping_source",
        "final_mapping_confidence",
        "needs_review",
    ]

    existing = existing[[c for c in existing_key_cols if c in existing.columns]].drop_duplicates()

    # Already mapped same old identity
    same_old = existing.rename(columns={"final_titan_product_id": "titan_product_id"})
    candidates = candidates.merge(
        same_old.assign(existing_same_old_mapping=True),
        on=["old_aggregator_game_code", "old_game_name", "old_game_provider_name", "titan_product_id"],
        how="left",
    )
    candidates["existing_same_old_mapping"] = candidates["existing_same_old_mapping"].fillna(False)

    # Titan product already mapped to another old identity
    mapped_products = existing.rename(columns={"final_titan_product_id": "titan_product_id"})
    conflicts = candidates.merge(
        mapped_products,
        on="titan_product_id",
        how="left",
        suffixes=("", "_existing"),
    )

    conflicts["conflicts_with_existing_mapping"] = (
        conflicts["old_aggregator_game_code_existing"].notna()
        & ~(
            (conflicts["old_aggregator_game_code"] == conflicts["old_aggregator_game_code_existing"])
            & (conflicts["old_game_name"] == conflicts["old_game_name_existing"])
            & (conflicts["old_game_provider_name"] == conflicts["old_game_provider_name_existing"])
        )
    )

    conflict_any = (
        conflicts
        .groupby(["old_aggregator_game_code", "old_game_name", "old_game_provider_name", "titan_product_id"])
        ["conflicts_with_existing_mapping"]
        .max()
        .reset_index()
    )

    candidates = candidates.merge(
        conflict_any,
        on=["old_aggregator_game_code", "old_game_name", "old_game_provider_name", "titan_product_id"],
        how="left",
    )
    candidates["conflicts_with_existing_mapping"] = candidates["conflicts_with_existing_mapping"].fillna(False)

except FileNotFoundError:
    candidates["existing_same_old_mapping"] = False
    candidates["conflicts_with_existing_mapping"] = False


# Never turn a human-reviewed item into an automated decision.  The notebook CSV
# is the source of truth for accepted, deferred, and no-match decisions.
if pd.io.common.file_exists(DECISIONS_CSV):
    manual_decisions = pd.read_csv(DECISIONS_CSV, dtype=str).fillna("")
    manually_reviewed_codes = set(manual_decisions["old_aggregator_game_code"].str.strip())
else:
    manually_reviewed_codes = set()

candidates["already_manually_reviewed"] = candidates["old_aggregator_game_code"].isin(manually_reviewed_codes)


# -----------------------------
# Decision buckets
# -----------------------------

def decision(row) -> str:
    if row["existing_same_old_mapping"]:
        return "already_mapped_same_old_identity"

    if row["candidate_rank"] != 1:
        return "lower_rank_candidate"

    if row["numeric_conflict"]:
        return "manual_review_numeric_conflict"

    if row["conflicts_with_existing_mapping"]:
        if row["score_best"] >= 98 and row["score_gap_to_second"] >= 5:
            return "manual_review_existing_product_mapping"
        return "manual_review_existing_product_mapping_weak"

    if row["match_quality"] >= 94 and row["score_gap_to_second"] >= 10:
        return "auto_candidate_high"

    if row["score_best"] >= 92 and row["score_gap_to_second"] >= 8:
        return "review_candidate_medium_high"

    if row["score_best"] >= 85:
        return "review_candidate_medium"

    return "weak_candidate"


candidates["mapping_decision"] = candidates.apply(decision, axis=1)


# Conservative batch approval.  A record must be provider-blocked, rank first,
# have no numeric or existing-mapping conflict, and meet one of three strong
# pieces of evidence: an unambiguous strict title, the scoped Azure family rule,
# or high token coverage plus a substantial lead over candidate #2.
exact_title_count = (
    candidates[candidates["exact_normalized_title"]]
    .groupby("old_aggregator_game_code")["titan_product_id"]
    .nunique()
)
candidates["exact_title_candidate_count"] = candidates["old_aggregator_game_code"].map(exact_title_count).fillna(0).astype(int)

base_safe = (
    candidates["candidate_rank"].eq(1)
    & ~candidates["numeric_conflict"]
    & ~candidates["conflicts_with_existing_mapping"]
    & ~candidates["existing_same_old_mapping"]
    & ~candidates["already_manually_reviewed"]
)
exact_title_safe = candidates["exact_normalized_title"] & candidates["exact_title_candidate_count"].eq(1)
family_rule_safe = candidates["family_rule_match"]
high_coverage_safe = (
    candidates["match_quality"].ge(94)
    & candidates["token_overlap"].ge(90)
    & candidates["target_token_coverage"].ge(90)
    & candidates["score_gap_to_second"].ge(10)
)

candidates["auto_accept_reason"] = ""
candidates.loc[base_safe & high_coverage_safe, "auto_accept_reason"] = "high_coverage_clear_lead"
candidates.loc[base_safe & exact_title_safe, "auto_accept_reason"] = "exact_normalized_title"
candidates.loc[base_safe & family_rule_safe, "auto_accept_reason"] = "verified_azure_ordinal_family"
candidates["auto_accepted"] = candidates["auto_accept_reason"].ne("")

print("Best match methods for rank-1 candidates:", flush=True)
print(
    candidates[candidates["candidate_rank"] == 1]["best_match_method"]
    .value_counts(dropna=False)
    .to_string(),
    flush=True,
)


# -----------------------------
# Save outputs
# -----------------------------

# All top 5 candidates
candidates.to_csv(OUTPUT_ALL, index=False)

# Review file: mainly rank 1 candidates, sorted by commercial importance
review_cols = [
    "mapping_decision",
    "candidate_rank",
    "old_aggregator_game_code",
    "old_game_name",
    "old_game_provider_code",
    "old_game_provider_name",
    "old_game_type_name",
    "old_rounds",
    "old_bets",
    "old_wins",
    "titan_product_id",
    "titan_product_name",
    "titan_friendly_name",
    "mapped_provider_code",
    "mapped_provider_name",
    "score_best",
    "score_product",
    "score_friendly",
    "best_match_method",
    "match_quality",
    "token_overlap",
    "target_token_coverage",
    "family_rule_match",
    "exact_normalized_title",
    "exact_title_candidate_count",
    "already_manually_reviewed",
    "auto_accepted",
    "auto_accept_reason",
    "score_gap_to_second",
    "numeric_conflict",
    "conflicts_with_existing_mapping",
    "existing_same_old_mapping",
    "old_name_core",
    "product_name_core",
    "friendly_name_core",
]

review = candidates[candidates["candidate_rank"] <= 3].copy()
review = review[[c for c in review_cols if c in review.columns]]
review = review.sort_values(
    ["mapping_decision", "old_bets", "score_best"],
    ascending=[True, False, False],
)

review.to_csv(OUTPUT_REVIEW, index=False)

# Keep automatic decisions separate from both the notebook audit log and the
# candidate file.  They are ready for a later sampled QA pass before promotion.
auto_accept_cols = [
    "old_aggregator_game_code",
    "old_game_name",
    "old_game_provider_name",
    "old_bets",
    "old_rounds",
    "titan_product_id",
    "titan_product_name",
    "titan_friendly_name",
    "mapped_provider_name",
    "status",
    "mapping_source",
    "mapping_confidence",
    "auto_accept_reason",
    "match_quality",
    "score_best",
    "token_overlap",
    "target_token_coverage",
    "score_gap_to_second",
    "family_rule_match",
    "exact_normalized_title",
]
auto_accepted = candidates[candidates["auto_accepted"]].copy()
auto_accepted["status"] = "auto_accepted"
auto_accepted["mapping_source"] = "conservative_batch_matcher"
auto_accepted["mapping_confidence"] = "exact_or_high_coverage"
auto_accepted = auto_accepted[[column for column in auto_accept_cols if column in auto_accepted.columns]]
auto_accepted = auto_accepted.sort_values(["old_bets", "match_quality"], ascending=[False, False])
auto_accepted.to_csv(OUTPUT_AUTO_ACCEPTED, index=False)

print(f"Saved {OUTPUT_ALL}: {len(candidates):,} rows")
print(f"Saved {OUTPUT_REVIEW}: {len(review):,} rows")
print(f"Saved {OUTPUT_AUTO_ACCEPTED}: {len(auto_accepted):,} rows")
print()
print(candidates["mapping_decision"].value_counts(dropna=False))
