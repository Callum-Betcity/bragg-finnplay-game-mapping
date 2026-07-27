# Game-mapping assumptions audit

This file records the assumptions used after `unified_game_mapping_for_bigquery.csv` was created. It is the human-review companion to `mapping_rules.json`.

Nothing in the dry-run rule matcher writes to the unified mapping, the manual decision log, or the existing fuzzy auto-accept file. Promotion remains a separate, explicit audit step.

## Safe for conservative candidate generation

| Rule | Assumption | Current use |
|---|---|---|
| R001 | Exact normalized title-token identity is strong evidence | Candidate generation, with uniqueness guards |
| R002 | Audited provider aliases identify the same provider | Evidence and normalization |
| R003 | Scoped Titan product-name prefixes can reveal the underlying studio | Evidence only; prefixes are provider-specific |
| R004 | Slingo, Edict, ELK Studios, and Hacksaw Gaming have unresolved provider routes | Quarantine in provider-route review |
| R007 | Numeric/configuration tokens must be preserved | Exact identity guard |
| R008 | Pragmatic Azure ordinals `1..5` map to `a..e` within that family only | Existing family-scoped matcher |
| R012 | Titan release after first old activity requires review | Automatic-accept blocker |
| R015 | Prior manual/unified decisions take precedence | Never revisit or overwrite resolved codes |
| R023 | For an exact title/configuration match, prefer a candidate whose mapped provider equals the normalized old provider | Direct provider identity is stronger routing evidence than an otherwise identical catalogue copy; active provider-route quarantines still win |
| R025 | A legacy `94` suffix may be absent from a Titan title only with corroborating title and route evidence | Manual-only, provider/family-scoped exception; not a general configuration-dropping rule |

## Ranking or workflow assumptions, not proof

| Rule | Assumption | Audit concern |
|---|---|---|
| R005 | Titan provider can be a distribution route rather than the studio | Provider equality can mislead |
| R006 | Prefer non-Oryx/OGS after all substantive evidence ties | Must not decide an auto match |
| R009 | `BetCity` may indicate the Titan `Branded` variant | Plausible, but needs more confirmed examples |
| R013 | Route ambiguity is a defer/review outcome, not no-match | Prevents false negative decisions |

## Disabled hypotheses

| Rule | Hypothesis | Why disabled |
|---|---|---|
| R011 | `NBB` / `No Bonus Buy` maps to Titan suffix `f0` rather than `f1` | Existing reviewed rows are circular evidence, not an independent definition |
| R014 | Ruby Play should always prefer RelaxGaming over Oryx | Repeated ambiguity exists, but the preferred route is not established |
| R025 | A source `94` suffix can always be ignored | The `94` token normally remains identity-bearing under R007; the Flower Fortune Supreme decision is a single, documented exception |

## Provider-route assumptions to audit

- **Edict:** appears to be an aggregator/catalogue containing games from studios such as Merkur, Booming Games and Blueprint. A Titan provider named Edict is therefore not required.
- **Slingo:** Gaming Realms/Slingo titles appear on multiple Titan routes, especially GamesGlobal and RelaxGaming. There is no established universal route preference.
- **ELK Studios:** the same title can appear through Spearhead, iSoftBet, ST8, OGS or other routes.
- **Hacksaw Gaming:** the same title can appear through iSoftBet, RelaxGaming, OGS, GamesGlobal or other routes.
- **Ruby Play:** RelaxGaming and Oryx copies recur. It is now in active provider-route review; do not choose a route from title identity alone.
- **Bluberi Games:** GamesGlobal and Oryx copies recur. It is now in active provider-route review; do not choose a route from title identity alone.
- **Booming Games:** GamesGlobal, iSoftBet, RelaxGaming and other catalogue routes recur. It is now in active provider-route review; product-code provenance is not enough to choose a route.
- **Atomic Slot Lab:** Oryx and other catalogue routes recur. It is now in active provider-route review; the ASL marker identifies the studio but not the preferred route.
- **Gammomat:** GamesGlobal and Oryx copies recur. It is now in active provider-route review; the GAM marker identifies the studio but not the preferred route.
- **Gaming Corps:** RelaxGaming, Oryx, OGS and other catalogue routes recur. It is now in active provider-route review; the GC marker identifies the studio but not the preferred route.
- **Inspired Entertainment:** GamesGlobal, OGS, RelaxGaming and other catalogue routes recur. It is now in active provider-route review; the INS marker identifies the studio but not the preferred route.
- **1X2gaming:** RelaxGaming, OGS and other catalogue routes recur. It is now in active provider-route review; the `1x2` marker identifies the studio but not the preferred route.
- **Indigo Magic / O2X:** Oryx, GamesGlobal and other catalogue routes recur. It is now in active provider-route review; product-code provenance is not enough to select a route.
- **Oryx/OGS generally:** these often look like wrappers or catalogue routes. Preferencing another route can help review order, but it cannot prove identity.

