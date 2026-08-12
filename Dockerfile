# Custom RunPod serverless ComfyUI worker for SUPERWORLD video gen
# (Wan2.1 i2v via WanVideoWrapper + MiniMax H3 via native ComfyUI nodes).
FROM runpod/worker-comfyui:5.8.7-base

# MiniMax H3 needs ComfyUI >= 0.30.0 (native nodes landed 2026-08-03); the
# 5.8.7 base pins 0.29.0, so upgrade the comfy-cli checkout in place. torch
# stays as the base image pinned it (2.11.0+cu128) — requirements.txt does
# not move it.
ARG COMFYUI_VERSION=v0.32.0
RUN cd /comfyui \
 && if [ -d .git ]; then \
      git fetch --depth 1 origin tag ${COMFYUI_VERSION} \
      && git checkout ${COMFYUI_VERSION}; \
    else \
      curl -fsSL https://github.com/comfyanonymous/ComfyUI/archive/refs/tags/${COMFYUI_VERSION}.tar.gz \
      | tar xz --strip-components=1; \
    fi \
 && (uv pip install -r requirements.txt \
     || pip install --no-cache-dir -r requirements.txt)

# Latest main (has LoadWanVideoT5TextEncoder) + explicit dep install. The earlier
# comfy-node-install (registry) installed the node without its Python deps, so it
# failed to import on the worker. pip installing requirements fixes that.
RUN cd /comfyui/custom_nodes \
 && git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes \
 && git clone --depth 1 https://github.com/kijai/ComfyUI-WanVideoWrapper \
 && (uv pip install -r ComfyUI-KJNodes/requirements.txt \
     || pip install --no-cache-dir -r ComfyUI-KJNodes/requirements.txt) \
 && (uv pip install -r ComfyUI-WanVideoWrapper/requirements.txt \
     || pip install --no-cache-dir -r ComfyUI-WanVideoWrapper/requirements.txt)

# non-GPU sanity: the nodes ARE defined in the source (can't do a full node
# load here — GH runners have no NVIDIA driver).
RUN grep -rq "LoadWanVideoT5TextEncoder" /comfyui/custom_nodes/ComfyUI-WanVideoWrapper/ \
 && grep -rq "MiniMaxH3ImageToVideo" /comfyui/comfy_extras/ \
 && grep -rq "MiniMaxH3ReferenceToVideo" /comfyui/comfy_extras/ \
 && echo "NODE_SOURCE_OK"

# CPU-only import smoke test: catches dependency breakage from the ComfyUI
# upgrade (the base image ran this against 0.29.0; re-run against ours).
RUN cd /comfyui && timeout 300 python main.py --quick-test-for-ci --cpu

COPY extra_model_paths.yaml /comfyui/extra_model_paths.yaml
