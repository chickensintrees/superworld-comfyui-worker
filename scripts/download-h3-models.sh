#!/usr/bin/env bash
# Download MiniMax H3 models onto the RunPod network volume (uyd3wn4j15).
#
# Run this ON A RUNPOD POD with the network volume attached (pods mount it at
# /workspace; serverless workers see the same volume at /runpod-volume):
#
#   bash download-h3-models.sh                 # fl2va set (~43 GB): t2v + i2v
#   bash download-h3-models.sh --ref2va        # also ref2va DiT (+21 GB)
#   bash download-h3-models.sh --base /runpod-volume/ComfyUI
#
# Files are the smallest published variants (Comfy-Org/MiniMax-H3, public —
# no HF token needed). wget -c makes every download resumable.
set -euo pipefail

BASE="/workspace/ComfyUI"
WANT_REF2VA=0
while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="$2"; shift 2 ;;
    --ref2va) WANT_REF2VA=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

HF="https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main"

# path-on-volume  |  url  |  expected min size (bytes, sanity floor)
FILES=(
  "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors|$HF/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors|20000000000"
  "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors|$HF/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors|15000000000"
  "vae/minimax_h3_video_vae_fp16.safetensors|$HF/vae/minimax_h3_video_vae_fp16.safetensors|5000000000"
  "vae/minimax_h3_audio_vae_fp32.safetensors|$HF/vae/minimax_h3_audio_vae_fp32.safetensors|600000000"
)
if [ "$WANT_REF2VA" = 1 ]; then
  FILES+=("diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors|$HF/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors|20000000000")
fi

echo "Volume free space:"
df -h "$BASE" 2>/dev/null || df -h "$(dirname "$BASE")"

for entry in "${FILES[@]}"; do
  rel="${entry%%|*}"; rest="${entry#*|}"
  url="${rest%%|*}"; min_size="${rest#*|}"
  dest="$BASE/models/$rel"
  mkdir -p "$(dirname "$dest")"
  echo "==> $rel"
  wget -c -q --show-progress -O "$dest" "$url"
  actual=$(stat -c%s "$dest")
  if [ "$actual" -lt "$min_size" ]; then
    echo "ERROR: $dest is $actual bytes, expected >= $min_size (truncated download?)" >&2
    exit 1
  fi
done

echo
echo "All MiniMax H3 models in place under $BASE/models/:"
ls -lh "$BASE/models/diffusion_models" "$BASE/models/text_encoders" "$BASE/models/vae"
