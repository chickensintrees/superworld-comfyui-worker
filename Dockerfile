# Custom RunPod serverless ComfyUI worker for SUPERWORLD i2v (Wan2.1).
FROM runpod/worker-comfyui:5.1.0-base

# Latest main (has LoadWanVideoT5TextEncoder) + explicit dep install. The earlier
# comfy-node-install (registry) installed the node without its Python deps, so it
# failed to import on the worker. pip installing requirements fixes that.
RUN cd /comfyui/custom_nodes \
 && git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes \
 && git clone --depth 1 https://github.com/kijai/ComfyUI-WanVideoWrapper \
 && pip install --no-cache-dir -r ComfyUI-KJNodes/requirements.txt \
 && pip install --no-cache-dir -r ComfyUI-WanVideoWrapper/requirements.txt

# non-GPU sanity: the node IS defined in the cloned source (can't do a full node
# load here — GH runners have no NVIDIA driver).
RUN grep -rq "LoadWanVideoT5TextEncoder" /comfyui/custom_nodes/ComfyUI-WanVideoWrapper/ \
 && echo "NODE_SOURCE_OK"

COPY extra_model_paths.yaml /comfyui/extra_model_paths.yaml
