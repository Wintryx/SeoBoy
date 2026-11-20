PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE backlink_observations (
    observation_id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    target_url TEXT NOT NULL,
    source_original TEXT NOT NULL,
    target_original TEXT NOT NULL,
    dataset_source TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    anchor_text TEXT NOT NULL DEFAULT '',
    rel TEXT NOT NULL DEFAULT '',
    first_seen_by_provider TEXT NOT NULL DEFAULT '',
    last_seen_by_provider TEXT NOT NULL DEFAULT '',
    entity_role TEXT NOT NULL DEFAULT 'unknown' CHECK (entity_role IN ('own', 'competitor', 'unknown')),
    review_state TEXT NOT NULL DEFAULT 'open' CHECK (review_state IN ('open', 'reviewed', 'ignored')),
    review_note TEXT NOT NULL DEFAULT '',
    event_key TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE (project_id, event_key)
) STRICT;

CREATE INDEX backlink_observations_source
    ON backlink_observations(project_id, source_url, observed_at);
CREATE INDEX backlink_observations_target
    ON backlink_observations(project_id, target_url, observed_at);
CREATE INDEX backlink_observations_snapshot
    ON backlink_observations(project_id, dataset_source, snapshot_id);

PRAGMA user_version = 6;
COMMIT;
