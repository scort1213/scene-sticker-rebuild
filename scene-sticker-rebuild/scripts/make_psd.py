#!/usr/bin/env python3
"""Write the layered PSD deliverable (memory-light: every layer is stored at its own
bounding box, RLE-compressed; full-canvas layers are only the board and the reference).

Layer stack, bottom to top:
  原图（参考）   the source in sRGB, hidden - for checking positions, not for printing
  底板           board/state.png
  stickers       in the stacking order of recompose/layout.json (back to front),
                 named like the PNG files; each layer sits at its original position
  front pieces   only if recompose.py was run with --front-pieces
The merged image (what viewers show without rendering layers) is recompose/recompose.png.

  python make_psd.py --project P [--out deliver/拆分分层.psd]
export.py calls this at the end; it reads deliver/摆放位置.json and deliver/贴纸/.
"""
import argparse
import json
import time

import numpy as np
from PIL import Image
from psd_tools import PSDImage
from psd_tools.api.layers import PixelLayer
from psd_tools.constants import Compression

from common import Project

Image.MAX_IMAGE_PIXELS = None


def build_psd(P, out="deliver/拆分分层.psd", reference=True):
    D = P.p("deliver")
    place = json.loads((D / "摆放位置.json").read_text(encoding="utf-8"))
    W, H = place["image_size"]
    t0 = time.time()
    # RGBA document: layer alpha is stored as real layer transparency (an RGB document
    # would turn it into a layer mask and the pixels themselves would be opaque)
    psd = PSDImage.new("RGBA", (W, H))

    def add(img, name, left=0, top=0, visible=True):
        layer = PixelLayer.frompil(img.convert("RGBA"), psd, "layer", top, left, Compression.RLE)
        layer.name = name          # setter: legacy ASCII name + Unicode name (Chinese names)
        layer.visible = visible
        psd.append(layer)

    if reference:
        add(Image.open(P.source), "原图（参考）", visible=False)
    add(Image.open(D / "底板.png"), "底板")
    for name in place["order_back_to_front"]:
        s = place["stickers"][name]
        add(Image.open(D / s["file"]), name, s["x"], s["y"])
    for s in place.get("front_pieces", []):
        add(Image.open(D / s["file"]), s["file"].split("/")[-1][:-4], s["x"], s["y"])

    comp = np.asarray(Image.open(P.p("recompose", "recompose.png")).convert("RGBA"))
    psd._record.image_data.set_data([comp[..., c].tobytes() for c in range(4)], psd._record.header)
    out = P.p(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    psd.save(str(out))

    # reopen and check
    chk = PSDImage.open(str(out))
    names = [layer.name for layer in chk]
    expected = int(reference) + 1 + len(place["order_back_to_front"]) + len(place.get("front_pieces", []))
    assert len(names) == expected, (len(names), expected)
    assert chk.size == (W, H)
    # transparency must survive: a sticker layer has transparent pixels and no layer mask
    probe = [layer for layer in chk if layer.name in place["stickers"]][0]
    alpha = np.asarray(probe.topil().convert("RGBA"))[..., 3]
    assert (alpha == 0).any() and not probe.has_mask(), f"layer transparency lost in {probe.name}"
    print(f"{out} written in {time.time() - t0:.0f}s, {out.stat().st_size / 1e6:.0f} MB, {len(names)} layers "
          f"({names[0]} ... {names[-1]})")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", default="deliver/拆分分层.psd")
    ap.add_argument("--no-reference", action="store_true", help="leave out the hidden source layer")
    a = ap.parse_args()
    build_psd(Project(a.project), a.out, not a.no_reference)


if __name__ == "__main__":
    main()
