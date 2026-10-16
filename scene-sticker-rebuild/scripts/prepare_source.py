#!/usr/bin/env python3
"""Create a project: copy the source, convert it to sRGB through its embedded ICC
profile (CMYK print files included), and render gridded preview tiles whose labels
are full-resolution pixel coordinates (used to write SAM prompts and plan boxes).

  python prepare_source.py --project projects/20261012_shop --source /path/art.jpg
"""
import argparse
import io
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageDraw

from common import Project, font, write_json

Image.MAX_IMAGE_PIXELS = None


def to_srgb(im: Image.Image) -> tuple[Image.Image, str]:
    icc = im.info.get("icc_profile")
    if icc:
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        desc = ImageCms.getProfileDescription(src).strip()
        out = ImageCms.profileToProfile(im, src, ImageCms.createProfile("sRGB"),
                                        renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                                        outputMode="RGB", flags=ImageCms.Flags.BLACKPOINTCOMPENSATION)
        return out, f"converted from embedded profile: {desc}"
    if im.mode == "CMYK":
        return im.convert("RGB"), "CMYK without profile: naive conversion, check colours"
    return im.convert("RGB"), "no profile: assumed sRGB"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--tile-px", type=int, default=1200, help="preview tile size in screen pixels")
    a = ap.parse_args()
    P = Project(a.project)
    P.p("source", "grid").mkdir(parents=True, exist_ok=True)
    src = Path(a.source)
    shutil.copy2(src, P.p("source", "original" + src.suffix.lower()))
    im = Image.open(src)
    mode, size = im.mode, im.size
    rgb, note = to_srgb(im)
    rgb.save(P.source)

    W, H = size
    step = max(50, int(round(max(W, H) / 50 / 50.0)) * 50)        # grid line spacing in source px
    scale = max(1, int(round(max(W, H) / (2.5 * a.tile_px))))     # ~2-3 tiles across
    small = rgb.resize((W // scale, H // scale), Image.LANCZOS)
    tw = a.tile_px * scale
    ov = int(tw * 0.1)
    xs = list(range(0, max(1, W - ov), tw - ov)) or [0]
    ys = list(range(0, max(1, H - ov), tw - ov)) or [0]
    f = font(max(12, a.tile_px // 60))
    tiles = []
    for r, y0 in enumerate(ys):
        for c, x0 in enumerate(xs):
            x1, y1 = min(W, x0 + tw), min(H, y0 + tw)
            t = small.crop((x0 // scale, y0 // scale, x1 // scale, y1 // scale)).convert("RGB")
            d = ImageDraw.Draw(t)
            for X in range((x0 // step + 1) * step, x1, step):
                major = X % (step * 5) == 0
                d.line([((X - x0) / scale, 0), ((X - x0) / scale, t.height)], fill=(255, 0, 0) if major else (90, 170, 255))
                if major:
                    d.text(((X - x0) / scale + 3, 3), str(X), fill=(255, 0, 0), font=f)
            for Y in range((y0 // step + 1) * step, y1, step):
                major = Y % (step * 5) == 0
                d.line([(0, (Y - y0) / scale), (t.width, (Y - y0) / scale)], fill=(255, 0, 0) if major else (90, 170, 255))
                if major:
                    d.text((3, (Y - y0) / scale + 3), str(Y), fill=(255, 0, 0), font=f)
            name = f"r{r}c{c}.jpg"
            t.save(P.p("source", "grid", name), quality=88)
            tiles.append({"file": name, "box": [x0, y0, x1, y1]})
    small.save(P.p("source", "preview.jpg"), quality=88)
    # whole-picture overview with labelled major grid lines (first look, element inventory)
    k = max(W, H) / 1600
    ov = rgb.resize((int(W / k), int(H / k)), Image.LANCZOS)
    d = ImageDraw.Draw(ov)
    major = step * 5 if max(W, H) / (step * 5) <= 30 else step * 10
    for X in range(major, W, major):
        d.line([(X / k, 0), (X / k, ov.height)], fill=(255, 0, 0)); d.text((X / k + 3, 3), str(X), fill=(255, 0, 0), font=f)
    for Y in range(major, H, major):
        d.line([(0, Y / k), (ov.width, Y / k)], fill=(255, 0, 0)); d.text((3, Y / k + 3), str(Y), fill=(255, 0, 0), font=f)
    ov.save(P.p("source", "overview_grid.jpg"), quality=88)
    write_json(P.p("source", "info.json"), {"size": [W, H], "mode": mode, "colour": note,
                                            "grid_step": step, "preview_scale": scale, "tiles": tiles})
    # the workflow marks hidden areas in flat magenta; warn if the artwork itself uses it
    sm = np.asarray(small, dtype=np.int16)
    key_like = ((sm[..., 0] > 200) & (sm[..., 2] > 200) & (sm[..., 1] < 80)).mean()
    if key_like > 0.001:
        print(f"WARNING: {key_like:.2%} of the picture is close to magenta (255,0,255), the colour used to mark "
              "hidden areas; check generated stickers for confusion, or change MAGENTA in common.py and the "
              "word 'magenta' in the prompt templates to an unused colour")
    print(f"{W}x{H} {mode}; {note}; {len(tiles)} grid tiles, grid step {step}px")


if __name__ == "__main__":
    main()
