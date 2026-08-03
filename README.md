# Bragg–Finnplay game mapping

An auditable workflow for mapping legacy Bragg/Finnplay game codes to Titan
product IDs. The process combines guarded matching, human review, and a single
downstream mapping output for BigQuery.

## The one file used downstream

`unified_game_mapping_for_bigquery.csv` is the **only** mapping CSV that should
be uploaded to BigQuery or joined to `game_rounds` and `daily_player_games`.

All other CSVs are source inputs, review logs, candidate queues, or audit
reports. They support the decision-making process; they are not downstream
mapping tables.

## Data flow

```text
Legacy game/activity exports + Titan catalogue + existing reviewed mappings
                              |
                              v
             fuzzy/rule-based candidate generation
                              |
                              v
              iterative_discovery.ipynb human review
                              |
                              v
              iterative_mapping_decisions.csv
                              |
                              v
  approved_game_mapping_seed.csv + approved_game_mapping_audit.csv
                              |
                              v
unified_game_mapping_for_bigquery.csv + unified_game_mapping_audit.csv
                              |
                              v
       BigQuery mapping table -> game_rounds / daily_player_games
```

## File roles

| Layer | Main files | Purpose |
|---|---|---|
| Source inputs | `old_bragg_games_source.csv`, `titan_product_mapping_source.csv`, `bragg_finnplay_mapping_reviewed_2.csv` | Legacy games, Titan catalogue, and pre-existing reviewed mappings. |
| Review state | `iterative_mapping_decisions.csv`, `iterative_discovery.ipynb` | Human accept/reject/defer decisions and the notebook that records them. |
| Candidate queues | `fuzzy_game_mapping_candidates_all.csv`, `provisional_same_provider_top_matches.csv`, `rule_based_*` | Suggestions awaiting review, deferred provider routes, or explicit promotion. |
| Approved intermediate | `approved_game_mapping_seed.csv` | Inputs accepted in this run before they are combined with pre-existing mappings. |
| Delivery output | `unified_game_mapping_for_bigquery.csv` | The sole BigQuery upload and downstream join file. |
| Audit reports | `approved_game_mapping_audit.csv`, `unified_game_mapping_audit.csv`, `unified_game_mapping_conflicts.csv` | Explain provenance, risk flags, and conflict handling. |
| Rules | `MAPPING_RULES_AUDIT.md`, `mapping_rules.json` | Human-readable assumptions and their machine-readable counterparts. |

## Review principles

- Prefer exact title and configuration identity; do not silently ignore editions,
  jackpots, Megaways, or other material qualifiers.
- A Titan mapped provider can be a delivery/catalogue route rather than the game
  studio. Treat route ambiguity as **deferred**, not as a forced match or a
  no-match.
- Record a notebook note for every non-obvious decision—especially omitted
  configuration tokens, studio-prefix evidence, or an intentionally excluded
  variant.
- `MAPPING_RULES_AUDIT.md` records which assumptions are active, provisional, or
  disabled. Do not turn a single manual decision into a general matching rule.

## Workflow

### 1. Generate and review candidates

```bash
venv/bin/python fuzzy_match.py
venv/bin/python build_rule_based_auto_matches.py
```

Use `iterative_discovery.ipynb` for same-provider, cross-provider, and
provider-route review. Decisions are saved to `iterative_mapping_decisions.csv`.

The rule-based dry run produces:

- `rule_based_auto_match_candidates.csv` — guarded suggestions pending review.
- `rule_based_deferred_review.csv` — provider-route ambiguity, ties, and release-date blockers.
- `rule_based_no_exact_match.csv` — remaining games without an exact title candidate.

Promotion of reviewed rule-based candidates is explicit:

```bash
venv/bin/python promote_rule_based_auto_matches.py
```

### 2. Build the accepted mapping and audit it

After review decisions have been saved, run:

```bash
venv/bin/python build_final_mapping_seed.py
venv/bin/python audit_approved_mapping.py
venv/bin/python build_unified_game_mapping.py
venv/bin/python audit_unified_game_mapping.py
```

Before uploading, sample `unified_game_mapping_audit.csv`, prioritising
`review_cross_provider` and `review_release_after_activity` rows by `old_bets`.
Correct any bad decision in the notebook, rerun the four commands above, and
sample again.

### 3. Load to BigQuery

Upload `unified_game_mapping_for_bigquery.csv` to the approved mapping table.
Use the stable legacy `aggregator_game_code` join described in
[`sql/game_rounds_unified_mapping_changes.sql`](sql/game_rounds_unified_mapping_changes.sql)
to update `game_rounds` and `daily_player_games`.

Keep unresolved provider-route cases deferred. Export them—with legacy code,
legacy provider/title, bets, and competing Titan routes—for Casino to verify.

### 4. Classify subproviders for dashboarding

Keep provider taxonomy separate from the activity facts. The taxonomy has three
reporting dimensions:

- `aggregation_platform` — OSS, OGS, Relax, or Bragg.
- `provider_group` — Evolution, Light & Wonder, Relax, or Bragg.
- `game_subprovider` — for example NetEnt, ELK Studios, Silver Bullet, or Fazi.

[`sql/game_subprovider_taxonomy.sql`](sql/game_subprovider_taxonomy.sql) builds
`test_callum.game_subprovider_taxonomy` from exact legacy-provider evidence in
the unified mapping. It marks any Titan product with conflicting supplier
evidence as `review`; dashboard queries must join only `approved` taxonomy
rows. The script also includes the safe `daily_player_games` join pattern.

This deliberately does not write taxonomy columns into `game_rounds` or
`daily_player_games`. Join it in a reporting view first; materialise an
enriched fact table only if dashboard performance requires it.

## Archive

`archive/` contains superseded intermediate exports and malformed notebook
snapshots that are not used by the current scripts. It is retained locally for
traceability, not as an active data source.

## Repository policy

This repository is code-first. Do **not** commit production extracts, BigQuery
exports, mapping-decision CSVs, generated imports, or credentials. The
`.gitignore` deliberately excludes those files. Use an approved BigQuery table
or controlled shared location for working data and audit outputs.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## GitHub publishing checklist

- Keep production CSVs and BigQuery exports out of Git.
- Review `git status --ignored` before the first commit.
- Commit code, SQL, documentation, and small synthetic fixtures only.
- Add `iterative_discovery.ipynb` only once saved as a standard notebook with
  cleared outputs.
