# Custom RunPod serverless ComfyUI worker for SUPERWORLD i2v (Wan2.1).
FROM runpod/worker-comfyui:5.1.0-base

# Latest main (has LoadWanVideoT5TextEncoder) + proper dep install (no masking).
RUN cd /comfyui/custom_nodes \
 && git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes \
 && git clone --depth 1 https://github.com/kijai/ComfyUI-WanVideoWrapper \
 && pip install --no-cache-dir -r ComfyUI-KJNodes/requirements.txt \
 && pip install --no-cache-dir -r ComfyUI-WanVideoWrapper/requirements.txt

# VERIFY the node actually registers — fail the build (and print the import error)
# if not, so a broken image never deploys.
RUN cd /comfyui && python -c "import nodes; nodes.init_extra_nodes(); m=nodes.NODE_CLASS_MAPPINGS; print('TOTAL_NODES', len(m)); print('WANVIDEO_OK', 'LoadWanVideoT5TextEncoder' in m); assert 'LoadWanVideoT5TextEncoder' in m, 'WanVideoWrapper node did not register'"

COPY extra_model_paths.yaml /comfyui/extra_model_paths.yaml
