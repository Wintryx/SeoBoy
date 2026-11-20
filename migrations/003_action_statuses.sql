PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE action_statuses (
    project_id TEXT NOT NULL,
    action_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'in_progress', 'done', 'ignored')),
    note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (project_id, action_key)
) STRICT;

CREATE TABLE action_status_history (
    project_id TEXT NOT NULL,
    action_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'in_progress', 'done', 'ignored')),
    note TEXT NOT NULL DEFAULT '',
    changed_at TEXT NOT NULL,
    PRIMARY KEY (project_id, action_key, changed_at)
) STRICT;

CREATE INDEX action_status_history_key
    ON action_status_history(project_id, action_key, changed_at);

PRAGMA user_version = 3;
COMMIT;
