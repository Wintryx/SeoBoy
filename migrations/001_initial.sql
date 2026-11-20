PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL
) STRICT;

CREATE TABLE sites (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    site_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('own', 'competitor')),
    label TEXT NOT NULL,
    start_url TEXT NOT NULL,
    PRIMARY KEY (project_id, site_id)
) STRICT;

CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('crawl', 'inspect')),
    status TEXT NOT NULL CHECK (status IN ('running', 'paused', 'completed', 'partial', 'failed')),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    stop_reason TEXT,
    config_json TEXT NOT NULL CHECK (json_valid(config_json)),
    config_hash TEXT NOT NULL,
    inputs_json TEXT NOT NULL CHECK (json_valid(inputs_json)),
    tool_version TEXT NOT NULL,
    crawler_version TEXT NOT NULL,
    ruleset_version TEXT NOT NULL,
    normalization_version TEXT NOT NULL,
    max_urls INTEGER NOT NULL CHECK (max_urls > 0),
    max_requests INTEGER NOT NULL CHECK (max_requests > 0),
    FOREIGN KEY (project_id, site_id) REFERENCES sites(project_id, site_id),
    UNIQUE (run_id, project_id),
    CHECK ((status IN ('completed', 'partial', 'failed')) = (ended_at IS NOT NULL))
) STRICT;

CREATE TABLE urls (
    url_id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    normalized_url TEXT NOT NULL,
    UNIQUE (project_id, normalized_url),
    UNIQUE (url_id, project_id)
) STRICT;

CREATE TABLE run_urls (
    run_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    url_id INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('discovered', 'excluded', 'blocked', 'queued', 'finished', 'deferred')),
    reason_code TEXT,
    page_type TEXT,
    business_value TEXT NOT NULL DEFAULT 'normal' CHECK (business_value IN ('high', 'normal', 'low')),
    expected_indexable INTEGER CHECK (expected_indexable IN (0, 1)),
    click_depth INTEGER CHECK (click_depth >= 0),
    admitted_at TEXT,
    PRIMARY KEY (run_id, url_id),
    FOREIGN KEY (run_id, project_id) REFERENCES runs(run_id, project_id),
    FOREIGN KEY (url_id, project_id) REFERENCES urls(url_id, project_id)
) STRICT;

CREATE TABLE source_imports (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    import_id INTEGER NOT NULL,
    module TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'partial', 'unavailable', 'disabled')),
    captured_at TEXT NOT NULL,
    input_hash TEXT,
    metadata_json TEXT NOT NULL CHECK (json_valid(metadata_json)),
    PRIMARY KEY (run_id, import_id)
) STRICT;

CREATE TABLE url_discoveries (
    run_id TEXT NOT NULL,
    url_id INTEGER NOT NULL,
    discovery_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('seed', 'link', 'sitemap', 'gsc', 'redirect', 'canonical', 'auxiliary')),
    original_url TEXT NOT NULL,
    from_url_id INTEGER,
    import_id INTEGER,
    PRIMARY KEY (run_id, url_id, discovery_id),
    FOREIGN KEY (run_id, url_id) REFERENCES run_urls(run_id, url_id),
    FOREIGN KEY (run_id, from_url_id) REFERENCES run_urls(run_id, url_id),
    FOREIGN KEY (run_id, import_id) REFERENCES source_imports(run_id, import_id)
) STRICT;

CREATE TABLE crawl_jobs (
    run_id TEXT NOT NULL,
    job_id INTEGER NOT NULL,
    url_id INTEGER NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('page', 'robots', 'sitemap')),
    state TEXT NOT NULL CHECK (state IN ('pending', 'in_flight', 'done', 'skipped')),
    priority INTEGER NOT NULL DEFAULT 0,
    not_before_at TEXT NOT NULL,
    reason_code TEXT,
    PRIMARY KEY (run_id, job_id),
    UNIQUE (run_id, purpose, url_id),
    FOREIGN KEY (run_id, url_id) REFERENCES run_urls(run_id, url_id)
) STRICT;

