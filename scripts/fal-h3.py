#!/usr/bin/env python3
"""Run MiniMax H3 on fal.ai — the hosted path, no GPU to provision.

Same model as the self-hosted worker, so prompts transfer verbatim. Reads the
key from ~/.claude/config.json ({"fal": {"api_key": "..."}}) or $FAL_KEY.

  python3 scripts/fal-h3.py --prompt-file prompt.txt --duration 5
  python3 scripts/fal-h3.py --prompt "..." --resolution 2K
  python3 scripts/fal-h3.py --prompt "..." --ref-image still.png   # ref2va

Pricing (per fal, Aug 2026): $0.08/s at 768P, $0.13/s at 2K, $0.16/s at 4K;
first 5 reference images free. A 5 s 768P clip is ~$0.40 — the script prints
its own cost estimate before submitting.

Two defaults differ from the self-hosted graph and are pinned here for
comparability: resolution defaults to 2K upstream (we default 768P, matching
the model's native canvas), and enable_prompt_expansion defaults to true
upstream, which silently rewrites the prompt. Pass --expand-prompt to allow it.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

PRICE_PER_SEC = {"768P": 0.08, "2K": 0.13, "4K": 0.16}


def load_key():
    if os.environ.get("FAL_KEY"):
        return os.environ["FAL_KEY"]
    cfg = os.path.expanduser("~/.claude/config.json")
    if os.path.exists(cfg):
        try:
            key = json.load(open(cfg)).get("fal", {}).get("api_key")
            if key:
                return key
        except json.JSONDecodeError:
            pass
    sys.exit("no fal key: set $FAL_KEY or ~/.claude/config.json fal.api_key")


def call(url, key, payload=None, method=None, timeout=120, raw=False):
    headers = {"Authorization": f"Key {key}", "User-Agent": "fal-h3/1.0"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if raw else json.load(r)


def upload(path, key):
    """fal accepts data URIs for reference media, which avoids the storage API."""
    import base64
    import mimetypes
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--prompt")
    g.add_argument("--prompt-file")
    p.add_argument("--duration", type=int, default=5)
    p.add_argument("--resolution", default="768P", choices=["768P", "2K", "4K"])
    p.add_argument("--aspect-ratio", default="16:9")
    p.add_argument("--seed", type=int)
    p.add_argument("--ref-image", action="append", default=[],
                   help="reference image for ref2va (repeatable, up to 9)")
    p.add_argument("--image", help="first frame for image-to-video")
    p.add_argument("--expand-prompt", action="store_true",
                   help="let fal rewrite the prompt (upstream default; off here)")
    p.add_argument("--out", default="fal-output")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    args = p.parse_args()

    key = load_key()
    prompt = args.prompt or open(args.prompt_file).read()

    if args.ref_image:
        endpoint = "minimax/h3/reference-to-video"
    elif args.image:
        endpoint = "minimax/h3/image-to-video"
    else:
        endpoint = "minimax/h3/text-to-video"

    payload = {
        "prompt": prompt,
        "duration": args.duration,
        "resolution": args.resolution,
        "aspect_ratio": args.aspect_ratio,
        "enable_prompt_expansion": bool(args.expand_prompt),
    }
    if args.seed is not None:
        payload["seed"] = args.seed
    if args.image:
        payload["image_url"] = upload(args.image, key)
    if args.ref_image:
        payload["reference_image_urls"] = [upload(p_, key) for p_ in args.ref_image]

    est = PRICE_PER_SEC[args.resolution] * args.duration
    extra_refs = max(0, len(args.ref_image) - 5)
    est += extra_refs * 0.08
    print(f"endpoint : {endpoint}")
    print(f"settings : {args.duration}s @ {args.resolution} {args.aspect_ratio}, "
          f"prompt_expansion={'on' if args.expand_prompt else 'off'}")
    print(f"estimate : ${est:.2f}" + (f" (+{extra_refs} paid refs)" if extra_refs else ""))
    if not args.yes:
        if input("submit? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("aborted")

    sub = call(f"https://queue.fal.run/{endpoint}", key, payload)
    rid = sub["request_id"]
    status_url = sub["status_url"]
    print(f"request  : {rid}")

    t0 = time.time()
    while True:
        time.sleep(5)
        try:
            st = call(status_url, key, timeout=60)
        except urllib.error.URLError as e:
            print(f"  (transient: {e})")
            continue
        s = st.get("status")
        if s == "COMPLETED":
            break
        if s in ("FAILED", "CANCELLED", "ERROR"):
            sys.exit(f"job {s}: {json.dumps(st)[:1000]}")
        print(f"  [{int(time.time()-t0):>4}s] {s}")
        if time.time() - t0 > args.timeout:
            sys.exit("timed out")

    res = call(sub["response_url"], key, timeout=120)
    url = (res.get("video") or {}).get("url")
    if not url:
        sys.exit("completed but no video in response: " + json.dumps(res)[:800])

    os.makedirs(args.out, exist_ok=True)
    dest = os.path.join(args.out, f"fal-h3-{rid[:8]}.mp4")
    with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as f:
        f.write(r.read())
    print(f"saved {dest} ({os.path.getsize(dest)/1e6:.1f} MB) in {int(time.time()-t0)}s")


if __name__ == "__main__":
    main()
