#!/usr/bin/env python3
"""Queue a whole batch of MiniMax H3 generations against one warm ComfyUI.

The point: ComfyUI keeps the ~43 GB of H3 weights resident between queued
prompts, so only the FIRST job pays the multi-minute model load. Submitting
ten jobs at once costs one cold start, not ten.

  python3 scripts/h3-batch.py --url https://<podid>-8188.proxy.runpod.net \
      --jobs jobs/example.json --out h3-output

Job file format (see jobs/example.json):

  {
    "defaults": {"length": 124, "steps": 20, "width": 1344, "height": 768},
    "jobs": [
      {"name": "wide-open",  "prompt": "..."},
      {"name": "from-still", "prompt": "...", "first_frame": "stills/a.png"},
      {"name": "char-b",     "mode": "ref2va", "prompt": "<Picture 1> ...",
       "ref_images": ["stills/char.png"], "seed": 7}
    ]
  }

Every job may override any default plus: seed, first_frame, last_frame,
mode ("fl2va" default, or "ref2va"), ref_images, ref_audios, ref_image_size.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

UA = {"User-Agent": "h3-batch/1.0"}  # Cloudflare 403s python-urllib's default UA

MODELS = {
    "fl2va": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "ref2va": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
}
CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"


def call(url, payload=None, timeout=180, raw=False):
    headers = dict(UA)
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if raw else json.load(r)


def upload_image(base, path):
    boundary = uuid.uuid4().hex
    with open(path, "rb") as f:
        data = f.read()
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
        f"filename=\"{os.path.basename(path)}\"\r\nContent-Type: application/octet-stream"
        "\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{base}/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)["name"]


def align_length(n):
    """H3 samples on a 17k+5 frame grid at 24fps; snap up like the node does."""
    n = max(5, int(n))
    while n % 17 != 5:
        n += 1
    return n


def build_graph(job, base, uploaded):
    """Assemble the API-format graph for one job."""
    mode = job.get("mode", "fl2va")
    if mode not in MODELS:
        sys.exit(f"job {job.get('name')!r}: unknown mode {mode!r}")
    length = align_length(job.get("length", 124))
    seed = job.get("seed", 0)

    g = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": MODELS[mode], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIP, "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "7": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": job.get("sampler", "res_multistep")}},
        "9": {"class_type": "BasicScheduler",
              "inputs": {"model": ["1", 0], "scheduler": job.get("scheduler", "simple"),
                         "steps": job.get("steps", 20), "denoise": 1.0}},
        "10": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["6", 0]}},
        "11": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["7", 0], "guider": ["10", 0], "sampler": ["8", 0],
                          "sigmas": ["9", 0], "latent_image": ["6", 1]}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["11", 0], "vae": ["4", 0]}},
        "14": {"class_type": "CreateVideo",
               "inputs": {"images": ["12", 0], "audio": ["13", 0], "fps": 24}},
        "15": {"class_type": "SaveVideo",
               "inputs": {"video": ["14", 0],
                          "filename_prefix": "video/" + job.get("name", "h3"),
                          "format": "auto", "codec": "auto"}},
    }

    cond = {
        "clip": ["2", 0], "vae": ["3", 0], "prompt": job["prompt"],
        "width": job.get("width", 1344), "height": job.get("height", 768),
        "length": length,
    }

    def image_node(path):
        """Upload once per run, reuse the LoadImage node id."""
        if path not in uploaded:
            name = upload_image(base, path)
            nid = str(100 + len(uploaded))
            uploaded[path] = (nid, name)
            g[nid] = {"class_type": "LoadImage", "inputs": {"image": name}}
        else:
            nid, name = uploaded[path]
            g.setdefault(nid, {"class_type": "LoadImage", "inputs": {"image": name}})
        return [uploaded[path][0], 0]

    if mode == "fl2va":
        node_type = "MiniMaxH3ImageToVideo"
        for key in ("first_frame", "last_frame"):
            if job.get(key):
                cond[key] = image_node(job[key])
    else:
        node_type = "MiniMaxH3ReferenceToVideo"
        cond["audio_vae"] = ["4", 0]
        cond["ref_image_size"] = job.get("ref_image_size", "match")
        # Autogrow (COMFY_AUTOGROW_V3) sockets arrive as ONE nested dict keyed
        # by prefixed socket name -- the node's execute() takes `ref_images` and
        # iterates .values(). Flat `ref_image_0` inputs pass validation but blow
        # up at execution with "unexpected keyword argument".
        refs = {f"ref_image_{i}": image_node(p)
                for i, p in enumerate(job.get("ref_images", []))}
        if refs:
            cond["ref_images"] = refs

    g["6"] = {"class_type": node_type, "inputs": cond}
    return g, length


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True, help="ComfyUI base URL")
    p.add_argument("--jobs", required=True, help="job spec JSON")
    p.add_argument("--out", default="h3-output")
    p.add_argument("--timeout", type=int, default=14400, help="overall budget, seconds")
    args = p.parse_args()
    base = args.url.rstrip("/")

    spec = json.load(open(args.jobs))
    defaults = spec.get("defaults", {})
    jobs = [{**defaults, **j} for j in spec["jobs"]]
    if not jobs:
        sys.exit("no jobs in spec")

    os.makedirs(args.out, exist_ok=True)
    uploaded = {}
    queued = []
    for i, job in enumerate(jobs):
        name = job.get("name") or f"job{i}"
        job["name"] = name
        try:
            graph, length = build_graph(job, base, uploaded)
        except (OSError, KeyError) as e:
            print(f"!! {name}: skipped ({e})")
            continue
        res = call(f"{base}/prompt", {"prompt": graph, "client_id": uuid.uuid4().hex})
        if "prompt_id" not in res:
            print(f"!! {name}: rejected {json.dumps(res)[:400]}")
            continue
        queued.append((res["prompt_id"], name))
        print(f"queued {name}  ({job.get('mode','fl2va')}, {length}f, "
              f"{job.get('steps',20)} steps, seed {job.get('seed',0)})")

    if not queued:
        sys.exit("nothing queued")
    print(f"\n{len(queued)} jobs queued — model loads once, then they run back to back.\n")

    pending = dict(queued)
    t0 = time.time()
    done = 0
    while pending and time.time() - t0 < args.timeout:
        time.sleep(15)
        for pid in list(pending):
            name = pending[pid]
            try:
                hist = call(f"{base}/history/{pid}", timeout=60)
            except urllib.error.URLError as e:
                print(f"  (transient: {e})")
                break
            if pid not in hist:
                continue
            entry = hist[pid]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                print(f"!! {name} FAILED: {json.dumps(msgs)[:600]}")
                del pending[pid]
                continue
            if not entry.get("outputs"):
                continue
            for out in entry["outputs"].values():
                for kind in ("videos", "images", "audio"):
                    for item in out.get(kind, []):
                        qs = urllib.parse.urlencode({
                            "filename": item["filename"],
                            "subfolder": item.get("subfolder", ""),
                            "type": item.get("type", "output")})
                        blob = call(f"{base}/view?{qs}", raw=True, timeout=600)
                        dest = os.path.join(args.out, item["filename"])
                        with open(dest, "wb") as f:
                            f.write(blob)
                        print(f"[{int(time.time()-t0):>5}s] {name} -> {dest} "
                              f"({len(blob)/1e6:.1f} MB)")
            del pending[pid]
            done += 1
        if pending:
            # The pod proxy 502s while ComfyUI restarts; a status poll must
            # never kill the run, since the jobs outlive this client.
            try:
                q = call(f"{base}/prompt", timeout=60)
                remaining = q.get("exec_info", {}).get("queue_remaining")
            except (urllib.error.URLError, OSError) as e:
                remaining = f"unknown ({e})"
            print(f"  [{int(time.time()-t0):>5}s] {done}/{len(queued)} done, "
                  f"queue_remaining={remaining}")

    if pending:
        print(f"\ntimed out with {len(pending)} unfinished: {list(pending.values())}")
        sys.exit(1)
    failed = len(queued) - done
    print(f"\n{done}/{len(queued)} jobs produced output in {int(time.time()-t0)}s -> {args.out}/")
    if failed:
        sys.exit(f"{failed} job(s) failed")


if __name__ == "__main__":
    main()