CREATE TABLE http_attempts (
    run_id TEXT NOT NULL,
    attempt_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
    state TEXT NOT NULL CHECK (state IN ('reserved', 'response', 'transport_error', 'interrupted')),
    reserved_at TEXT NOT NULL,
    finished_at TEXT,
    status_code INTEGER CHECK (status_code BETWEEN 100 AND 599),
    content_type TEXT,
    location_url_id INTEGER,
    error_code TEXT,
    headers_json TEXT CHECK (json_valid(headers_json)),
    PRIMARY KEY (run_id, attempt_id),
    UNIQUE (run_id, job_id, attempt_no),
    FOREIGN KEY (run_id, job_id) REFERENCES crawl_jobs(run_id, job_id),
    FOREIGN KEY (run_id, location_url_id) REFERENCES run_urls(run_id, url_id),
    CHECK ((state = 'response') = (status_code IS NOT NULL)),
    CHECK ((state = 'reserved') = (finished_at IS NULL)),
    CHECK (location_url_id IS NULL OR (status_code IS NOT NULL AND status_code BETWEEN 300 AND 399))
) STRICT;

CREATE TABLE crawl_origins (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    origin TEXT NOT NULL,
    not_before_at TEXT NOT NULL,
    robots_state TEXT NOT NULL CHECK (robots_state IN ('unknown', 'available', 'unavailable', 'unreachable')),
    robots_attempt_id INTEGER,
    robots_rules_json TEXT CHECK (json_valid(robots_rules_json)),
    PRIMARY KEY (run_id, origin),
    FOREIGN KEY (run_id, robots_attempt_id) REFERENCES http_attempts(run_id, attempt_id)
) STRICT;

CREATE TABLE page_observations (
    run_id TEXT NOT NULL,
    observation_id INTEGER NOT NULL,
    url_id INTEGER NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('http', 'browser')),
    attempt_id INTEGER,
    observed_at TEXT NOT NULL,
    title TEXT,
    meta_description TEXT,
    links_complete INTEGER NOT NULL DEFAULT 0 CHECK (links_complete IN (0, 1)),
    signals_json TEXT NOT NULL CHECK (json_valid(signals_json)),
    PRIMARY KEY (run_id, observation_id),
    FOREIGN KEY (run_id, url_id) REFERENCES run_urls(run_id, url_id),
    FOREIGN KEY (run_id, attempt_id) REFERENCES http_attempts(run_id, attempt_id),
    CHECK ((method = 'http') = (attempt_id IS NOT NULL))
) STRICT;

CREATE TABLE links (
    run_id TEXT NOT NULL,
    observation_id INTEGER NOT NULL,
    target_url_id INTEGER NOT NULL,
    PRIMARY KEY (run_id, observation_id, target_url_id),
    FOREIGN KEY (run_id, observation_id) REFERENCES page_observations(run_id, observation_id),
    FOREIGN KEY (run_id, target_url_id) REFERENCES run_urls(run_id, url_id)
) STRICT;

CREATE TABLE gsc_datasets (
    run_id TEXT NOT NULL,
    dataset_id INTEGER NOT NULL,
    import_id INTEGER NOT NULL,
    property TEXT NOT NULL,
    search_type TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT '',
    device TEXT NOT NULL DEFAULT '',
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    grain TEXT NOT NULL CHECK (grain IN ('page', 'page_query')),
    PRIMARY KEY (run_id, dataset_id),
    UNIQUE (run_id, property, search_type, country, device, period_start, period_end, grain),
    FOREIGN KEY (run_id, import_id) REFERENCES source_imports(run_id, import_id),
    CHECK (period_start <= period_end)
) STRICT;

CREATE TABLE gsc_metrics (
    run_id TEXT NOT NULL,
    dataset_id INTEGER NOT NULL,
    source_page TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '',
    url_id INTEGER,
    mapping_status TEXT NOT NULL CHECK (mapping_status IN ('matched', 'unmatched', 'ambiguous')),
    clicks INTEGER NOT NULL CHECK (clicks >= 0),
    impressions INTEGER NOT NULL CHECK (impressions >= 0),
    position REAL CHECK (position >= 1),
    PRIMARY KEY (run_id, dataset_id, source_page, query),
    FOREIGN KEY (run_id, dataset_id) REFERENCES gsc_datasets(run_id, dataset_id),
    FOREIGN KEY (run_id, url_id) REFERENCES run_urls(run_id, url_id),
    CHECK ((mapping_status = 'matched') = (url_id IS NOT NULL))
) STRICT;

