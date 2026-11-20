PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE monitor_observations (
    observation_id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL,
    watch_key TEXT NOT NULL,
    url TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    http_status INTEGER,
    final_url TEXT,
    elapsed_ms INTEGER,
    robots_directive TEXT,
    canonical_url TEXT,
    state TEXT NOT NULL CHECK (state IN ('ok', 'suspect', 'confirmed', 'recovered', 'not_checked')),
    reason_code TEXT,
    UNIQUE (project_id, watch_key, observed_at)
) STRICT;

CREATE INDEX monitor_observations_watch
    ON monitor_observations(project_id, watch_key, observed_at);

CREATE TABLE monitor_events (
    project_id TEXT NOT NULL,
    watch_key TEXT NOT NULL,
    url TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('ok', 'suspect', 'confirmed', 'recovered')),
    reason_code TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    confirmed_at TEXT,
    recovered_at TEXT,
    failures INTEGER NOT NULL DEFAULT 0,
    last_observation_id INTEGER,
    PRIMARY KEY (project_id, watch_key)
) STRICT;

PRAGMA user_version = 4;
COMMIT;
