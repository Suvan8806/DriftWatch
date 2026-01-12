"""
DriftWatch Configuration
Zero-configuration defaults for production-grade drift detection
"""

# Database Configuration
DATABASE_PATH = "driftwatch.db"

# Baseline Generation Parameters
MIN_SAMPLES_FOR_BASELINE = 100  # Minimum samples before transitioning to STABLE
BASELINE_WINDOW_SIZE = 1000     # Maximum samples to consider for baseline
BASELINE_RECALC_INTERVAL = 50   # Recalculate baseline after N new samples

# Drift Detection Parameters
DRIFT_ZSCORE_THRESHOLD = 3.0           # Z-score threshold for single anomaly
DRIFT_CONSECUTIVE_THRESHOLD = 5        # Consecutive anomalies to trigger DRIFT_DETECTED
DRIFT_MODERATE_ZSCORE_THRESHOLD = 2.5  # Moderate anomaly threshold
DRIFT_MODERATE_COUNT = 10              # Moderate anomalies in window
DRIFT_MODERATE_WINDOW = 20             # Window size for moderate anomaly detection

# Recovery Parameters
RECOVERY_CONSECUTIVE_NORMAL = 50  # Consecutive normal samples to recover from drift

# Data Retention
TELEMETRY_RETENTION_DAYS = 7
DRIFT_EVENTS_RETENTION_DAYS = 30

# API Configuration
API_HOST = "0.0.0.0"
API_PORT = 8000

# Validation Parameters
MAX_SERVICE_ID_LENGTH = 64
TIMESTAMP_TOLERANCE_HOURS = 1  # Accept timestamps within ±1 hour of server time

# Health States
class HealthState:
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    STABLE = "STABLE"
    DRIFT_DETECTED = "DRIFT_DETECTED"