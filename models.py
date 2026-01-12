"""
DriftWatch Data Models
Pydantic schemas for API request/response validation
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, validator
from config import MAX_SERVICE_ID_LENGTH


class TelemetryRequest(BaseModel):
    """Incoming telemetry data from monitored services"""
    service_id: str = Field(..., min_length=1, max_length=MAX_SERVICE_ID_LENGTH)
    latency_ms: float = Field(..., ge=0.0)
    payload_kb: float = Field(..., ge=0.0)
    timestamp: Optional[datetime] = None

    @validator('service_id')
    def validate_service_id(cls, v):
        """Ensure service_id contains only valid characters"""
        if not all(c.isalnum() or c in '-_.' for c in v):
            raise ValueError('service_id must contain only alphanumeric, hyphens, underscores, or dots')
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "service_id": "payment-authorization-prod",
                "latency_ms": 156.7,
                "payload_kb": 2.3,
                "timestamp": "2026-01-12T10:30:45.123Z"
            }
        }


class TelemetryResponse(BaseModel):
    """Response after telemetry ingestion"""
    status: str
    service_id: str
    timestamp: datetime
    message: Optional[str] = None


class BaselineStats(BaseModel):
    """Statistical baseline for a service"""
    service_id: str
    sample_count: int
    mean_latency: float
    stddev_latency: float
    mean_payload: float
    stddev_payload: float
    last_updated: datetime
    created_at: datetime


class HealthStatus(BaseModel):
    """Current health state of a service"""
    service_id: str
    state: str
    transition_timestamp: datetime
    sample_count: int
    baseline: Optional[BaselineStats] = None
    metadata: Optional[dict] = None

    class Config:
        json_schema_extra = {
            "example": {
                "service_id": "payment-authorization-prod",
                "state": "STABLE",
                "transition_timestamp": "2026-01-12T10:32:15.000Z",
                "sample_count": 450,
                "baseline": {
                    "mean_latency": 152.3,
                    "stddev_latency": 24.8
                }
            }
        }


class DriftEvent(BaseModel):
    """Audit record of state transitions"""
    id: int
    service_id: str
    detected_at: datetime
    previous_state: str
    new_state: str
    trigger_samples: Optional[List[float]] = None


class SimulationRequest(BaseModel):
    """Request to start synthetic traffic simulation"""
    service_id: str = Field(..., min_length=1, max_length=MAX_SERVICE_ID_LENGTH)
    mode: str = Field(..., pattern="^(NORMAL|SPIKE|CREEP)$")
    duration_seconds: int = Field(default=60, ge=10, le=300)
    samples_per_second: int = Field(default=10, ge=1, le=100)

    class Config:
        json_schema_extra = {
            "example": {
                "service_id": "test-payment-service",
                "mode": "SPIKE",
                "duration_seconds": 60,
                "samples_per_second": 10
            }
        }


class SimulationResponse(BaseModel):
    """Response after starting simulation"""
    status: str
    simulation_id: str
    service_id: str
    mode: str
    duration_seconds: int
    message: str


class SystemStatus(BaseModel):
    """DriftWatch system health"""
    status: str
    uptime_seconds: float
    services_monitored: int
    total_telemetry_records: int
    database_size_mb: float
    active_simulations: int