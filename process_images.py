#!/usr/bin/env python3
"""
批量处理插画素材
  去白底 -> 裁边 -> (可选)放大 -> 保存 300dpi 透明 PNG -> (可选)拼成 Letter/A4 素材页(PNG + PDF)

依赖：pip install pillow numpy
用法示例：
  # 1) 只去底、裁边、写入 300dpi 元数据（不放大）
  python process_images.py 下载内容 out

  # 2) 同时拼成 Letter 尺寸素材页（每个素材最长边不超过 3 英寸）
  python process_images.py 下载内容 out --sheet --page letter --max-inch 3

  # 3) 先用 Real-ESRGAN 命令行放大 2 倍再处理（需要自己安装可执行文件，下面的参数请以其官方说明为准）
  python process_images.py 下载内容 out --scale 2 --realesrgan /path/to/realesrgan-ncnn-vulkan

关于 300dpi：dpi 只是写在文件里的一个数字，真正决定能不能高清打印的是像素数。
  打印尺寸(英寸) = 像素 / 300。1024 像素的图在 300dpi 下只能原生打印到约 3.4 英寸。
  所以不放大的做法是：把素材缩小到 3 英寸以内，排在 2550x3300 的整页画布上（--sheet）。
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

DPI = 300
PAGES = {"letter": (2550, 3300), "a4": (2480, 3508)}
EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MARKER = (255, 0, 255)


def border_is_white(im, thr=235):
    w, h = im.size
    pts = [(2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3),
           (w // 2, 2), (w // 2, h - 3), (2, h // 2), (w - 3, h // 2)]
    return all(min(im.getpixel(p)[:3]) >= thr for p in pts)


def remove_white_bg(im, tol=28, thr=235):
    """只去掉与图片边缘相连的近白背景，素材内部的白色区域会保留。"""
    rgb = im.convert("RGB")
    w, h = rgb.size
    work = rgb.copy()
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
             (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
    for s in seeds:
        px = work.getpixel(s)
        if px != MARKER and min(px) >= thr:
            ImageDraw.floodfill(work, s, MARKER, thresh=tol)
    arr = np.array(work)
    bg = (arr[..., 0] == 255) & (arr[..., 1] == 0) & (arr[..., 2] == 255)
    alpha = Image.fromarray(np.where(bg, 0, 255).astype("uint8"), "L")
    # 收缩 1 像素并轻微羽化，避免白色毛边
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.7))
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def trim(im, pad=6):
    bbox = im.split()[-1].point(lambda a: 255 if a > 10 else 0).getbbox()
    if not bbox:
        return im
    l, t, r, b = bbox
    return im.crop((max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b + pad)))


def upscale(src: Path, scale: int, realesrgan: str | None) -> Image.Image:
    if realesrgan:
        with tempfile.TemporaryDirectory() as td:
            dst = Path(td) / "up.png"
            # 参数以所用版本的说明为准；这里按 ncnn-vulkan 版常见写法
            subprocess.run([realesrgan, "-i", str(src), "-o", str(dst), "-s", str(scale)], check=True)
            return Image.open(dst).convert("RGB")
    im = Image.open(src).convert("RGB")
    return im.resize((im.width * scale, im.height * scale), Image.LANCZOS)  # 仅插值，不会增加细节


def pack_sheets(pieces, outdir: Path, page: str, max_inch: float, margin_in: float, gap_in: float):
    PW, PH = PAGES[page]
    margin, gap = int(margin_in * DPI), int(gap_in * DPI)
    limit = int(max_inch * DPI)
    items = []
    for name, im in pieces:
        s = min(1.0, limit / max(im.size))  # 只缩小，不放大
        if s < 1.0:
            im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
        items.append((name, im))
    items.sort(key=lambda t: t[1].height, reverse=True)

    pages, cur = [], Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    x, y, row_h = margin, margin, 0
    for name, im in items:
        if x + im.width > PW - margin:
            x, y, row_h = margin, y + row_h + gap, 0
        if y + im.height > PH - margin:
            pages.append(cur)
            cur = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
            x, y, row_h = margin, margin, 0
        cur.alpha_composite(im, (x, y))
        x += im.width + gap
        row_h = max(row_h, im.height)
    pages.append(cur)

    paths = []
    for i, pg in enumerate(pages, 1):
        p = outdir / f"sheet_{i:02d}.png"
        pg.save(p, dpi=(DPI, DPI))
        paths.append(p)
    white = []
    for pg in pages:
        bg = Image.new("RGB", pg.size, (255, 255, 255))
        bg.paste(pg, mask=pg.split()[-1])
        white.append(bg)
    white[0].save(outdir / "sheets.pdf", save_all=True, append_images=white[1:], resolution=DPI)
    return paths


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("indir")
    ap.add_argument("outdir")
    ap.add_argument("--scale", type=int, default=1, help="放大倍数，默认 1（不放大）")
    ap.add_argument("--realesrgan", default=None, help="Real-ESRGAN 可执行文件路径（可选）")
    ap.add_argument("--tol", type=int, default=28, help="去白底容差，默认 28；边缘有残留就调大，素材被吃掉就调小")
    ap.add_argument("--white-thr", type=int, default=235, help="判定“白底”的最低亮度，默认 235；背景偏灰白时可调到 215 左右")
    ap.add_argument("--sheet", action="store_true", help="拼成整页素材页")
    ap.add_argument("--page", choices=PAGES.keys(), default="letter")
    ap.add_argument("--max-inch", type=float, default=3.0, help="拼页时每个素材最长边的英寸数，默认 3")
    ap.add_argument("--margin-in", type=float, default=0.4)
    ap.add_argument("--gap-in", type=float, default=0.15)
    a = ap.parse_args()

    indir, outdir = Path(a.indir), Path(a.outdir)
    (outdir / "cutouts").mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in indir.iterdir() if p.suffix.lower() in EXTS and not p.name.startswith("."))
    pieces, skipped = [], []
    print(f"{'文件':<42}{'原始':>12}{'处理后':>12}{'300dpi原生打印尺寸':>22}")
    for f in files:
        base = upscale(f, a.scale, a.realesrgan) if a.scale > 1 else Image.open(f).convert("RGB")
        if not border_is_white(base, a.white_thr):
            skipped.append(f.name)
            im = base.convert("RGBA")
            note = "（背景不是白色，未去底）"
        else:
            im = trim(remove_white_bg(base, a.tol, a.white_thr))
            note = ""
        out = outdir / "cutouts" / (f.stem[:60] + ".png")
        im.save(out, dpi=(DPI, DPI))
        pieces.append((f.stem, im))
        o = Image.open(f).size
        print(f"{f.name[:40]:<42}{str(o):>12}{str(im.size):>12}{im.width / DPI:>10.1f} x {im.height / DPI:.1f} in {note}")
    if a.sheet:
        paths = pack_sheets(pieces, outdir, a.page, a.max_inch, a.margin_in, a.gap_in)
        print(f"\n已生成 {len(paths)} 张整页素材页和 sheets.pdf（{a.page}，{PAGES[a.page][0]}x{PAGES[a.page][1]} 像素 @300dpi）")
    if skipped:
        print("\n以下文件背景不是白色，需要人工处理：", *skipped, sep="\n  ")


if __name__ == "__main__":
    main()
