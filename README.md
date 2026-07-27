# Bragg–Finnplay game mapping

Tools and review workflow for mapping legacy Bragg/Finnplay game identifiers to
Titan product identifiers, with a conservative fuzzy-matching pass and a
human-review notebook.

## Auditable rule-based dry run

The assumptions used for conservative follow-up matching are documented in
`MAPPING_RULES_AUDIT.md` and encoded in `mapping_rules.json`.

Generate pending candidates without changing any approved mapping:

```bash
venv/bin/python build_rule_based_auto_matches.py
```

This writes:

- `rule_based_auto_match_candidates.csv` — unique, guarded suggestions awaiting audit.
- `rule_based_deferred_review.csv` — route ambiguities, ties and chronology blockers.
- `rule_based_no_exact_match.csv` — remaining codes with no exact title candidate, for fuzzy review.

The script deliberately does not update `unified_game_mapping_for_bigquery.csv`,
`iterative_mapping_decisions.csv`, or `fuzzy_game_mapping_auto_accepted.csv`.

After an explicit review approval, run `promote_rule_based_auto_matches.py`, then
run the normal seed and unified-mapping builders.

## Repository policy

This repository is code-first. Do **not** commit production extracts, BigQuery
exports, mapping-decision CSVs, generated imports, or credentials. The
`.gitignore` intentionally excludes these files. Use an approved BigQuery table
or controlled shared location for the working data and audit outputs.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Place the required local input exports alongside the scripts only while working
locally. They are not part of the Git repository.

## Workflow

1. Run `fuzzy_match.py` to generate conservative candidates and auto-accepted
   matches.
2. Use `iterative_discovery.ipynb` for same-provider and cross-provider review.
   Decisions are saved locally in `iterative_mapping_decisions.csv`.
3. Run `build_final_mapping_seed.py` and `audit_approved_mapping.py`.
4. Combine existing approved mappings with new decisions using
   `build_unified_game_mapping.py`, then validate with
   `audit_unified_game_mapping.py`.
5. Upload the generated unified mapping CSV to BigQuery and apply it using the
   SQL guidance in `sql/game_rounds_unified_mapping_changes.sql`.

## GitHub publishing checklist

- Create a new **private** repository under the correct organisation.
- Keep the production CSVs and BigQuery exports out of the initial commit.
- Review `git status --ignored` before the first commit.
- Add only code, SQL, documentation, and small synthetic fixtures under
  `data/sample/`. Add the notebook only after it has been saved/exported as a
  standard `.ipynb` file with cleared outputs.

The prior local `.git` history was corrupt and pointed at an unrelated remote;
start a fresh repository rather than pushing to that remote.
