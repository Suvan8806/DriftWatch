#!/usr/bin/env python3
"""
DriftWatch Synthetic Traffic Simulator
Generates realistic telemetry patterns to validate drift detection

Usage:
    python simulator.py --mode NORMAL --duration 60
    python simulator.py --mode SPIKE --duration 90
    python simulator.py --mode CREEP --duration 120
"""
import asyncio
import argparse
import sys
from datetime import datetime
from typing import List, Tuple
import numpy as np
import httpx


class TrafficGenerator:
    """Generates synthetic telemetry with configurable patterns"""
    
    @staticmethod
    def generate_normal(
        count: int,
        latency_mean: float = 150.0,
        latency_std: float = 25.0,
        payload_mean: float = 2.5,
        payload_std: float = 0.8
    ) -> List[Tuple[float, float]]:
        """
        Generate normal/healthy traffic pattern
        
        Args:
            count: Number of samples to generate
            latency_mean: Mean latency in ms
            latency_std: Standard deviation of latency
            payload_mean: Mean payload size in KB
            payload_std: Standard deviation of payload
        
        Returns:
            List of (latency_ms, payload_kb) tuples
        """
        # Normal distribution for latency
        latencies = np.random.normal(latency_mean, latency_std, count)
        latencies = np.clip(latencies, 1, None)  # Ensure positive
        
        # Log-normal distribution for payload (more realistic)
        payloads = np.random.lognormal(
            np.log(payload_mean), 
            payload_std / payload_mean, 
            count
        )
        payloads = np.clip(payloads, 0.1, None)
        
        return list(zip(latencies.tolist(), payloads.tolist()))
    
    @staticmethod
    def generate_spike(
        total_duration: int,
        samples_per_sec: int,
        normal_latency: float = 150.0,
        spike_latency: float = 500.0
    ) -> List[Tuple[float, float, float]]:
        """
        Generate traffic with sudden spike in the middle
        
        Pattern:
        - First 40%: NORMAL
        - Middle 30%: SPIKE (3.3x latency increase)
        - Last 30%: NORMAL (recovery)
        
        Args:
            total_duration: Total duration in seconds
            samples_per_sec: Samples per second
            normal_latency: Baseline latency
            spike_latency: Spiked latency
        
        Returns:
            List of (latency_ms, payload_kb, timestamp_offset) tuples
        """
        total_samples = total_duration * samples_per_sec
        
        # Calculate phase boundaries
        phase1_end = int(total_samples * 0.4)
        phase2_end = int(total_samples * 0.7)
        
        samples = []
        
        # Phase 1: Normal (40%)
        phase1 = TrafficGenerator.generate_normal(phase1_end)
        for i, (lat, pay) in enumerate(phase1):
            samples.append((lat, pay, i / samples_per_sec))
        
        # Phase 2: Spike (30%)
        phase2_count = phase2_end - phase1_end
        phase2 = TrafficGenerator.generate_normal(
            phase2_count,
            latency_mean=spike_latency,
            latency_std=spike_latency * 0.15
        )
        for i, (lat, pay) in enumerate(phase2):
            offset = (phase1_end + i) / samples_per_sec
            samples.append((lat, pay, offset))
        
        # Phase 3: Recovery (30%)
        phase3_count = total_samples - phase2_end
        phase3 = TrafficGenerator.generate_normal(phase3_count)
        for i, (lat, pay) in enumerate(phase3):
            offset = (phase2_end + i) / samples_per_sec
            samples.append((lat, pay, offset))
        
        return samples
    
    @staticmethod
    def generate_creep(
        total_duration: int,
        samples_per_sec: int,
        start_latency: float = 150.0,
        end_latency: float = 300.0
    ) -> List[Tuple[float, float, float]]:
        """
        Generate traffic with gradual latency increase (creep)
        
        Latency increases linearly from start to end over duration
        
        Args:
            total_duration: Total duration in seconds
            samples_per_sec: Samples per second
            start_latency: Initial latency
            end_latency: Final latency
        
        Returns:
            List of (latency_ms, payload_kb, timestamp_offset) tuples
        """
        total_samples = total_duration * samples_per_sec
        samples = []
        
        for i in range(total_samples):
            # Linear interpolation of mean latency
            progress = i / total_samples
            current_mean = start_latency + (end_latency - start_latency) * progress
            current_std = current_mean * 0.15
            
            # Generate sample with current mean
            latency = np.random.normal(current_mean, current_std)
            latency = max(1, latency)
            
            payload = np.random.lognormal(np.log(2.5), 0.32)
            payload = max(0.1, payload)
            
            offset = i / samples_per_sec
            samples.append((latency, payload, offset))
        
        return samples


