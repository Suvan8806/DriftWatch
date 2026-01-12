"""
DriftWatch Telemetry Ingestion
High-performance telemetry receiver with validation
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from models import TelemetryRequest
from config import TIMESTAMP_TOLERANCE_HOURS


class TelemetryValidator:
    """Validates incoming telemetry data"""
    
    @staticmethod
    def validate_timestamp(timestamp: Optional[datetime]) -> datetime:
        """
        Validate and normalize timestamp
        
        - If None, use current server time
        - If provided, ensure it's within acceptable range (±1 hour)
        
        Args:
            timestamp: Client-provided timestamp
        
        Returns:
            Validated timestamp
        
        Raises:
            ValueError: If timestamp is outside acceptable range
        """
        if timestamp is None:
            return datetime.now()
        
        now = datetime.now()
        tolerance = timedelta(hours=TIMESTAMP_TOLERANCE_HOURS)
        
        if timestamp < (now - tolerance) or timestamp > (now + tolerance):
            raise ValueError(
                f"Timestamp outside acceptable range: {timestamp} "
                f"(server time: {now}, tolerance: ±{TIMESTAMP_TOLERANCE_HOURS}h)"
            )
        
        return timestamp
    
    @staticmethod
    def validate_metrics(latency_ms: float, payload_kb: float):
        """
        Validate metric values
        
        Args:
            latency_ms: Latency in milliseconds
            payload_kb: Payload size in kilobytes
        
        Raises:
            ValueError: If metrics are invalid
        """
        if latency_ms < 0:
            raise ValueError(f"Negative latency not allowed: {latency_ms}")
        
        if payload_kb < 0:
            raise ValueError(f"Negative payload size not allowed: {payload_kb}")
        
        # Sanity checks for extreme values (likely errors)
        if latency_ms > 300000:  # 5 minutes
            raise ValueError(f"Latency exceeds reasonable maximum: {latency_ms}ms")
        
        if payload_kb > 1048576:  # 1 GB
            raise ValueError(f"Payload size exceeds reasonable maximum: {payload_kb}kb")


class IngestionQueue:
    """
    Async queue for decoupling ingestion from processing
    
    Provides backpressure mechanism via queue size limits
    """
    
    def __init__(self, maxsize: int = 10000):
        self.queue = asyncio.Queue(maxsize=maxsize)
        self.processing_task: Optional[asyncio.Task] = None
    
    async def enqueue(self, item: dict) -> bool:
        """
        Add item to processing queue
        
        Args:
            item: Telemetry data with service_id, timestamp, metrics
        
        Returns:
            True if enqueued successfully, False if queue full
        """
        try:
            self.queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            return False
    
    async def start_processing(self, processor_func):
        """
        Start background processing of queued items
        
        Args:
            processor_func: Async function to process each item
        """
        self.processing_task = asyncio.create_task(
            self._process_loop(processor_func)
        )
        print("✓ Ingestion queue processor started")
    
    async def _process_loop(self, processor_func):
        """Internal processing loop"""
        while True:
            try:
                # Get batch of items (up to 10 at once for efficiency)
                batch = []
                for _ in range(10):
                    try:
                        item = self.queue.get_nowait()
                        batch.append(item)
                    except asyncio.QueueEmpty:
                        break
                
                if not batch:
                    # Queue is empty, wait a bit
                    await asyncio.sleep(0.1)
                    continue
                
                # Process batch
                for item in batch:
                    try:
                        await processor_func(item)
                    except Exception as e:
                        print(f"✗ Error processing telemetry: {e}")
                
            except asyncio.CancelledError:
                print("✓ Ingestion queue processor stopped")
                break
            except Exception as e:
                print(f"✗ Unexpected error in processing loop: {e}")
                await asyncio.sleep(1)
    
    async def stop_processing(self):
        """Stop background processing"""
        if self.processing_task:
            self.processing_task.cancel()
            try:
                await self.processing_task
            except asyncio.CancelledError:
                pass
    
    def size(self) -> int:
        """Get current queue size"""
        return self.queue.qsize()


class TelemetryIngestionService:
    """
    High-level service for telemetry ingestion
    
    Coordinates validation, queuing, and persistence
    """
    
    def __init__(self, db, health_manager):
        self.db = db
        self.health_manager = health_manager
        self.validator = TelemetryValidator()
        self.queue = IngestionQueue()
        self.stats = {
            'received': 0,
            'processed': 0,
            'rejected': 0
        }
    
    async def start(self):
        """Start ingestion service"""
        await self.queue.start_processing(self._process_telemetry)
        print("✓ Telemetry ingestion service started")
    
    async def stop(self):
        """Stop ingestion service"""
        await self.queue.stop_processing()
        print("✓ Telemetry ingestion service stopped")
    
    async def ingest(self, request: TelemetryRequest) -> dict:
        """
        Ingest telemetry data
        
        This is the main entry point called by API endpoints
        
        Args:
            request: Validated telemetry request
        
        Returns:
            Response dictionary with status
        
        Raises:
            ValueError: If validation fails
            RuntimeError: If queue is full (backpressure)
        """
        self.stats['received'] += 1
        
        # Validate timestamp
        timestamp = self.validator.validate_timestamp(request.timestamp)
        
        # Validate metrics
        self.validator.validate_metrics(request.latency_ms, request.payload_kb)
        
        # Enqueue for processing
        enqueued = await self.queue.enqueue({
            'service_id': request.service_id,
            'timestamp': timestamp,
            'latency_ms': request.latency_ms,
            'payload_kb': request.payload_kb
        })
        
        if not enqueued:
            self.stats['rejected'] += 1
            raise RuntimeError("Ingestion queue full - backpressure applied")
        
        return {
            'status': 'accepted',
            'service_id': request.service_id,
            'timestamp': timestamp,
            'queue_size': self.queue.size()
        }
    
    async def _process_telemetry(self, item: dict):
        """
        Process telemetry item from queue
        
        This runs in the background and handles:
        1. Persistence to database
        2. Health state evaluation
        
        Args:
            item: Telemetry data dictionary
        """
        try:
            # Persist to database
            await self.db.insert_telemetry(
                service_id=item['service_id'],
                timestamp=item['timestamp'],
                latency_ms=item['latency_ms'],
                payload_kb=item['payload_kb']
            )
            
            # Process through health state manager
            await self.health_manager.process_telemetry(
                service_id=item['service_id'],
                latency_ms=item['latency_ms'],
                payload_kb=item['payload_kb'],
                timestamp=item['timestamp']
            )
            
            self.stats['processed'] += 1
            
        except Exception as e:
            print(f"✗ Failed to process telemetry for {item['service_id']}: {e}")
            self.stats['rejected'] += 1
            raise
    
    def get_stats(self) -> dict:
        """Get ingestion statistics"""
        return {
            **self.stats,
            'queue_size': self.queue.size(),
            'processing_rate': (
                self.stats['processed'] / max(1, self.stats['received'])
            ) * 100
        }