#!/usr/bin/env python3
"""Pull stills out of a generated clip, to reuse as H3 references or keyframes.

Two jobs in the music-video pipeline need this:
  - character consistency: grab a frame of a character, feed it to ref2va
    as <Picture 1> so the next shot keeps the same face/wardrobe
  - shot chaining: take a clip's last frame and pass it as the next clip's
    first_frame, so cuts continue rather than restart

  python3 scripts/extract-ref.py clip.mp4 --frame 60 --out ref.png
  python3 scripts/extract-ref.py clip.mp4 --last  --out tail.png
  python3 scripts/extract-ref.py clip.mp4 --every 24 --out-dir stills/
"""
import argparse
import os
import sys

try:
    import imageio.v3 as iio
except ImportError:
    sys.exit("needs: pip install imageio imageio-ffmpeg av")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("--frame", type=int, help="single frame index (0-based)")
    p.add_argument("--last", action="store_true", help="final frame")
    p.add_argument("--every", type=int, help="every Nth frame")
    p.add_argument("--out", help="output png (single-frame modes)")
    p.add_argument("--out-dir", help="output directory (--every)")
    args = p.parse_args()

    frames = iio.imread(args.video, plugin="pyav")
    total = len(frames)
    print(f"{args.video}: {total} frames, {frames.shape[2]}x{frames.shape[1]}")

    if args.every:
        out_dir = args.out_dir or "stills"
        os.makedirs(out_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(args.video))[0]
        for i in range(0, total, args.every):
            dest = os.path.join(out_dir, f"{stem}-f{i:04d}.png")
            iio.imwrite(dest, frames[i])
            print(f"  {dest}")
        return

    idx = total - 1 if args.last else (args.frame if args.frame is not None else total // 2)
    if not 0 <= idx < total:
        sys.exit(f"frame {idx} out of range (0..{total-1})")
    dest = args.out or f"frame-{idx:04d}.png"
    iio.imwrite(dest, frames[idx])
    print(f"wrote {dest} (frame {idx})")


if __name__ == "__main__":
    main()
