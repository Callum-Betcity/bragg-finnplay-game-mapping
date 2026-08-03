-- Game subprovider taxonomy for Casino reporting.
--
-- Creates a small, auditable dimension keyed by Titan product ID. It uses
-- exact legacy provider-name evidence from unified_game_mapping, not fuzzy
-- title matching. Products with conflicting source evidence are deliberately
-- marked review and are excluded by the dashboard join template below.
--
-- Before running:
-- 1. Load the reviewed unified_game_mapping CSV to
--    betcity-319812.test_callum.unified_game_mapping.
-- 2. Replace v_cutover_ts with the Titan migration cutover timestamp.
-- 3. Review rows with decision_status = 'review' before relying on them.

DECLARE v_cutover_ts TIMESTAMP DEFAULT TIMESTAMP('2026-05-12 09:18:50.569780 UTC');

CREATE OR REPLACE TABLE `betcity-319812.test_callum.game_subprovider_taxonomy` AS
WITH provider_rules AS (
  -- Exact normalised legacy provider labels. These implement Jan's requested
  -- platform/provider-group taxonomy; do not infer a studio from title text.
  SELECT 'evolution' AS provider_norm, 'OSS' AS aggregation_platform, 'Evolution' AS provider_group, 'Evolution' AS game_subprovider UNION ALL
  SELECT 'nolimitcity', 'OSS', 'Evolution', 'Nolimit City' UNION ALL
  SELECT 'netent', 'OSS', 'Evolution', 'NetEnt' UNION ALL
  SELECT 'bigtimegaming', 'OSS', 'Evolution', 'Big Time Gaming' UNION ALL
  SELECT 'redtiger', 'OSS', 'Evolution', 'Red Tiger' UNION ALL

  SELECT 'lightandwonder', 'OGS', 'Light & Wonder', 'Light & Wonder' UNION ALL
  SELECT 'lightwonder', 'OGS', 'Light & Wonder', 'Light & Wonder' UNION ALL
  SELECT 'hacksaw', 'OGS', 'Light & Wonder', 'Hacksaw' UNION ALL
  SELECT 'hacksawgaming', 'OGS', 'Light & Wonder', 'Hacksaw' UNION ALL
  SELECT 'elk', 'OGS', 'Light & Wonder', 'ELK Studios' UNION ALL
  SELECT 'elkstudios', 'OGS', 'Light & Wonder', 'ELK Studios' UNION ALL
  SELECT 'gamingcorps', 'OGS', 'Light & Wonder', 'Gaming Corps' UNION ALL
  SELECT 'inspired', 'OGS', 'Light & Wonder', 'Inspired' UNION ALL
  SELECT 'inspiredentertainment', 'OGS', 'Light & Wonder', 'Inspired' UNION ALL
  SELECT 'swintt', 'OGS', 'Light & Wonder', 'Swintt' UNION ALL
  SELECT 'swintt2', 'OGS', 'Light & Wonder', 'Swintt' UNION ALL
  SELECT 'thunderkick', 'OGS', 'Light & Wonder', 'Thunderkick' UNION ALL
  SELECT 'booming', 'OGS', 'Light & Wonder', 'Booming Games' UNION ALL
  SELECT 'boominggames', 'OGS', 'Light & Wonder', 'Booming Games' UNION ALL

  SELECT 'relax', 'Relax', 'Relax', 'Relax' UNION ALL
  SELECT 'relaxgaming', 'Relax', 'Relax', 'Relax' UNION ALL
  SELECT 'silverbullet', 'Relax', 'Relax', 'Silver Bullet' UNION ALL
  SELECT 'rubyplay', 'Relax', 'Relax', 'Ruby Play' UNION ALL
  SELECT 'synot', 'Relax', 'Relax', 'Synot' UNION ALL

  SELECT 'bragg', 'Bragg', 'Bragg', 'Bragg' UNION ALL
  SELECT 'cherryplay', 'Bragg', 'Bragg', 'Cherry Play' UNION ALL
  SELECT 'gamomat', 'Bragg', 'Bragg', 'Gamomat' UNION ALL
  SELECT 'gammomat', 'Bragg', 'Bragg', 'Gamomat' UNION ALL
  SELECT 'fazi', 'Bragg', 'Bragg', 'Fazi' UNION ALL
  SELECT 'fazigameprovider', 'Bragg', 'Bragg', 'Fazi'
),
source_evidence AS (
  SELECT
    CAST(m.titan_product_id AS INT64) AS titan_product_id,
    m.old_game_provider_name,
    REGEXP_REPLACE(LOWER(TRIM(m.old_game_provider_name)), r'[^a-z0-9]+', '') AS provider_norm,
    COUNT(DISTINCT m.old_aggregator_game_code) AS legacy_game_codes,
    SUM(m.old_bets) AS legacy_bets,
    SUM(m.old_rounds) AS legacy_rounds
  FROM `betcity-319812.test_callum.unified_game_mapping` AS m
  WHERE m.titan_product_id IS NOT NULL
    AND NULLIF(TRIM(m.old_game_provider_name), '') IS NOT NULL
  GROUP BY 1, 2, 3
),
classified_evidence AS (
  SELECT
    e.titan_product_id,
    r.aggregation_platform,
    r.provider_group,
    r.game_subprovider,
    e.old_game_provider_name,
    e.legacy_game_codes,
    e.legacy_bets,
    e.legacy_rounds
  FROM source_evidence AS e
  JOIN provider_rules AS r USING (provider_norm)
),
resolved AS (
  SELECT
    titan_product_id,
    aggregation_platform,
    provider_group,
    game_subprovider,
    ARRAY_AGG(DISTINCT old_game_provider_name IGNORE NULLS ORDER BY old_game_provider_name) AS evidence_legacy_provider_names,
    SUM(legacy_game_codes) AS evidence_legacy_game_codes,
    SUM(legacy_bets) AS evidence_legacy_bets,
    SUM(legacy_rounds) AS evidence_legacy_rounds
  FROM classified_evidence
  GROUP BY 1, 2, 3, 4
),
product_conflicts AS (
  SELECT titan_product_id, COUNT(*) AS distinct_classifications
  FROM resolved
  GROUP BY 1
)
SELECT
  r.titan_product_id,
  r.aggregation_platform,
  r.provider_group,
  r.game_subprovider,
  IF(c.distinct_classifications = 1, 'approved', 'review') AS decision_status,
  'exact_legacy_provider_name_rule' AS mapping_method,
  'v1' AS rule_version,
  r.evidence_legacy_provider_names,
  r.evidence_legacy_game_codes,
  r.evidence_legacy_bets,
  r.evidence_legacy_rounds,
  CURRENT_TIMESTAMP() AS generated_at
