"""把录屏帧目录合成 demo GIF：去重相邻同帧、缩放、控制总时长。

用法：
    python scripts/make_gif.py <frames_dir> <out.gif> [--width 880] [--fps 1.2]
"""
import argparse
from pathlib import Path

from PIL import Image, ImageChops


def frames_identical(a: Image.Image, b: Image.Image, tol: float = 0.001) -> bool:
    """两帧差异比例低于阈值视为同帧（跳过）。"""
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    bbox_ratio = sum(1 for px in diff.getdata() if max(px) > 8) / (a.width * a.height)
    return bbox_ratio < tol


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir")
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=880)
    ap.add_argument("--fps", type=float, default=1.2, help="帧率（演示 GIF 宜慢）")
    args = ap.parse_args()

    paths = sorted(Path(args.frames_dir).glob("*.png"))
    if not paths:
        raise SystemExit(f"无帧：{args.frames_dir}")

    frames, last = [], None
    for p in paths:
        img = Image.open(p).convert("RGB")
        ratio = args.width / img.width
        img = img.resize((args.width, int(img.height * ratio)), Image.LANCZOS)
        if last is None or not frames_identical(img, last):
            frames.append(img)
            last = img
    if len(frames) == 1:
        frames = frames * 2

    duration = int(1000 / args.fps)
    frames[0].save(
        args.out, save_all=True, append_images=frames[1:],
        duration=duration, loop=0, optimize=True,
    )
    print(f"{args.out}: {len(frames)} 帧（原始 {len(paths)} 帧去重）")


if __name__ == "__main__":
    main()
