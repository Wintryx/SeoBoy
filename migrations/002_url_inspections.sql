PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE url_inspections (
    run_id TEXT NOT NULL,
    url_id INTEGER NOT NULL,
    property TEXT NOT NULL,
    inspection_url TEXT NOT NULL,
    language_code TEXT NOT NULL,
    inspected_at TEXT NOT NULL,
    verdict TEXT,
    coverage_state TEXT,
    indexing_state TEXT,
    robots_txt_state TEXT,
    page_fetch_state TEXT,
    google_canonical TEXT,
    user_canonical TEXT,
    last_crawl_time TEXT,
    error_code TEXT,
    raw_json TEXT NOT NULL CHECK (json_valid(raw_json)),
    PRIMARY KEY (run_id, url_id),
    FOREIGN KEY (run_id, url_id) REFERENCES run_urls(run_id, url_id)
) STRICT;

CREATE INDEX url_inspections_run ON url_inspections(run_id, inspected_at);

PRAGMA user_version = 2;
COMMIT;
