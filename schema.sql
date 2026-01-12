-- DriftWatch SQLite Schema
-- Production-grade schema for telemetry storage and drift detection

-- Telemetry Records
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT NOT NULL,
    timestamp INTEGER NOT NULL,  -- Unix epoch milliseconds
    latency_ms REAL NOT NULL,
    payload_kb REAL NOT NULL,
    created_at INTEGER NOT NULL,
    CONSTRAINT chk_latency CHECK (latency_ms >= 0),
    CONSTRAINT chk_payload CHECK (payload_kb >= 0)
);

CREATE INDEX IF NOT EXISTS idx_telemetry_service_time 
ON telemetry(service_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_telemetry_created 
ON telemetry(created_at);

-- Service Baselines
CREATE TABLE IF NOT EXISTS baselines (
    service_id TEXT PRIMARY KEY,
    sample_count INTEGER NOT NULL,
    mean_latency REAL NOT NULL,
    stddev_latency REAL NOT NULL,
    mean_payload REAL NOT NULL,
    stddev_payload REAL NOT NULL,
    p50_latency REAL,
    p95_latency REAL,
    p99_latency REAL,
    last_updated INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    CONSTRAINT chk_sample_count CHECK (sample_count > 0)
);

-- Health States
CREATE TABLE IF NOT EXISTS health_states (
    service_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    transition_timestamp INTEGER NOT NULL,
    metadata TEXT,  -- JSON metadata
    CONSTRAINT chk_state CHECK (state IN ('INSUFFICIENT_DATA', 'STABLE', 'DRIFT_DETECTED'))
);

-- Drift Events (Audit Log)
CREATE TABLE IF NOT EXISTS drift_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT NOT NULL,
    detected_at INTEGER NOT NULL,
    previous_state TEXT NOT NULL,
    new_state TEXT NOT NULL,
    trigger_samples TEXT,  -- JSON array of recent z-scores
    metadata TEXT  -- Additional context
);

CREATE INDEX IF NOT EXISTS idx_drift_events_service 
ON drift_events(service_id, detected_at DESC);

-- Z-Score History (for drift detection)
CREATE TABLE IF NOT EXISTS zscore_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    latency_zscore REAL NOT NULL,
    payload_zscore REAL NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_zscore_service_time 
ON zscore_history(service_id, created_at DESC);

-- Simulation Tracking (internal)
CREATE TABLE IF NOT EXISTS simulations (
    simulation_id TEXT PRIMARY KEY,
    service_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    end_time INTEGER,
    status TEXT NOT NULL,  -- RUNNING, COMPLETED, FAILED
    samples_sent INTEGER DEFAULT 0
);