"""
DriftWatch - Statistical Drift Detection Platform
Main FastAPI application
"""
import os
import time
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

from models import (
    TelemetryRequest, TelemetryResponse,
    HealthStatus, BaselineStats, SystemStatus,
    SimulationRequest, SimulationResponse
)
from database import db
from health import HealthStateManager
from ingestion import TelemetryIngestionService
from config import API_HOST, API_PORT, HealthState


# Application startup/shutdown lifecycle
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    # Startup
    print("=" * 60)
    print("DriftWatch - Statistical Drift Detection Platform")
    print("=" * 60)
    
    # Initialize database
    await db.connect()
    
    # Initialize health manager
    app.state.health_manager = HealthStateManager(db)
    
    # Initialize ingestion service
    app.state.ingestion_service = TelemetryIngestionService(
        db, 
        app.state.health_manager
    )
    await app.state.ingestion_service.start()
    
    # Track startup time
    app.state.startup_time = time.time()
    
    print("✓ DriftWatch is ready")
    print(f"✓ API listening on http://{API_HOST}:{API_PORT}")
    print("=" * 60)
    
    yield
    
    # Shutdown
    print("\n" + "=" * 60)
    print("Shutting down DriftWatch...")
    await app.state.ingestion_service.stop()
    await db.close()
    print("✓ DriftWatch stopped gracefully")
    print("=" * 60)


# Create FastAPI application
app = FastAPI(
    title="DriftWatch",
    description="Statistical Drift Detection Platform for Service Reliability",
    version="1.0.0",
    lifespan=lifespan
)


# ============================================================================
# TELEMETRY INGESTION ENDPOINTS
# ============================================================================

@app.post(
    "/v1/telemetry",
    response_model=TelemetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Ingestion"]
)
async def ingest_telemetry(request: TelemetryRequest):
    """
    Ingest telemetry data from monitored services
    
    Accepts latency and payload size measurements and queues them for
    statistical analysis and drift detection.
    
    - **service_id**: Unique identifier for the service (e.g., payment-auth-prod)
    - **latency_ms**: Request latency in milliseconds (non-negative)
    - **payload_kb**: Payload size in kilobytes (non-negative)
    - **timestamp**: Optional ISO 8601 timestamp (defaults to server time)
    """
    try:
        result = await app.state.ingestion_service.ingest(request)
        
        return TelemetryResponse(
            status="accepted",
            service_id=result['service_id'],
            timestamp=result['timestamp'],
            message=f"Telemetry queued for processing (queue size: {result['queue_size']})"
        )
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e)
        )
    except Exception as e:
        print(f"✗ Unexpected error in telemetry ingestion: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during telemetry ingestion"
        )


# ============================================================================
# HEALTH & MONITORING ENDPOINTS
# ============================================================================

@app.get(
    "/v1/health/{service_id}",
    response_model=HealthStatus,
    tags=["Monitoring"]
)
async def get_service_health(service_id: str):
    """
    Get current health state for a service
    
    Returns the service's current state (INSUFFICIENT_DATA, STABLE, or DRIFT_DETECTED)
    along with baseline statistics and metadata.
    
    - **service_id**: Service identifier
    """
    try:
        health_data = await app.state.health_manager.get_detailed_health(service_id)
        
        # Format baseline if exists
        baseline = None
        if health_data['baseline']:
            b = health_data['baseline']
            baseline = BaselineStats(
                service_id=service_id,
                sample_count=b['sample_count'],
                mean_latency=b['mean_latency'],
                stddev_latency=b['stddev_latency'],
                mean_payload=b['mean_payload'],
                stddev_payload=b['stddev_payload'],
                last_updated=datetime.fromtimestamp(b['last_updated'] / 1000),
                created_at=datetime.fromtimestamp(b['created_at'] / 1000)
            )
        
        return HealthStatus(
            service_id=service_id,
            state=health_data['state'],
            transition_timestamp=health_data['transition_timestamp'],
            sample_count=health_data['sample_count'],
            baseline=baseline,
            metadata=health_data.get('metadata')
        )
    
    except Exception as e:
        print(f"✗ Error retrieving health for {service_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve health status: {str(e)}"
        )


@app.get(
    "/v1/baseline/{service_id}",
    response_model=BaselineStats,
    tags=["Monitoring"]
)
async def get_service_baseline(service_id: str):
    """
    Get current baseline statistics for a service
    
    Returns computed statistical baseline including mean, standard deviation,
    and percentiles for latency and payload metrics.
    
    - **service_id**: Service identifier
    """
    try:
        baseline = await db.get_baseline(service_id)
        
        if not baseline:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No baseline found for service: {service_id}"
            )
        
        return BaselineStats(
            service_id=service_id,
            sample_count=baseline['sample_count'],
            mean_latency=baseline['mean_latency'],
            stddev_latency=baseline['stddev_latency'],
            mean_payload=baseline['mean_payload'],
            stddev_payload=baseline['stddev_payload'],
            last_updated=datetime.fromtimestamp(baseline['last_updated'] / 1000),
            created_at=datetime.fromtimestamp(baseline['created_at'] / 1000)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"✗ Error retrieving baseline for {service_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve baseline: {str(e)}"
        )


# ============================================================================
# SYSTEM STATUS ENDPOINTS
# ============================================================================

@app.get(
    "/v1/system/status",
    response_model=SystemStatus,
    tags=["System"]
)
async def get_system_status():
    """
    Get DriftWatch system health and statistics
    
    Returns overall system metrics including uptime, services monitored,
    and database size.
    """
    try:
        uptime = time.time() - app.state.startup_time
        services_count = await db.get_monitored_services_count()
        total_records = await db.get_total_telemetry_count()
        
        # Get database file size
        db_size_bytes = os.path.getsize(db.db_path) if os.path.exists(db.db_path) else 0
        db_size_mb = db_size_bytes / (1024 * 1024)
        
        # Get ingestion stats
        ingestion_stats = app.state.ingestion_service.get_stats()
        
        return SystemStatus(
            status="healthy",
            uptime_seconds=uptime,
            services_monitored=services_count,
            total_telemetry_records=total_records,
            database_size_mb=db_size_mb,
            active_simulations=0  # Implemented in simulator
        )
    
    except Exception as e:
        print(f"✗ Error retrieving system status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve system status: {str(e)}"
        )


@app.get("/", tags=["System"])
async def root():
    """Root endpoint - API information"""
    return {
        "service": "DriftWatch",
        "version": "1.0.0",
        "description": "Statistical Drift Detection Platform for Service Reliability",
        "endpoints": {
            "telemetry": "POST /v1/telemetry",
            "health": "GET /v1/health/{service_id}",
            "baseline": "GET /v1/baseline/{service_id}",
            "system": "GET /v1/system/status"
        },
        "docs": "/docs"
    }


@app.get("/health", tags=["System"])
async def health_check():
    """Simple health check endpoint"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Catch-all exception handler"""
    print(f"✗ Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "type": type(exc).__name__
        }
    )


# ============================================================================
# APPLICATION ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=API_HOST,
        port=API_PORT,
        log_level="info",
        access_log=True
    )