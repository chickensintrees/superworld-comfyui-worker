# Custom RunPod serverless ComfyUI worker for SUPERWORLD i2v (Wan2.1).
# Base = RunPod's worker-comfyui; add the custom nodes our workflow needs.
# Models come from the attached network volume via extra_model_paths.yaml.
FROM runpod/worker-comfyui:5.1.0-base

RUN cd /comfyui/custom_nodes \
 && git clone --depth 1 https://github.com/kijai/ComfyUI-WanVideoWrapper \
 && git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes \
 && (pip install --no-cache-dir -r ComfyUI-WanVideoWrapper/requirements.txt || true) \
 && (pip install --no-cache-dir -r ComfyUI-KJNodes/requirements.txt || true)

# ComfyUI reads models from the network volume (mounted at /runpod-volume) where
# our provisioning already put them (/runpod-volume/ComfyUI/models/...).
COPY extra_model_paths.yaml /comfyui/extra_model_paths.yaml
