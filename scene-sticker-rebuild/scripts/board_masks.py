#!/usr/bin/env python3
"""Decide what the board must remove, from the finished stickers.

vis_kept    union over stickers of their SAM-visible pixels: everything that belongs to an
            element is removed and repainted (default; clean "building shell" boards).
            With --return-uncovered only the pixels the sticker actually covers are
            removed and the rest stays on the board: use it only when the board keeps
            furniture and SAM may have grabbed some of it. Under the shell standard the
            uncovered pixels are object fragments, and returning them leaves debris.
silhouettes union of the sticker silhouettes; board_fill.py uses them near vis_kept to
            catch object pixels SAM missed next to the visible area.
Run after every sticker has stickers/<name>/sticker.png.

  python board_masks.py --project P
Writes board/vis_kept.png, board/silhouettes.png and prints the elements that returned
the largest share of their SAM mask to the board (check those masks visually).
"""
import argparse
import json

import cv2
import numpy as np
from PIL import Image

from common import Project, load_mask, write_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--grow", type=int, default=8, help="tolerance between sticker edge and SAM edge (px)")
    ap.add_argument("--return-uncovered", action="store_true",
                    help="keep SAM pixels the sticker does not cover on the board (see docstring)")
    a = ap.parse_args()
    P = Project(a.project)
    W, H = P.size()
    vis_kept = np.zeros((H, W), np.uint8)
    sil = np.zeros((H, W), np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * a.grow + 1, 2 * a.grow + 1))
    report, missing = {}, []
    for e in P.elements():
        f = P.sticker_dir(e["name"])
        if not (f / "sticker.png").exists():
            missing.append(e["name"]); continue
        x0, y0, _, _ = json.loads((f / "crop.json").read_text(encoding="utf-8"))["box_in_image"]
        alpha = np.array(Image.open(f / "sticker.png"))[..., 3] > 127
        vis = load_mask(f / "visible.png")
        covered = vis & (cv2.dilate(alpha.astype(np.uint8), k) > 0)
        keep = covered if a.return_uncovered else vis
        h, w = alpha.shape
        cx0, cy0, cx1, cy1 = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
        sl = (slice(cy0 - y0, cy1 - y0), slice(cx0 - x0, cx1 - x0))
        vis_kept[cy0:cy1, cx0:cx1] |= keep[sl].astype(np.uint8)
        sil[cy0:cy1, cx0:cx1] |= alpha[sl].astype(np.uint8)
        report[e["name"]] = round(float((vis & ~covered).sum() / max(1, vis.sum())), 4)
    if missing:
        raise SystemExit("stickers without sticker.png: " + ", ".join(missing))
    P.p("board").mkdir(exist_ok=True)
    Image.fromarray(vis_kept * 255).save(P.p("board", "vis_kept.png"))
    Image.fromarray(sil * 255).save(P.p("board", "silhouettes.png"))
    write_json(P.p("board", "returned_to_board.json"), report)
    worst = sorted(report.items(), key=lambda kv: -kv[1])[:8]
    print("share of SAM mask the sticker does not cover (largest first; check these stickers):",
          json.dumps(worst, ensure_ascii=False))


if __name__ == "__main__":
    main()