## Naming assumptions

- Source provider markers can be removed only when they are explicitly scoped to the source provider.
- Titan product-name markers such as `SL_`, `INS_`, `BTG_`, `GC_`, `IM_`, `BB_`, `RP_`, and `BMNG_` are supporting studio evidence only for their registered provider.
- `SL_` in a Titan product name is treated as StakeLogic in that scoped context. It is not a global abbreviation rule.
- **StakeLogic routed through RelaxGaming:** `STK_RUNNER_RUNNER_ARCADE` maps to `SL_RunnerRunnerArcade` (`698521`). The exact title and scoped `SL_` prefix establish the studio identity; `RelaxGaming` is the mapped delivery/catalogue route. This corroborates the scoped prefix rule, but does not create a general provider-route preference.
- Exact suffixes matter: `94`, `96`, `92`, table letters, numbered tables, editions, jackpot variants, branded variants and other qualifiers should not be silently dropped.
- `NBB` means “No Bonus Buy”; the stronger claim that it equals `f0` remains unverified.
- **Open configuration question:** for Evolution/NetEnt titles such as *Monopoly Money Line 94 (No Bonus Buy)*, establish from a catalogue or product metadata whether `f0` or `f1` is the no-bonus-buy variant. Do not infer it from historical manual choices.
- `STT` and `SWI` normalize to **Swintt**. For an exact Swintt title, the candidate mapped to Swintt is preferred over an identical RelaxGaming or OGS copy.
- **Flower Fortune Supreme 94 (manual exception):** `RELAX_SBLT_FLOWER_FORTUNE_SUPREME_94` may map to `RG_F_FlowerFortunesSupreme` (`687028`). The core title is exact and the candidate is on the direct RelaxGaming route, while Titan omits the legacy `94` suffix. This is manual evidence only; do not generalise it to other `94` titles without equivalent corroboration.

## Evidence and provenance

The unified file currently mixes distinct sources that should not be treated as equally independent evidence:

- `preexisting_reviewed_mapping` rows originated in `bragg_finnplay_mapping_reviewed_2.csv`.
- Manual accept/reject decisions are logged in `iterative_mapping_decisions.csv`.
- Existing automatic candidates are in `fuzzy_game_mapping_auto_accepted.csv`.
- Approved provisional rows are explicitly opted in through the seed-building workflow.

A prior manual choice can establish workflow state, but it must not be used as circular evidence to invent a general rule. The clearest example is the provisional `NBB → f0` hypothesis.

## Audit checklist before promotion

1. Confirm each enabled rule and provider alias in `mapping_rules.json`.
2. Confirm the thirteen active provider-route review groups: Slingo, Edict, ELK Studios, Hacksaw Gaming, Ruby Play, Bluberi Games, Booming Games, Atomic Slot Lab, Gammomat, Gaming Corps, Inspired Entertainment, 1X2gaming, and Indigo Magic / O2X.
3. Establish route preferences, if any, from an authoritative catalogue or migration record—not merely from earlier manual choices.
4. Review `rule_based_auto_match_candidates.csv`, especially the `evidence` and `rule_ids` columns.
5. Review `rule_based_deferred_review.csv` for route ambiguity, tied candidates and chronology blockers.
6. Only then promote selected rows through a separate approval step.

## Current dry-run result

Run with:

```bash
venv/bin/python build_rule_based_auto_matches.py
```

The first audited run produced:

- **57** new candidates in `rule_based_auto_match_candidates.csv`, all marked `pending_audit`.
- **181** rows in `rule_based_deferred_review.csv`.
- **442** rows in `rule_based_no_exact_match.csv`; these need fuzzy/candidate review because no exact normalized title exists.
- At the time of the first run, 90 rows were in active provider-route review and 59 Ruby Play rows were held as a provisional route issue. Ruby Play is now an active provider-route review group; rerun the dry run to consolidate those counts.
- No duplicate Titan IDs among the 57 candidates.
- No unified, manual-decision, or existing fuzzy-auto file was modified.
