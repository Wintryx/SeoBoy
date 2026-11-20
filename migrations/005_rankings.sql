PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE ranking_keywords (
    project_id TEXT NOT NULL,
    keyword_id TEXT NOT NULL,
    query TEXT NOT NULL,
    intent TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    market TEXT NOT NULL,
    language TEXT NOT NULL,
    location_key TEXT NOT NULL DEFAULT '',
    engine TEXT NOT NULL,
    device TEXT NOT NULL,
    result_type TEXT NOT NULL,
    expected_target TEXT NOT NULL DEFAULT '',
    target_active INTEGER NOT NULL DEFAULT 1,
    business_value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (project_id, keyword_id)
) STRICT;

CREATE TABLE ranking_snapshots (
    project_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    keyword_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    engine TEXT NOT NULL,
    market TEXT NOT NULL,
    language TEXT NOT NULL,
    location_key TEXT NOT NULL DEFAULT '',
    device TEXT NOT NULL,
    result_type TEXT NOT NULL,
    depth INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'no_match', 'failed', 'blocked')),
    imported_at TEXT NOT NULL,
    PRIMARY KEY (project_id, snapshot_id),
    FOREIGN KEY (project_id, keyword_id)
        REFERENCES ranking_keywords(project_id, keyword_id)
) STRICT;

CREATE TABLE ranking_results (
    project_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    url TEXT NOT NULL,
    profile_id TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (project_id, snapshot_id, position),
    FOREIGN KEY (project_id, snapshot_id)
        REFERENCES ranking_snapshots(project_id, snapshot_id)
) STRICT;

CREATE INDEX ranking_snapshots_profile
    ON ranking_snapshots(project_id, keyword_id, observed_at);
CREATE INDEX ranking_results_snapshot
    ON ranking_results(project_id, snapshot_id, position);

PRAGMA user_version = 5;
COMMIT;
