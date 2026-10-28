"""网页版调用的核心流程：输入 [(文件名, 字节)]，输出结果 zip、处理明细和缩略预览。"""
from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

from process_images import DPI, border_is_white, pack_sheets, remove_white_bg, trim

PARCHMENT = (236, 226, 206)


def _unique_stem(name: str, used: set) -> str:
    base = (Path(name).stem[:60] or "image").replace("/", "_")
    stem, i = base, 1
    while stem in used:
        i += 1
        stem = f"{base}_{i}"
    used.add(stem)
    return stem


def _preview(im: Image.Image, max_side: int) -> Image.Image:
    """缩略图：放在纸色背景上，方便看透明边缘有没有毛边。"""
    t = im.convert("RGBA")
    t.thumbnail((max_side, max_side), Image.LANCZOS)
    bg = Image.new("RGB", t.size, PARCHMENT)
    bg.paste(t, mask=t.split()[-1])
    return bg


def process_files(files, tol=28, white_thr=235, sheet=True, page="letter",
                  max_inch=3.0, margin_in=0.4, gap_in=0.15):
    used, pieces, rows, skipped = set(), [], [], []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "cutouts").mkdir()
        for name, data in files:
            try:
                base = Image.open(io.BytesIO(data)).convert("RGB")
            except Exception as e:  # 损坏或不支持的文件
                rows.append({"文件": name, "状态": f"无法读取：{e}"})
                continue
            stem = _unique_stem(name, used)
            if border_is_white(base, white_thr):
                im, status = trim(remove_white_bg(base, tol, white_thr)), "已去底"
            else:
                im, status = base.convert("RGBA"), "背景不是白色，未去底"
                skipped.append(name)
            im.save(td / "cutouts" / f"{stem}.png", dpi=(DPI, DPI))
            pieces.append((stem, im))
            rows.append({
                "文件": name, "状态": status,
                "原始像素": f"{base.width}x{base.height}",
                "处理后像素": f"{im.width}x{im.height}",
                "300dpi原生打印(英寸)": f"{im.width / DPI:.1f} x {im.height / DPI:.1f}",
            })
        sheet_previews = []
        if sheet and pieces:
            for p in pack_sheets(pieces, td, page, max_inch, margin_in, gap_in):
                with Image.open(p) as sp:
                    sheet_previews.append(_preview(sp, 900))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(td.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(td))
        piece_previews = [(s, _preview(im, 260)) for s, im in pieces]
    return {"zip": buf.getvalue(), "rows": rows, "skipped": skipped,
            "pieces": piece_previews, "sheets": sheet_previews}
