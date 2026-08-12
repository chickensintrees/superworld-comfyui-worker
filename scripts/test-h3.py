#!/usr/bin/env python3
"""Smoke-test MiniMax H3 on the RunPod serverless ComfyUI endpoint.

Submits workflows/minimax-h3-i2v.json (or its t2v variant when no image is
given) and saves whatever the worker returns (mp4 with audio) locally.

  export RUNPOD_API_KEY=...        # runpod.io -> Settings -> API Keys
  export RUNPOD_ENDPOINT_ID=...    # the serverless endpoint id
  python3 scripts/test-h3.py --image still.png            # i2v
  python3 scripts/test-h3.py                              # t2v
  python3 scripts/test-h3.py --length 56 --steps 8        # cheap smoke test

length must land on the model's 17k+5 frame grid at 24fps (56 = ~2.3s,
124 = ~5.2s, 362 = ~15s); off-grid values are snapped up by the node.
"""
import argparse
import base64
import copy
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.join(HERE, "..", "workflows", "minimax-h3-i2v.json")


def api(url, key, payload=None, timeout=60):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def collect_files(obj, found):
    """Walk the result for {'data': <b64>} entries (worker returns media this way)."""
    if isinstance(obj, dict):
        if "data" in obj and isinstance(obj["data"], str) and len(obj["data"]) > 1000:
            found.append((obj.get("filename", f"output-{len(found)}.bin"), obj["data"]))
        for v in obj.values():
            collect_files(v, found)
    elif isinstance(obj, list):
        for v in obj:
            collect_files(v, found)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image", help="first-frame image (omit for t2v)")
    p.add_argument("--prompt", help="override the workflow prompt")
    p.add_argument("--length", type=int, help="frame count on the 17k+5 grid (default 124 = ~5s)")
    p.add_argument("--steps", type=int, help="sampler steps (default 20)")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--seed", type=int)
    p.add_argument("--timeout", type=int, default=1800, help="seconds to wait for the job")
    p.add_argument("--out", default="h3-output", help="output directory")
    args = p.parse_args()

    key = os.environ.get("RUNPOD_API_KEY")
    endpoint = os.environ.get("RUNPOD_ENDPOINT_ID")
    if not key or not endpoint:
        sys.exit("Set RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID")

    wf = copy.deepcopy(json.load(open(WORKFLOW)))
    node = wf["6"]["inputs"]
    if args.prompt:
        node["prompt"] = args.prompt
    if args.length:
        node["length"] = args.length
    if args.width:
        node["width"] = args.width
    if args.height:
        node["height"] = args.height
    if args.steps:
        wf["9"]["inputs"]["steps"] = args.steps
    if args.seed is not None:
        wf["7"]["inputs"]["noise_seed"] = args.seed

    payload = {"input": {"workflow": wf}}
    if args.image:
        b64 = base64.b64encode(open(args.image, "rb").read()).decode()
        payload["input"]["images"] = [{"name": "input.png", "image": b64}]
    else:
        # t2v: drop the image loader and the first_frame link
        del wf["5"]
        del node["first_frame"]

    base = f"https://api.runpod.ai/v2/{endpoint}"
    job = api(f"{base}/run", key, payload)
    job_id = job["id"]
    print(f"job {job_id} submitted ({'i2v' if args.image else 't2v'}, "
          f"length={node['length']}, {node['width']}x{node['height']})")

    t0 = time.time()
    while True:
        time.sleep(10)
        status = api(f"{base}/status/{job_id}", key)
        state = status.get("status")
        print(f"  [{int(time.time() - t0):>4}s] {state}")
        if state in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            break
        if time.time() - t0 > args.timeout:
            sys.exit(f"gave up after {args.timeout}s (job {job_id} still {state})")

    if state != "COMPLETED":
        print(json.dumps(status, indent=2)[:4000])
        sys.exit(f"job ended {state}")

    files = []
    collect_files(status.get("output"), files)
    if not files:
        print(json.dumps(status, indent=2)[:4000])
        sys.exit("job completed but no media found in output")

    os.makedirs(args.out, exist_ok=True)
    for name, data in files:
        dest = os.path.join(args.out, os.path.basename(name))
        with open(dest, "wb") as f:
            f.write(base64.b64decode(data))
        print(f"saved {dest} ({os.path.getsize(dest)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
