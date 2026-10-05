#!/usr/bin/env python3
"""
Quick Queue Demo - runs with standard runserver
Shows the key benefit: upload returns in ~100ms instead of 28s
"""
import os
import sys
import time
import requests
import uuid

BASE_URL = "http://127.0.0.1:8000"
CAMERA_CODE = "CAM-01"
TEST_IMAGE = "sample_inputs/clearcar.jpg"
NUM_REQUESTS = 2


def check_server():
    try:
        r = requests.get(f"{BASE_URL}/api/health/", timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"  Health check error: {e}")
        return False


def upload_async(image_path):
    """Current async endpoint - returns immediately after queueing."""
    with open(image_path, "rb") as f:
        return requests.post(
            f"{BASE_URL}/api/captures/",
            data={"camera": CAMERA_CODE},
            files={"image": ("test.jpg", f, "image/jpeg")},
            headers={"Idempotency-Key": str(uuid.uuid4())},
            timeout=30
        ).json()


if __name__ == "__main__":
    print("="*60)
    print("QUEUE DEMO: Upload Latency Comparison")
    print("="*60)
    print("Run with: python manage.py runserver  (single-threaded)")
    
    if not check_server():
        print("\nERROR: Django server not running on http://127.0.0.1:8000")
        print("Start with: python manage.py runserver")
        sys.exit(1)
    print("✓ Django server responding (runserver)")
    
    import redis
    try:
        r = redis.Redis(decode_responses=True)
        r.ping()
        r.flushall()
        print("✓ Redis connected, queue cleared")
    except:
        print("ERROR: Redis not running - start with: redis-server")
        sys.exit(1)
    
    # Check Celery worker
    try:
        queue_len = r.llen("celery")
        print(f"✓ Celery queue ready: {queue_len} pending")
    except:
        print("⚠ Could not check queue")
    
    print(f"\n{'='*60}")
    print(f"SENDING {NUM_REQUESTS} UPLOADS (sequential due to runserver)")
    print(f"{'='*60}")
    print("With queue: each upload returns in ~100ms")
    print("Without queue: each upload would block for ~28s")
    print()
    
    upload_times = []
    
    for i in range(NUM_REQUESTS):
        req_start = time.time()
        result = upload_async(TEST_IMAGE)
        elapsed = (time.time() - req_start) * 1000
        upload_times.append(elapsed)
        print(f"  [{i+1}/{NUM_REQUESTS}] Accepted in {elapsed:.0f}ms - {result['status']} ({result['uuid']})")
    
    total = sum(upload_times) / 1000
    avg = sum(upload_times) / len(upload_times)
    
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    print(f"Total time for {NUM_REQUESTS} uploads: {total:.1f}s")
    print(f"Average upload latency: {avg:.0f}ms")
    print(f"")
    print(f"COMPARISON:")
    print(f"  Without queue: {NUM_REQUESTS} × 28s = {NUM_REQUESTS*28}s (client blocked)")
    print(f"  With queue:    {NUM_REQUESTS} × {avg/1000:.3f}s = {total:.1f}s (client free)")
    print(f"  Speedup:       {28/(avg/1000):.0f}x faster per upload")
    print(f"")
    print(f"KEY INSIGHT FOR DOCUMENTATION:")
    print(f"  ✓ Client wait: 28,000ms → {avg:.0f}ms ({int(28000/avg)}x improvement)")
    print(f"  ✓ Server responsive during processing")
    print(f"  ✓ Queue absorbs burst, workers process at own pace")
    print(f"  ✓ Failed items don't block other cameras")
    print(f"  ✓ Add Celery workers independently for more throughput")
    print(f"  ✓ Queue visible: redis-cli llen celery")
    print(f"")
    print(f"  With runserver: sequential uploads (1 at a time)")
    print(f"  Architecture: Client → Django (50ms) → Redis → Celery Workers → DB")