FROM resolved AS r
JOIN product_conflicts AS c USING (titan_product_id);

-- Quality check: resolve review rows before treating them as dashboard data.
SELECT
  decision_status,
  COUNT(*) AS titan_products,
  SUM(evidence_legacy_bets) AS legacy_bets
FROM `betcity-319812.test_callum.game_subprovider_taxonomy`
GROUP BY 1
ORDER BY 1;

-- Dashboard join pattern. Keep this as a view/query rather than rewriting
-- daily_player_games. Legacy activity is resolved through unified mapping;
-- post-cutover activity uses its Titan product ID. The cutover guard prevents
-- numeric legacy codes from being mistaken for Titan product IDs.
--
-- SELECT
--   dpg.*,
--   tax.aggregation_platform,
--   tax.provider_group,
--   tax.game_subprovider
-- FROM `betcity-319812.01_operator_data_marts.daily_player_games` AS dpg
-- LEFT JOIN `betcity-319812.test_callum.unified_game_mapping` AS ugm
--   ON dpg.end_time < v_cutover_ts
--  AND CAST(dpg.aggregator_game_code AS STRING) = ugm.old_aggregator_game_code
-- LEFT JOIN `betcity-319812.test_callum.game_subprovider_taxonomy` AS tax
--   ON tax.titan_product_id = COALESCE(
--        ugm.titan_product_id,
--        IF(dpg.end_time >= v_cutover_ts, SAFE_CAST(dpg.aggregator_game_code AS INT64), NULL)
--      )
--  AND tax.decision_status = 'approved';
