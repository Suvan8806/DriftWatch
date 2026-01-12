"""
DriftWatch Statistical Engine
Distribution-based drift detection using Z-score analysis
"""
import numpy as np
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from config import (
    MIN_SAMPLES_FOR_BASELINE,
    BASELINE_WINDOW_SIZE,
    DRIFT_ZSCORE_THRESHOLD,
    DRIFT_CONSECUTIVE_THRESHOLD,
    DRIFT_MODERATE_ZSCORE_THRESHOLD,
    DRIFT_MODERATE_COUNT,
    DRIFT_MODERATE_WINDOW
)


class StatisticalEngine:
    """Core statistical analysis and drift detection"""
    
    @staticmethod
    def calculate_baseline(samples: List[float]) -> Dict[str, float]:
        """
        Calculate baseline statistics from sample data
        
        Args:
            samples: List of numerical samples (latency or payload)
        
        Returns:
            Dictionary with mean, stddev, and percentiles
        """
        if len(samples) < MIN_SAMPLES_FOR_BASELINE:
            raise ValueError(f"Insufficient samples: {len(samples)} < {MIN_SAMPLES_FOR_BASELINE}")
        
        arr = np.array(samples)
        
        return {
            'mean': float(np.mean(arr)),
            'stddev': float(np.std(arr, ddof=1)),  # Sample standard deviation
            'p50': float(np.percentile(arr, 50)),
            'p95': float(np.percentile(arr, 95)),
            'p99': float(np.percentile(arr, 99)),
            'sample_count': len(samples)
        }
    
    @staticmethod
    def calculate_zscore(value: float, mean: float, stddev: float) -> float:
        """
        Calculate z-score for a value given baseline statistics
        
        Z-score = (value - mean) / stddev
        
        Returns:
            Z-score (number of standard deviations from mean)
        """
        if stddev == 0:
            return 0.0  # No variance, all values are identical
        
        return (value - mean) / stddev
    
    @staticmethod
    def is_anomaly(zscore: float, threshold: float = DRIFT_ZSCORE_THRESHOLD) -> bool:
        """
        Determine if a z-score represents an anomaly
        
        Args:
            zscore: Calculated z-score
            threshold: Threshold for anomaly detection (default: 3.0)
        
        Returns:
            True if |zscore| > threshold
        """
        return abs(zscore) > threshold
    
    @staticmethod
    def detect_drift(
        recent_zscores: List[float],
        consecutive_threshold: int = DRIFT_CONSECUTIVE_THRESHOLD,
        moderate_threshold: float = DRIFT_MODERATE_ZSCORE_THRESHOLD
    ) -> Tuple[bool, Dict[str, any]]:
        """
        Detect drift using consecutive anomaly analysis
        
        Detection rules:
        1. SEVERE: N consecutive samples with |z| > 3.0
        2. MODERATE: M samples in last K with |z| > 2.5
        
        Args:
            recent_zscores: List of recent z-scores (ordered newest to oldest)
            consecutive_threshold: Number of consecutive anomalies to trigger drift
            moderate_threshold: Threshold for moderate anomalies
        
        Returns:
            Tuple of (drift_detected: bool, metadata: dict)
        """
        if len(recent_zscores) < consecutive_threshold:
            return False, {'reason': 'insufficient_samples', 'sample_count': len(recent_zscores)}
        
        # Rule 1: Consecutive severe anomalies
        consecutive_count = 0
        for z in recent_zscores[:consecutive_threshold]:
            if abs(z) > DRIFT_ZSCORE_THRESHOLD:
                consecutive_count += 1
            else:
                break
        
        if consecutive_count >= consecutive_threshold:
            return True, {
                'reason': 'consecutive_severe_anomalies',
                'consecutive_count': consecutive_count,
                'threshold': DRIFT_ZSCORE_THRESHOLD,
                'max_zscore': max(abs(z) for z in recent_zscores[:consecutive_threshold])
            }
        
        # Rule 2: Moderate anomalies in window
        if len(recent_zscores) >= DRIFT_MODERATE_WINDOW:
            window = recent_zscores[:DRIFT_MODERATE_WINDOW]
            moderate_count = sum(1 for z in window if abs(z) > moderate_threshold)
            
            if moderate_count >= DRIFT_MODERATE_COUNT:
                return True, {
                    'reason': 'moderate_anomalies_in_window',
                    'moderate_count': moderate_count,
                    'window_size': DRIFT_MODERATE_WINDOW,
                    'threshold': moderate_threshold
                }
        
        return False, {
            'reason': 'no_drift',
            'consecutive_count': consecutive_count,
            'recent_anomalies': sum(1 for z in recent_zscores[:10] if abs(z) > DRIFT_ZSCORE_THRESHOLD)
        }
    
    @staticmethod
    def is_recovered(
        recent_zscores: List[float],
        recovery_threshold: int = 50
    ) -> bool:
        """
        Determine if service has recovered from drift
        
        Recovery requires N consecutive normal samples (|z| <= 2.0)
        
        Args:
            recent_zscores: List of recent z-scores (ordered newest to oldest)
            recovery_threshold: Number of consecutive normal samples required
        
        Returns:
            True if recovered
        """
        if len(recent_zscores) < recovery_threshold:
            return False
        
        # Check last N samples are all normal
        for z in recent_zscores[:recovery_threshold]:
            if abs(z) > 2.0:  # Normal threshold (less strict than detection)
                return False
        
        return True
    
    @staticmethod
    def format_baseline_summary(baseline: Dict[str, float]) -> str:
        """Create human-readable baseline summary"""
        return (
            f"μ={baseline['mean']:.2f}, σ={baseline['stddev']:.2f}, "
            f"p50={baseline['p50']:.2f}, p95={baseline['p95']:.2f}, "
            f"n={baseline['sample_count']}"
        )


