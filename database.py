"""
DriftWatch Database Layer
SQLite connection management and schema initialization
"""
import aiosqlite
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from config import (
    DATABASE_PATH, 
    TELEMETRY_RETENTION_DAYS,
    DRIFT_EVENTS_RETENTION_DAYS
)


class Database:
    """Async SQLite database manager"""
    
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
    
    async def connect(self):
        """Initialize database connection and schema"""
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._init_schema()
        print(f"✓ Database connected: {self.db_path}")
    
    async def _init_schema(self):
        """Create tables if they don't exist"""
        with open('schema.sql', 'r') as f:
            schema = f.read()
        
        await self._connection.executescript(schema)
        await self._connection.commit()
    
    async def close(self):
        """Close database connection"""
        if self._connection:
            await self._connection.close()
            print("✓ Database connection closed")
    
    # Telemetry Operations
    
    async def insert_telemetry(
        self, 
        service_id: str, 
        timestamp: datetime,
        latency_ms: float,
        payload_kb: float
    ) -> int:
        """Insert telemetry record"""
        ts_epoch = int(timestamp.timestamp() * 1000)
        created_at = int(datetime.now().timestamp() * 1000)
        
        cursor = await self._connection.execute(
            """
            INSERT INTO telemetry (service_id, timestamp, latency_ms, payload_kb, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (service_id, ts_epoch, latency_ms, payload_kb, created_at)
        )
        await self._connection.commit()
        return cursor.lastrowid
    
    async def get_recent_telemetry(
        self, 
        service_id: str, 
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get recent telemetry for a service"""
        cursor = await self._connection.execute(
            """
            SELECT * FROM telemetry
            WHERE service_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (service_id, limit)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def get_telemetry_count(self, service_id: str) -> int:
        """Count telemetry records for a service"""
        cursor = await self._connection.execute(
            "SELECT COUNT(*) as count FROM telemetry WHERE service_id = ?",
            (service_id,)
        )
        row = await cursor.fetchone()
        return row['count']
    
    async def get_total_telemetry_count(self) -> int:
        """Count all telemetry records"""
        cursor = await self._connection.execute(
            "SELECT COUNT(*) as count FROM telemetry"
        )
        row = await cursor.fetchone()
        return row['count']
    
    # Baseline Operations
    
    async def upsert_baseline(
        self,
        service_id: str,
        sample_count: int,
        mean_latency: float,
        stddev_latency: float,
        mean_payload: float,
        stddev_payload: float,
        p50_latency: Optional[float] = None,
        p95_latency: Optional[float] = None,
        p99_latency: Optional[float] = None
    ):
        """Insert or update baseline statistics"""
        now = int(datetime.now().timestamp() * 1000)
        
        async with self._lock:
            cursor = await self._connection.execute(
                "SELECT service_id FROM baselines WHERE service_id = ?",
                (service_id,)
            )
            exists = await cursor.fetchone()
            
            if exists:
                await self._connection.execute(
                    """
                    UPDATE baselines 
                    SET sample_count = ?, mean_latency = ?, stddev_latency = ?,
                        mean_payload = ?, stddev_payload = ?, 
                        p50_latency = ?, p95_latency = ?, p99_latency = ?,
                        last_updated = ?
                    WHERE service_id = ?
                    """,
                    (sample_count, mean_latency, stddev_latency, 
                     mean_payload, stddev_payload,
                     p50_latency, p95_latency, p99_latency, now, service_id)
                )
            else:
                await self._connection.execute(
                    """
                    INSERT INTO baselines 
                    (service_id, sample_count, mean_latency, stddev_latency, 
                     mean_payload, stddev_payload, p50_latency, p95_latency, p99_latency,
                     last_updated, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (service_id, sample_count, mean_latency, stddev_latency,
                     mean_payload, stddev_payload, p50_latency, p95_latency, p99_latency,
                     now, now)
                )
            
            await self._connection.commit()
    
    async def get_baseline(self, service_id: str) -> Optional[Dict[str, Any]]:
        """Get baseline for a service"""
        cursor = await self._connection.execute(
            "SELECT * FROM baselines WHERE service_id = ?",
            (service_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    # Health State Operations
    
    async def upsert_health_state(
        self,
        service_id: str,
        state: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Insert or update health state"""
        import json
        now = int(datetime.now().timestamp() * 1000)
        metadata_json = json.dumps(metadata) if metadata else None
        
        async with self._lock:
            cursor = await self._connection.execute(
                "SELECT service_id FROM health_states WHERE service_id = ?",
                (service_id,)
            )
            exists = await cursor.fetchone()
            
            if exists:
                await self._connection.execute(
                    """
                    UPDATE health_states 
                    SET state = ?, transition_timestamp = ?, metadata = ?
                    WHERE service_id = ?
                    """,
                    (state, now, metadata_json, service_id)
                )
            else:
                await self._connection.execute(
                    """
                    INSERT INTO health_states 
                    (service_id, state, transition_timestamp, metadata)
                    VALUES (?, ?, ?, ?)
                    """,
                    (service_id, state, now, metadata_json)
                )
            
            await self._connection.commit()
    
    async def get_health_state(self, service_id: str) -> Optional[Dict[str, Any]]:
        """Get health state for a service"""
        cursor = await self._connection.execute(
            "SELECT * FROM health_states WHERE service_id = ?",
            (service_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def get_monitored_services_count(self) -> int:
        """Count services with health states"""
        cursor = await self._connection.execute(
            "SELECT COUNT(DISTINCT service_id) as count FROM health_states"
        )
        row = await cursor.fetchone()
        return row['count']
    
    # Drift Event Operations
    
    async def insert_drift_event(
        self,
        service_id: str,
        previous_state: str,
        new_state: str,
        trigger_samples: Optional[List[float]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Insert drift event for audit trail"""
        import json
        now = int(datetime.now().timestamp() * 1000)
        trigger_json = json.dumps(trigger_samples) if trigger_samples else None
        metadata_json = json.dumps(metadata) if metadata else None
        
        cursor = await self._connection.execute(
            """
            INSERT INTO drift_events 
            (service_id, detected_at, previous_state, new_state, trigger_samples, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (service_id, now, previous_state, new_state, trigger_json, metadata_json)
        )
        await self._connection.commit()
        return cursor.lastrowid
    
    async def get_recent_drift_events(
        self, 
        service_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get recent drift events"""
        if service_id:
            cursor = await self._connection.execute(
                """
                SELECT * FROM drift_events
                WHERE service_id = ?
                ORDER BY detected_at DESC
                LIMIT ?
                """,
                (service_id, limit)
            )
        else:
            cursor = await self._connection.execute(
                """
                SELECT * FROM drift_events
                ORDER BY detected_at DESC
                LIMIT ?
                """,
                (limit,)
            )
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    # Z-Score History Operations
    
    async def insert_zscore(
        self,
        service_id: str,
        timestamp: datetime,
        latency_zscore: float,
        payload_zscore: float
    ):
        """Insert z-score for drift tracking"""
        ts_epoch = int(timestamp.timestamp() * 1000)
        created_at = int(datetime.now().timestamp() * 1000)
        
        await self._connection.execute(
            """
            INSERT INTO zscore_history 
            (service_id, timestamp, latency_zscore, payload_zscore, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (service_id, ts_epoch, latency_zscore, payload_zscore, created_at)
        )
        await self._connection.commit()
    
    async def get_recent_zscores(
        self, 
        service_id: str, 
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get recent z-scores for a service"""
        cursor = await self._connection.execute(
            """
            SELECT * FROM zscore_history
            WHERE service_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (service_id, limit)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    # Maintenance Operations
    
    async def cleanup_old_data(self):
        """Remove old telemetry and events per retention policy"""
        telemetry_cutoff = int(
            (datetime.now() - timedelta(days=TELEMETRY_RETENTION_DAYS)).timestamp() * 1000
        )
        events_cutoff = int(
            (datetime.now() - timedelta(days=DRIFT_EVENTS_RETENTION_DAYS)).timestamp() * 1000
        )
        
        await self._connection.execute(
            "DELETE FROM telemetry WHERE created_at < ?",
            (telemetry_cutoff,)
        )
        await self._connection.execute(
            "DELETE FROM drift_events WHERE detected_at < ?",
            (events_cutoff,)
        )
        await self._connection.execute(
            "DELETE FROM zscore_history WHERE created_at < ?",
            (telemetry_cutoff,)
        )
        await self._connection.commit()


# Global database instance
db = Database()