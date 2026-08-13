# superworld-comfyui-worker
Custom RunPod serverless ComfyUI worker for SUPERWORLD video generation:
- **Wan2.1-I2V-14B** via WanVideoWrapper + KJNodes (original pipeline)
- **MiniMax H3** (open-weights omni-modal video+audio, Aug 2026) via ComfyUI's
  native nodes — t2v, i2v/first-last-frame, and ref2va

Base `runpod/worker-comfyui:5.8.6-base-cuda12.8.1` with ComfyUI upgraded to v0.32.0
(H3 nodes need >= 0.30.0). Models load from the attached network volume
(`superworld-models` / `5zhfcq5im7`, US-TX-3, 60 GB) via `extra_model_paths.yaml`.
(The old volume `uyd3wn4j15` is gone — US-WA-1 no longer offers storage.)
Built by GitHub Actions → `ghcr.io/<owner>/superworld-comfyui-worker:latest`
(`main` only; `claude/**` branches push a sha-tagged image for testing).

## MiniMax H3

### One-time: models onto the network volume (~43 GB)

Start any cheap pod in US-TX-3 with volume `5zhfcq5im7` attached and run:

```bash
bash scripts/download-h3-models.sh              # fl2va: t2v + i2v (~43 GB)
bash scripts/download-h3-models.sh --ref2va     # + reference-to-video (+21 GB, needs a >=70 GB volume)
```

Smallest published variants from `Comfy-Org/MiniMax-H3`:
int8 DiT (21 GB) + nvfp4 Qwen3-VL-32B encoder (15.7 GB) + video/audio VAEs (5.8 GB).

### Endpoint GPU

~43 GB of weights with ComfyUI's dynamic offloading: 48 GB VRAM (L40S/A6000)
works; 80 GB (A100/H100) gives headroom for 2K/15s runs. Native output is
768px short edge, 24 fps, up to ~15 s, with 32 kHz stereo audio in the mp4.

### Test

Serverless endpoint: `minimax-h3` (`vw3tyxi0ua5374`), volume attached, 48 GB GPUs.

```bash
export RUNPOD_API_KEY=...       # from runpod.io settings
export RUNPOD_ENDPOINT_ID=vw3tyxi0ua5374
python3 scripts/test-h3.py --image still.png            # i2v from a still
python3 scripts/test-h3.py                              # t2v
python3 scripts/test-h3.py --length 56 --steps 8        # cheap smoke test
```

Or against a pod / local ComfyUI directly (no serverless layer):

```bash
python3 scripts/test-h3-comfy-http.py --url https://<podid>-8188.proxy.runpod.net --length 56 --steps 8
```

### Batch queue (preferred — avoids repeated cold starts)

The expensive part of an H3 run is loading ~43 GB of weights, not sampling.
ComfyUI keeps them resident between queued prompts, so submit the whole
batch at once and only the first job pays:

```bash
python3 scripts/h3-batch.py --url https://<podid>-8188.proxy.runpod.net \
    --jobs jobs/example.json --out h3-output
```

Each job may set `mode` (`fl2va` default, or `ref2va`), `prompt`, `seed`,
`length`, `steps`, `width`/`height`, `first_frame`/`last_frame`, and for
ref2va `ref_images` (up to 9) + `ref_image_size` (`match` | `max`).
Off-grid `length` values are snapped up to the 17k+5 frame grid.

### Character consistency (ref2va)

Reference media is addressed in the prompt by 1-based ordinal per type —
`<Picture 1>`, `<Video 1>`, `<Audio 1>` — and the model matches identity,
wardrobe, motion or voice from it. Up to 9 images, 3 videos, 3 audio clips.
`ref_image_size: "max"` uses the 2048px reference pipeline for the best
identity fidelity, at the cost of speed (reference tokens ride through
every sampling step).

Pull a character still out of a clip you already generated, then reuse it:

```bash
python3 scripts/extract-ref.py h3-output/cartoon-dinner.mp4 --frame 60 --out stills/cartoon-family.png
python3 scripts/h3-batch.py --url <comfy-url> --jobs jobs/ref2va-consistency.json
```

The same extractor does shot chaining — `--last` gives you a clip's final
frame to pass as the next shot's `first_frame` so cuts continue instead of
restarting. Note ref2va is a *separate 21 GB DiT*; alternating fl2va and
ref2va jobs in one queue forces a model swap, so group them by mode.

### Capacity note

Network volumes are datacenter-locked, so the models can only be used by a
GPU in **US-TX-3**. 48 GB-class stock there is intermittent; when it is dry,
both pods and the serverless endpoint simply wait. Grab a pod when one frees
up and keep it warm for the whole batch rather than starting per clip.

Verified 2026-08-13 on an L40S (US-TX-3): t2v 56f/8 steps in ~8 min cold
(incl. full model load), 124f/20 steps in ~11 min warm; output 1344x768
h264 + stereo AAC. Pod-mode note: the image's default `/start.sh` runs the
serverless handler, which exits outside serverless ("test_input.json not
found") and crash-loops the pod — override the entrypoint to launch
`python /comfyui/main.py --listen 0.0.0.0 --port 8188` after the model
download (see scripts/download-h3-models.sh header).

`workflows/minimax-h3-i2v.json` is the API-format graph (mirrors the official
Comfy template: res_multistep / simple / 20 steps / BasicGuider, no CFG).
`length` is a 24 fps frame count on the model's 17k+5 grid (56≈2.3s, 124≈5.2s,
362≈15s). Prompts can include an `Audio:` line and a `[0s-2s]`-style timeline.

## Wan2.1 (original pipeline)

See `../psuedo-videos/runpod/` for the client + workflow.
