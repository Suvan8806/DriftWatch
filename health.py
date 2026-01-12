"""
DriftWatch Health State Management
Manages service health state transitions and lifecycle
"""
from typing import Optional, Dict, Any
from datetime import datetime
from config import HealthState, MIN_SAMPLES_FOR_BASELINE
from statistics import BaselineManager, DriftDetector


class HealthStateManager:
    """
    Manages health state transitions for services
    
    State Machine:
    INSUFFICIENT_DATA → STABLE → DRIFT_DETECTED
          ↑                ↓              ↓
          └────────────────┴──────────────┘
    """
    
    def __init__(self, db):
        self.db = db
        self.baseline_manager = BaselineManager(db)
        self.drift_detector = DriftDetector(db)
    
    async def get_current_state(self, service_id: str) -> str:
        """
        Get current health state for a service
        
        Returns:
            Current state or INSUFFICIENT_DATA if not tracked
        """
        health = await self.db.get_health_state(service_id)
        if health:
            return health['state']
        
        # Initialize new service
        await self.db.upsert_health_state(
            service_id=service_id,
            state=HealthState.INSUFFICIENT_DATA,
            metadata={'reason': 'newly_tracked'}
        )
        return HealthState.INSUFFICIENT_DATA
    
    async def transition_state(
        self, 
        service_id: str, 
        new_state: str, 
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Transition service to a new health state
        
        Args:
            service_id: Service identifier
            new_state: Target state
            metadata: Additional context for transition
        """
        current_state = await self.get_current_state(service_id)
        
        if current_state == new_state:
            return  # No transition needed
        
        # Update state
        await self.db.upsert_health_state(
            service_id=service_id,
            state=new_state,
            metadata=metadata
        )
        
        # Record transition in audit log
        await self.db.insert_drift_event(
            service_id=service_id,
            previous_state=current_state,
            new_state=new_state,
            metadata=metadata
        )
        
        print(f"⚡ State transition: {service_id} | {current_state} → {new_state}")
        if metadata:
            print(f"   Reason: {metadata.get('reason', 'unknown')}")
    
    async def process_telemetry(
        self, 
        service_id: str, 
        latency_ms: float, 
        payload_kb: float,
        timestamp: datetime
    ):
        """
        Process new telemetry and update health state accordingly
        
        This is the main orchestration method called after telemetry ingestion
        
        Args:
            service_id: Service identifier
            latency_ms: Latency measurement
            payload_kb: Payload size measurement
            timestamp: Telemetry timestamp
        """
        current_state = await self.get_current_state(service_id)
        
        # Check if baseline needs recalculation
        if await self.baseline_manager.should_recalculate(service_id):
            baseline = await self.baseline_manager.calculate_and_store(service_id)
            
            # Transition from INSUFFICIENT_DATA to STABLE if baseline established
            if baseline and current_state == HealthState.INSUFFICIENT_DATA:
                await self.transition_state(
                    service_id=service_id,
                    new_state=HealthState.STABLE,
                    metadata={
                        'reason': 'baseline_established',
                        'sample_count': baseline['latency']['sample_count']
                    }
                )
                return
        
        # If still insufficient data, nothing more to do
        if current_state == HealthState.INSUFFICIENT_DATA:
            return
        
        # Evaluate for drift
        drift_detected, drift_metadata = await self.drift_detector.evaluate(
            service_id=service_id,
            latency_ms=latency_ms,
            payload_kb=payload_kb,
            timestamp=timestamp
        )
        
        # Handle state transitions
        if current_state == HealthState.STABLE and drift_detected:
            # Transition to DRIFT_DETECTED
            await self.transition_state(
                service_id=service_id,
                new_state=HealthState.DRIFT_DETECTED,
                metadata=drift_metadata
            )
        
        elif current_state == HealthState.DRIFT_DETECTED:
            # Check for recovery
            if not drift_detected:
                recovered = await self.drift_detector.check_recovery(service_id)
                if recovered:
                    await self.transition_state(
                        service_id=service_id,
                        new_state=HealthState.STABLE,
                        metadata={
                            'reason': 'recovered',
                            'recovery_samples': 50
                        }
                    )
    
    async def get_detailed_health(self, service_id: str) -> Dict[str, Any]:
        """
        Get comprehensive health information for a service
        
        Returns:
            Dictionary with state, baseline, telemetry count, and metadata
        """
        # Get health state
        health = await self.db.get_health_state(service_id)
        if not health:
            return {
                'service_id': service_id,
                'state': HealthState.INSUFFICIENT_DATA,
                'sample_count': 0,
                'baseline': None,
                'metadata': {'reason': 'not_tracked'}
            }
        
        # Get baseline
        baseline = await self.db.get_baseline(service_id)
        
        # Get sample count
        sample_count = await self.db.get_telemetry_count(service_id)
        
        # Parse metadata
        import json
        metadata = json.loads(health['metadata']) if health.get('metadata') else {}
        
        # Get recent drift events
        recent_events = await self.db.get_recent_drift_events(service_id, limit=5)
        
        return {
            'service_id': service_id,
            'state': health['state'],
            'transition_timestamp': datetime.fromtimestamp(health['transition_timestamp'] / 1000),
            'sample_count': sample_count,
            'baseline': baseline,
            'metadata': metadata,
            'recent_events': recent_events
        }
    
    async def reset_service(self, service_id: str):
        """
        Reset service to INSUFFICIENT_DATA state (admin operation)
        
        This would be used if baseline needs to be rebuilt from scratch
        """
        await self.transition_state(
            service_id=service_id,
            new_state=HealthState.INSUFFICIENT_DATA,
            metadata={'reason': 'manual_reset'}
        )