class BaselineManager:
    """
    Manages baseline calculation and updates for services
    """
    
    def __init__(self, db):
        self.db = db
        self.engine = StatisticalEngine()
    
    async def should_recalculate(self, service_id: str) -> bool:
        """
        Determine if baseline should be recalculated
        
        Recalculate when:
        - No baseline exists
        - New samples collected since last calculation exceeds threshold
        """
        baseline = await self.db.get_baseline(service_id)
        if not baseline:
            return True
        
        current_count = await self.db.get_telemetry_count(service_id)
        return current_count >= baseline['sample_count'] + 50  # BASELINE_RECALC_INTERVAL
    
    async def calculate_and_store(self, service_id: str) -> Optional[Dict[str, float]]:
        """
        Calculate baseline from recent telemetry and store in database
        
        Returns:
            Baseline statistics or None if insufficient data
        """
        # Get recent telemetry
        telemetry = await self.db.get_recent_telemetry(
            service_id, 
            limit=BASELINE_WINDOW_SIZE
        )
        
        if len(telemetry) < MIN_SAMPLES_FOR_BASELINE:
            return None
        
        # Extract metrics
        latencies = [record['latency_ms'] for record in telemetry]
        payloads = [record['payload_kb'] for record in telemetry]
        
        # Calculate baselines
        latency_baseline = self.engine.calculate_baseline(latencies)
        payload_baseline = self.engine.calculate_baseline(payloads)
        
        # Store in database
        await self.db.upsert_baseline(
            service_id=service_id,
            sample_count=len(telemetry),
            mean_latency=latency_baseline['mean'],
            stddev_latency=latency_baseline['stddev'],
            mean_payload=payload_baseline['mean'],
            stddev_payload=payload_baseline['stddev'],
            p50_latency=latency_baseline['p50'],
            p95_latency=latency_baseline['p95'],
            p99_latency=latency_baseline['p99']
        )
        
        print(f"✓ Baseline updated for {service_id}: "
              f"{self.engine.format_baseline_summary(latency_baseline)}")
        
        return {
            'latency': latency_baseline,
            'payload': payload_baseline
        }


class DriftDetector:
    """
    Detects drift by comparing recent samples against baseline
    """
    
    def __init__(self, db):
        self.db = db
        self.engine = StatisticalEngine()
    
    async def evaluate(
        self, 
        service_id: str, 
        latency_ms: float, 
        payload_kb: float,
        timestamp: datetime
    ) -> Tuple[bool, Dict[str, any]]:
        """
        Evaluate if new telemetry indicates drift
        
        Args:
            service_id: Service identifier
            latency_ms: Current latency
            payload_kb: Current payload size
            timestamp: Telemetry timestamp
        
        Returns:
            Tuple of (drift_detected: bool, metadata: dict)
        """
        # Get baseline
        baseline = await self.db.get_baseline(service_id)
        if not baseline:
            return False, {'reason': 'no_baseline'}
        
        # Calculate z-scores
        latency_zscore = self.engine.calculate_zscore(
            latency_ms,
            baseline['mean_latency'],
            baseline['stddev_latency']
        )
        
        payload_zscore = self.engine.calculate_zscore(
            payload_kb,
            baseline['mean_payload'],
            baseline['stddev_payload']
        )
        
        # Store z-scores
        await self.db.insert_zscore(
            service_id=service_id,
            timestamp=timestamp,
            latency_zscore=latency_zscore,
            payload_zscore=payload_zscore
        )
        
        # Get recent z-scores for drift detection
        recent_zscores = await self.db.get_recent_zscores(service_id, limit=25)
        latency_zscores = [record['latency_zscore'] for record in recent_zscores]
        
        # Detect drift (focus on latency for MVP)
        drift_detected, metadata = self.engine.detect_drift(latency_zscores)
        
        metadata.update({
            'current_latency_zscore': latency_zscore,
            'current_payload_zscore': payload_zscore
        })
        
        return drift_detected, metadata
    
    async def check_recovery(self, service_id: str) -> bool:
        """
        Check if service has recovered from drift state
        
        Returns:
            True if recovered (50 consecutive normal samples)
        """
        recent_zscores = await self.db.get_recent_zscores(service_id, limit=60)
        latency_zscores = [record['latency_zscore'] for record in recent_zscores]
        
        return self.engine.is_recovered(latency_zscores)