class DriftWatchSimulator:
    """Simulates traffic to DriftWatch API"""
    
    def __init__(self, api_url: str = "http://localhost:8000"):
        self.api_url = api_url
        self.client = None
    
    async def send_telemetry(
        self, 
        service_id: str, 
        latency_ms: float, 
        payload_kb: float
    ) -> bool:
        """
        Send telemetry to DriftWatch API
        
        Args:
            service_id: Service identifier
            latency_ms: Latency measurement
            payload_kb: Payload size
        
        Returns:
            True if successful
        """
        try:
            response = await self.client.post(
                f"{self.api_url}/v1/telemetry",
                json={
                    "service_id": service_id,
                    "latency_ms": latency_ms,
                    "payload_kb": payload_kb
                },
                timeout=5.0
            )
            return response.status_code in (200, 202)
        except Exception as e:
            print(f"✗ Failed to send telemetry: {e}")
            return False
    
    async def check_health(self, service_id: str) -> dict:
        """Query service health state"""
        try:
            response = await self.client.get(
                f"{self.api_url}/v1/health/{service_id}",
                timeout=5.0
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"✗ Failed to check health: {e}")
            return None
    
    async def run_simulation(
        self,
        service_id: str,
        mode: str,
        duration: int,
        samples_per_sec: int = 10
    ):
        """
        Run complete simulation
        
        Args:
            service_id: Service to simulate
            mode: NORMAL, SPIKE, or CREEP
            duration: Duration in seconds
            samples_per_sec: Sampling rate
        """
        print("=" * 70)
        print(f"DriftWatch Traffic Simulator")
        print("=" * 70)
        print(f"Service:   {service_id}")
        print(f"Mode:      {mode}")
        print(f"Duration:  {duration}s")
        print(f"Rate:      {samples_per_sec} samples/sec")
        print(f"API:       {self.api_url}")
        print("=" * 70)
        
        # Generate traffic pattern
        print(f"\n⚙ Generating {mode} traffic pattern...")
        
        if mode == "NORMAL":
            samples = TrafficGenerator.generate_normal(
                duration * samples_per_sec
            )
            # Add time offsets
            samples = [(lat, pay, i / samples_per_sec) 
                      for i, (lat, pay) in enumerate(samples)]
        
        elif mode == "SPIKE":
            samples = TrafficGenerator.generate_spike(
                duration, samples_per_sec
            )
        
        elif mode == "CREEP":
            samples = TrafficGenerator.generate_creep(
                duration, samples_per_sec
            )
        
        else:
            print(f"✗ Unknown mode: {mode}")
            return
        
        print(f"✓ Generated {len(samples)} samples")
        
        # Initialize HTTP client
        async with httpx.AsyncClient() as client:
            self.client = client
            
            # Check API health
            try:
                response = await client.get(f"{self.api_url}/health", timeout=5.0)
                if response.status_code != 200:
                    print(f"✗ DriftWatch API not responding at {self.api_url}")
                    return
                print(f"✓ DriftWatch API is healthy")
            except Exception as e:
                print(f"✗ Cannot connect to DriftWatch API: {e}")
                return
            
            # Send telemetry
            print(f"\n📊 Sending telemetry...")
            start_time = asyncio.get_event_loop().time()
            sent_count = 0
            failed_count = 0
            
            last_health_check = 0
            health_check_interval = max(duration // 10, 5)  # Check 10 times
            
            for i, (latency, payload, offset) in enumerate(samples):
                # Wait until correct time offset
                target_time = start_time + offset
                current_time = asyncio.get_event_loop().time()
                wait_time = target_time - current_time
                
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                
                # Send telemetry
                success = await self.send_telemetry(service_id, latency, payload)
                if success:
                    sent_count += 1
                else:
                    failed_count += 1
                
                # Calculate elapsed time
                elapsed = asyncio.get_event_loop().time() - start_time
                
                # Progress indicator
                if (i + 1) % (samples_per_sec * 5) == 0:
                    print(f"  [{elapsed:6.1f}s] Sent: {sent_count:4d} | "
                          f"Failed: {failed_count:2d} | "
                          f"Latest: lat={latency:6.1f}ms pay={payload:4.1f}kb")
                
                # Periodic health check
                if elapsed - last_health_check >= health_check_interval:
                    health = await self.check_health(service_id)
                    if health:
                        state = health.get('state', 'UNKNOWN')
                        sample_count = health.get('sample_count', 0)
                        print(f"  ⚡ Health: {state} (samples: {sample_count})")
                    last_health_check = elapsed
            
            # Final statistics
            total_time = asyncio.get_event_loop().time() - start_time
            print(f"\n{'=' * 70}")
            print(f"Simulation Complete")
            print(f"{'=' * 70}")
            print(f"Total time:      {total_time:.1f}s")
            print(f"Samples sent:    {sent_count}")
            print(f"Failed:          {failed_count}")
            print(f"Success rate:    {(sent_count/len(samples))*100:.1f}%")
            
            # Final health check
            print(f"\n📋 Final Health Status:")
            health = await self.check_health(service_id)
            if health:
                print(f"  State:           {health.get('state')}")
                print(f"  Samples:         {health.get('sample_count')}")
                print(f"  Transition:      {health.get('transition_timestamp')}")
                
                if health.get('baseline'):
                    baseline = health['baseline']
                    print(f"\n  Baseline:")
                    print(f"    Mean latency:  {baseline.get('mean_latency', 0):.2f}ms")
                    print(f"    Std dev:       {baseline.get('stddev_latency', 0):.2f}ms")
                    print(f"    Sample count:  {baseline.get('sample_count', 0)}")
            
            print(f"{'=' * 70}")


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="DriftWatch Synthetic Traffic Simulator"
    )
    parser.add_argument(
        "--service-id",
        default="test-payment-service",
        help="Service identifier (default: test-payment-service)"
    )
    parser.add_argument(
        "--mode",
        choices=["NORMAL", "SPIKE", "CREEP"],
        default="NORMAL",
        help="Traffic pattern mode (default: NORMAL)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Simulation duration in seconds (default: 60)"
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=10,
        help="Samples per second (default: 10)"
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="DriftWatch API URL (default: http://localhost:8000)"
    )
    
    args = parser.parse_args()
    
    simulator = DriftWatchSimulator(api_url=args.api_url)
    
    try:
        await simulator.run_simulation(
            service_id=args.service_id,
            mode=args.mode,
            duration=args.duration,
            samples_per_sec=args.rate
        )
    except KeyboardInterrupt:
        print("\n\n✗ Simulation interrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())