#!/usr/bin/env python3
"""Review sheets. Look at every sheet; metrics never replace a visual check.

  inputs    contact sheet of all input_target.png: magenta must cover exactly what is
            hidden; wrong occluders, missing parts (ears, tails) and leaks show up here
  stickers  original crop next to each finished sticker (identity, colours, pose,
            completeness, no invented holes or extra objects)
  hotspots  the areas where recompose/recompose.png differs most from the original

  python qa_sheets.py --project P inputs|stickers|hotspots
Writes qa/<mode>_N.jpg.
"""
import argparse

import numpy as np
from PIL import Image, ImageDraw

from common import Project, font, load_rgb


def grid(cells, cols, cw, ch):
    rows = (len(cells) + cols - 1) // cols
    s = Image.new("RGB", (cols * (cw + 6), rows * (ch + 6)), "white")
    for i, c in enumerate(cells):
        s.paste(c, ((i % cols) * (cw + 6), (i // cols) * (ch + 6)))
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("mode", choices=["inputs", "stickers", "hotspots"])
    ap.add_argument("--per-sheet", type=int, default=24)
    a = ap.parse_args()
    P = Project(a.project)
    q = P.p("qa")
    q.mkdir(exist_ok=True)
    f = font(16)
    names = [e["name"] for e in P.elements()]
    labels = {e["name"]: e.get("label", e["name"]) for e in P.elements()}

    if a.mode == "inputs":
        cells = []
        for n in names:
            p = P.sticker_dir(n) / "input_target.png"
            if not p.exists():
                continue
            im = Image.open(p).convert("RGB"); im.thumbnail((300, 300))
            c = Image.new("RGB", (300, 322), "white"); c.paste(im, ((300 - im.width) // 2, 22))
            ImageDraw.Draw(c).text((4, 2), labels[n], fill=(0, 0, 0), font=f); cells.append(c)
        for k in range(0, len(cells), a.per_sheet):
            grid(cells[k:k + a.per_sheet], 6, 300, 322).save(q / f"inputs_{k // a.per_sheet}.jpg", quality=85)
    elif a.mode == "stickers":
        cells = []
        for n in names:
            d = P.sticker_dir(n)
            if not (d / "sticker.png").exists():
                continue
            o = Image.open(d / "crop_full.png").convert("RGB"); r = Image.open(d / "sticker.png")
            bb = r.getbbox() or (0, 0, r.width, r.height)
            g = Image.new("RGBA", r.size, (150, 150, 150, 255)); g.alpha_composite(r)
            pair = [o.crop(bb), g.convert("RGB").crop(bb)]
            H = 220
            pair = [p.resize((max(1, int(p.width * H / p.height)), H)) for p in pair]
            wsum = pair[0].width + pair[1].width + 4
            if wsum > 520:
                k = 520 / wsum; pair = [p.resize((max(1, int(p.width * k)), max(1, int(H * k)))) for p in pair]
            c = Image.new("RGB", (520, H + 22), "white")
            x = (520 - (pair[0].width + pair[1].width + 4)) // 2
            c.paste(pair[0], (x, 22)); c.paste(pair[1], (x + pair[0].width + 4, 22))
            ImageDraw.Draw(c).text((4, 2), labels[n], fill=(0, 0, 0), font=f); cells.append(c)
        for k in range(0, len(cells), a.per_sheet):
            grid(cells[k:k + a.per_sheet], 4, 520, 242).save(q / f"stickers_{k // a.per_sheet}.jpg", quality=85)
    else:
        o = load_rgb(P.source); r = load_rgb(P.p("recompose", "recompose.png"))
        d = (np.abs(o.astype(np.int16) - r.astype(np.int16)).max(2) > 48).astype(np.float32)
        H, W = d.shape
        B = max(300, min(W, H) // 15)
        scores = sorted(((d[y:y + B, x:x + B].mean(), x, y) for y in range(0, H - B, B // 2) for x in range(0, W - B, B // 2)), reverse=True)
        picked = []
        for s, x, y in scores:
            if all(abs(x - px) >= B or abs(y - py) >= B for _, px, py in picked):
                picked.append((s, x, y))
            if len(picked) == 8:
                break
        cells = []
        for s, x, y in picked:
            c = Image.new("RGB", (730, 382), "white")
            c.paste(Image.fromarray(o[y:y + B, x:x + B]).resize((360, 360)), (0, 22))
            c.paste(Image.fromarray(r[y:y + B, x:x + B]).resize((360, 360)), (370, 22))
            ImageDraw.Draw(c).text((4, 2), f"original | recompose  at ({x},{y})  diff {s:.2f}", fill=(0, 0, 0), font=f)
            cells.append(c)
        grid(cells, 2, 730, 382).save(q / "hotspots_0.jpg", quality=85)
    print("written to", q)


if __name__ == "__main__":
    main()
