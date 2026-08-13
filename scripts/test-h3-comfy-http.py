#!/usr/bin/env python3
"""Run the MiniMax H3 workflow against a ComfyUI HTTP API directly
(e.g. a RunPod pod's 8188 proxy URL, or localhost) — no serverless layer.

  python3 scripts/test-h3-comfy-http.py --url https://<podid>-8188.proxy.runpod.net \
      [--image still.png] [--length 56] [--steps 8] [--prompt "..."]

Omit --image for t2v. Saves the resulting video into ./h3-output/.
"""
import argparse
import copy
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.join(HERE, "..", "workflows", "minimax-h3-i2v.json")


UA = {"User-Agent": "h3-test/1.0"}  # Cloudflare 403s python-urllib's default UA


def call(url, payload=None, timeout=120, raw=False):
    headers = dict(UA)
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if raw else json.load(r)


def upload_image(base, path):
    boundary = uuid.uuid4().hex
    name = os.path.basename(path)
    with open(path, "rb") as f:
        data = f.read()
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
        f"filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{base}/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **UA},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["name"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True, help="ComfyUI base URL")
    p.add_argument("--image")
    p.add_argument("--prompt")
    p.add_argument("--length", type=int)
    p.add_argument("--steps", type=int)
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--seed", type=int)
    p.add_argument("--timeout", type=int, default=2400)
    p.add_argument("--out", default="h3-output")
    args = p.parse_args()
    base = args.url.rstrip("/")

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

    if args.image:
        wf["5"]["inputs"]["image"] = upload_image(base, args.image)
    else:
        del wf["5"]
        del node["first_frame"]

    res = call(f"{base}/prompt", {"prompt": wf, "client_id": uuid.uuid4().hex})
    if "prompt_id" not in res:
        sys.exit(f"submit failed: {json.dumps(res)[:2000]}")
    pid = res["prompt_id"]
    print(f"queued {pid} ({'i2v' if args.image else 't2v'}, length={node['length']}, "
          f"steps={wf['9']['inputs']['steps']})")

    t0 = time.time()
    while True:
        time.sleep(10)
        hist = call(f"{base}/history/{pid}")
        if pid in hist:
            entry = hist[pid]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                sys.exit("execution error:\n" + json.dumps(msgs, indent=1)[:3000])
            if entry.get("outputs"):
                break
        q = call(f"{base}/prompt")
        print(f"  [{int(time.time()-t0):>4}s] queue_remaining="
              f"{q.get('exec_info', {}).get('queue_remaining')}")
        if time.time() - t0 > args.timeout:
            sys.exit("timed out")

    os.makedirs(args.out, exist_ok=True)
    saved = []
    for out in entry["outputs"].values():
        for kind in ("videos", "images", "audio"):
            for item in out.get(kind, []):
                qs = urllib.parse.urlencode({
                    "filename": item["filename"],
                    "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output"),
                })
                blob = call(f"{base}/view?{qs}", raw=True, timeout=300)
                dest = os.path.join(args.out, item["filename"])
                with open(dest, "wb") as f:
                    f.write(blob)
                saved.append((dest, len(blob)))
                print(f"saved {dest} ({len(blob)/1e6:.1f} MB)")
    if not saved:
        sys.exit("completed but no outputs found: " + json.dumps(entry["outputs"])[:1000])
    print(f"done in {int(time.time()-t0)}s")


if __name__ == "__main__":
    main()