CREATE TABLE rule_results (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    rule_id TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    subject_kind TEXT NOT NULL CHECK (subject_kind IN ('url', 'link', 'query', 'site')),
    rule_version TEXT NOT NULL,
    subcheck TEXT NOT NULL DEFAULT '',
    scope_key TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('pass', 'finding', 'not_checked', 'not_applicable')),
    severity TEXT CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    confidence TEXT CHECK (confidence IN ('confirmed', 'plausible', 'hint')),
    reason_code TEXT,
    exception_json TEXT CHECK (json_valid(exception_json)),
    PRIMARY KEY (run_id, rule_id, subject_key),
    CHECK ((outcome = 'finding') = (severity IS NOT NULL)),
    CHECK ((outcome = 'finding') = (confidence IS NOT NULL)),
    CHECK (outcome IN ('pass', 'finding') OR reason_code IS NOT NULL),
    CHECK (exception_json IS NULL OR outcome = 'finding')
) STRICT;

CREATE TABLE result_urls (
    run_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    url_id INTEGER NOT NULL,
    relation TEXT NOT NULL CHECK (relation IN ('affected', 'source', 'target')),
    PRIMARY KEY (run_id, rule_id, subject_key, url_id, relation),
    FOREIGN KEY (run_id, rule_id, subject_key) REFERENCES rule_results(run_id, rule_id, subject_key),
    FOREIGN KEY (run_id, url_id) REFERENCES run_urls(run_id, url_id)
) STRICT;

CREATE TABLE rule_evidence (
    run_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    source_kind TEXT NOT NULL CHECK (source_kind IN ('http', 'page_observation', 'import', 'crawl', 'config')),
    attempt_id INTEGER,
    observation_id INTEGER,
    import_id INTEGER,
    observed_at TEXT NOT NULL,
    facts_json TEXT NOT NULL CHECK (json_valid(facts_json)),
    PRIMARY KEY (run_id, rule_id, subject_key, ordinal),
    FOREIGN KEY (run_id, rule_id, subject_key) REFERENCES rule_results(run_id, rule_id, subject_key),
    FOREIGN KEY (run_id, attempt_id) REFERENCES http_attempts(run_id, attempt_id),
    FOREIGN KEY (run_id, observation_id) REFERENCES page_observations(run_id, observation_id),
    FOREIGN KEY (run_id, import_id) REFERENCES source_imports(run_id, import_id),
    CHECK ((source_kind = 'http') = (attempt_id IS NOT NULL)),
    CHECK ((source_kind = 'page_observation') = (observation_id IS NOT NULL)),
    CHECK ((source_kind = 'import') = (import_id IS NOT NULL))
) STRICT;

CREATE TABLE actions (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    action_key TEXT NOT NULL,
    priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 4),
    effort TEXT NOT NULL CHECK (effort IN ('small', 'medium', 'large', 'unknown')),
    title TEXT NOT NULL,
    proposed_fix TEXT NOT NULL,
    expected_effect TEXT NOT NULL,
    verification TEXT NOT NULL,
    PRIMARY KEY (run_id, action_key)
) STRICT;

CREATE TABLE action_findings (
    run_id TEXT NOT NULL,
    action_key TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    PRIMARY KEY (run_id, action_key, rule_id, subject_key),
    FOREIGN KEY (run_id, action_key) REFERENCES actions(run_id, action_key),
    FOREIGN KEY (run_id, rule_id, subject_key) REFERENCES rule_results(run_id, rule_id, subject_key)
) STRICT;

CREATE INDEX runs_site_history ON runs(project_id, site_id, started_at);
CREATE INDEX run_urls_admitted ON run_urls(run_id, url_id) WHERE admitted_at IS NOT NULL;
CREATE INDEX crawl_jobs_schedule ON crawl_jobs(run_id, state, not_before_at, priority);
CREATE UNIQUE INDEX http_one_reserved_per_job ON http_attempts(run_id, job_id) WHERE state = 'reserved';
CREATE UNIQUE INDEX http_one_extraction_per_response ON page_observations(run_id, attempt_id) WHERE method = 'http';
CREATE INDEX page_observations_url ON page_observations(run_id, url_id, method, observed_at);
CREATE INDEX links_inbound ON links(run_id, target_url_id, observation_id);
CREATE INDEX gsc_metrics_url ON gsc_metrics(run_id, url_id, dataset_id);
CREATE INDEX gsc_metrics_query ON gsc_metrics(run_id, dataset_id, query) WHERE query <> '';
CREATE INDEX rule_results_coverage ON rule_results(run_id, rule_id, subcheck, scope_key, outcome);
CREATE INDEX result_urls_lookup ON result_urls(run_id, url_id, rule_id);
CREATE INDEX actions_priority ON actions(run_id, priority, action_key);

PRAGMA user_version = 1;
COMMIT;
