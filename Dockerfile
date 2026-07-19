# Custom RunPod serverless ComfyUI worker for SUPERWORLD i2v (Wan2.1).
# Base = RunPod's worker-comfyui; add custom nodes via the supported installer
# (comfy-node-install handles the /comfyui/custom_nodes path + Python deps).
# Models come from the attached network volume via extra_model_paths.yaml.
FROM runpod/worker-comfyui:5.1.0-base

RUN comfy-node-install ComfyUI-WanVideoWrapper comfyui-kjnodes

# ComfyUI (at /comfyui) reads this on launch; points it at the volume models
# (mounted at /runpod-volume) where provisioning put them.
COPY extra_model_paths.yaml /comfyui/extra_model_paths.yaml
