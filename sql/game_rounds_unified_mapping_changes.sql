-- Apply these changes to the earlier CREATE OR REPLACE game_rounds script.
-- Staging table loaded from unified_game_mapping_for_bigquery.csv:
--   betcity-319812.test_callum.unified_game_mapping

-- 1. Replace the reviewed_dedup CTE with this CTE.
-- The unified staging file was validated to have exactly one nonblank Titan ID
-- per old aggregator game code, so it no longer needs the old confidence-based
-- choice across multiple candidate sources.
  reviewed_dedup AS (
    SELECT
      CAST(old_aggregator_game_code AS STRING) AS old_aggregator_game_code,
      ARRAY_AGG(
        STRUCT(
          CAST(titan_product_id AS STRING) AS titan_product_id,
          CAST(old_game_name AS STRING) AS old_game_name,
          CAST(old_game_provider_name AS STRING) AS old_game_provider_name
        )
        LIMIT 1
      )[OFFSET(0)] AS mapping
    FROM `betcity-319812.test_callum.unified_game_mapping`
    WHERE NULLIF(TRIM(CAST(titan_product_id AS STRING)), '') IS NOT NULL
    GROUP BY 1
  ),
  approved_mappings AS (
    SELECT
      old_aggregator_game_code,
      mapping.titan_product_id AS titan_product_id,
      mapping.old_game_name AS old_game_name,
      mapping.old_game_provider_name AS old_game_provider_name
    FROM reviewed_dedup
  ),

-- 2. In mapped_products, change these references:
--   FROM reviewed_dedup m             --> FROM approved_mappings m
--   m.final_titan_product_id          --> m.titan_product_id
-- This affects both the SELECT list and the titan_PRODUCT join.

-- The relevant mapped_products lines should therefore read:
--   m.titan_product_id,
--   ...
--   FROM approved_mappings m
--   JOIN `betcity-prod.betcitynl_titan_prod_eu.titan_PRODUCT` tp
--     ON m.titan_product_id = CAST(tp.PK_PRODUCT_ID AS STRING)

-- 3. In old_game_rounds, change the mapping output and join:
--   COALESCE(mp.final_titan_product_id, CAST(old.aggregator_game_code AS STRING))
--     --> COALESCE(mp.titan_product_id, CAST(old.aggregator_game_code AS STRING))
--
-- Replace the three-column join:
--   LEFT JOIN mapped_products mp
--     ON CAST(old.aggregator_game_code AS STRING) = mp.old_aggregator_game_code
--       AND CAST(old.game_name AS STRING) = mp.old_game_name
--       AND CAST(old.game_provider_name AS STRING) = mp.old_game_provider_name
--
-- with the stable mapping-key join:
--   LEFT JOIN mapped_products mp
--     ON CAST(old.aggregator_game_code AS STRING) = mp.old_aggregator_game_code

-- 4. Leave the cutover logic, Titan-round logic, and output schema unchanged.

-- Recommended: replace the original provider_aliases CTE with this more
-- complete provider-output override CTE.  Keys below match the normalised
-- titan_GAME_PROVIDER.NAME values observed in the Titan catalogue.
--
-- Amusnet uses AM in the current Titan mapping source.  EGT is the historical
-- Bragg code, so AM keeps the rebuilt table Titan-canonical.
  provider_aliases AS (
    SELECT 'pragmaticnative' AS titan_provider_norm, 'PP' AS legacy_provider_code, 'Pragmatic Play' AS legacy_provider_name UNION ALL
    SELECT 'blueprint',        'BP',    'Blueprint Gaming' UNION ALL
    SELECT 'amusnet',          'AM',    'Amusnet Interactive' UNION ALL
    SELECT 'oryxgaming',       'ORYX',  'Oryx' UNION ALL
    SELECT 'kambi',            'KMB',   'KMB' UNION ALL
    SELECT 'gamesglobal',      'MGS',   'Games Global' UNION ALL
    SELECT 'playngo',          'PNG',   'Play''n GO' UNION ALL
    SELECT 'stakelogic',       'STK',   'Stakelogic' UNION ALL
    SELECT 'greentube',        'GTB',   'Greentube' UNION ALL
    SELECT 'evolution',        'EVOL',  'Evolution' UNION ALL
    SELECT 'relaxgaming',      'RELAX', 'Relax Gaming' UNION ALL
    SELECT 'playson',          'PLS',   'Playson' UNION ALL
    SELECT 'pushgaming',       'PUSH',  'Push Gaming' UNION ALL
    SELECT 'synot',            'SYN',   'Synot' UNION ALL
    SELECT 'nolimitcity',      'NLC',   'Nolimit City' UNION ALL
    SELECT 'netent',           'NETE',  'NetEnt' UNION ALL
    SELECT 'redtiger',         'RTG',   'Red Tiger' UNION ALL
    SELECT 'ogs',              'OGS',   'OGS' UNION ALL
    SELECT 'booming',          'BOOMING', 'Booming Games' UNION ALL
    SELECT 'swintt',           'STT',   'Swintt'
  ),
