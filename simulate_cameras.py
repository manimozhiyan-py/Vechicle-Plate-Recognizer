"""Send uploads from several fake cameras at the same time and time them.

    python scripts/simulate_cameras.py --cameras 3 --wait

Needs at least that many cameras in the database (create them in the admin).
"""
import argparse
import threading
import time
from pathlib import Path
from statistics import mean

import requests

IMAGE_TYPES = {".jpg", ".jpeg", ".png"}


def upload(base, camera, images, count, results):
    """One fake camera: sends `count` images back to back."""
    for i in range(count):
        path = images[i % len(images)]
        start = time.perf_counter()
        with open(path, "rb") as f:
            response = requests.post(f"{base}/api/captures/", data={"camera": camera}, files={"image": f})
        accept = time.perf_counter() - start
        uuid = response.json().get("uuid") if response.status_code in (200, 202) else None
        results.append({"start": start, "accept": accept, "uuid": uuid})


def wait_for_results(base, results, timeout):
    """Poll every capture until it is completed or failed."""
    waiting = {r["uuid"]: r for r in results if r["uuid"]}
    deadline = time.perf_counter() + timeout
    while waiting and time.perf_counter() < deadline:
        for uuid, r in list(waiting.items()):
            data = requests.get(f"{base}/api/captures/{uuid}/").json()
            if data["status"] in ("completed", "failed"):
                r["done"] = time.perf_counter()
                r["final"] = data["status"]
                del waiting[uuid]
        time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--cameras", type=int, default=5)
    parser.add_argument("--per-camera", type=int, default=3, help="images each camera sends")
    parser.add_argument("--images", default="sample_inputs")
    parser.add_argument("--wait", action="store_true", help="wait for results and time them")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    images = sorted(p for p in Path(args.images).iterdir() if p.suffix.lower() in IMAGE_TYPES)
    codes = [c["code"] for c in requests.get(f"{args.url}/api/cameras/").json()["results"]]
    if len(codes) < args.cameras:
        raise SystemExit(f"Need {args.cameras} cameras in the database, found {len(codes)}.")

    results = []
    t0 = time.perf_counter()
    threads = [
        threading.Thread(target=upload, args=(args.url, code, images, args.per_camera, results))
        for code in codes[: args.cameras]
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    accepts = [r["accept"] for r in results]
    row = f"| {args.cameras} | {len(results)} | {mean(accepts):.2f} | {max(accepts):.2f} |"
    header = "| cameras | uploads | accept avg s | accept max s |"

    if args.wait:
        wait_for_results(args.url, results, args.timeout)
        done = [r for r in results if "done" in r]
        if done:
            totals = [r["done"] - r["start"] for r in done]
            failed = sum(r["final"] == "failed" for r in done)
            drain = max(r["done"] for r in done) - t0
            header += " finished | failed | total avg s | total max s | queue drain s |"
            row += f" {len(done)} | {failed} | {mean(totals):.2f} | {max(totals):.2f} | {drain:.2f} |"
        else:
            row += " nothing finished before the timeout |"

    print(header)
    print(row)


if __name__ == "__main__":
    main()
