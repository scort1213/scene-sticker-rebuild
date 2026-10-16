#!/usr/bin/env python3
"""Stick every sticker back onto the board and compare with the original.

Stack order comes from the original: if A's visible pixels lie inside B's completed
but hidden area, A is in front of B there; the order is sorted by the net amount.
Stickers are always complete and are simply stacked in that order. Where two elements
interlock (paws resting on a table the body sits behind), the upper sticker hides that
small part; this differs slightly from the original and is accepted by default.
Optional extras (off by default; small fiddly fragments are impractical in a sticker book):
  --front-pieces  a lower sticker's original-visible pixels that an upper completion
                  covers, cut as extra pieces stuck after all stickers
  --board-pieces  original pixels covered by a completion where no sticker was visible
                  (only meaningful with a patch-mode board that keeps original pixels)

  python recompose.py --project P
Writes recompose/recompose.png, preview.jpg, diff.jpg, pieces/*.png, layout.json, metrics.json.
"""
import argparse
import itertools
import json

import cv2
import numpy as np
from PIL import Image

from common import Project, load_mask, load_rgb, write_json


def inter(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return (x0, y0, x1, y1) if x0 < x1 and y0 < y1 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--board", default="board/state.png")
    ap.add_argument("--min-piece", type=int, default=500)
    ap.add_argument("--min-board-piece", type=int, default=3000)
    ap.add_argument("--front-pieces", action="store_true")
    ap.add_argument("--board-pieces", action="store_true")
    a = ap.parse_args()
    P = Project(a.project)
    orig = load_rgb(P.source)
    H, W = orig.shape[:2]
    board = load_rgb(P.p(a.board))
    out = P.p("recompose")
    (out / "pieces").mkdir(parents=True, exist_ok=True)

    S = {}
    for e in P.elements():
        f = P.sticker_dir(e["name"])
        if not (f / "sticker.png").exists():
            raise SystemExit(f"missing sticker for {e['name']}")
        x0, y0, x1, y1 = json.loads((f / "crop.json").read_text(encoding="utf-8"))["box_in_image"]
        rgba = np.array(Image.open(f / "sticker.png").convert("RGBA"))
        vis = load_mask(f / "visible.png")
        vis &= cv2.dilate((rgba[..., 3] > 127).astype(np.uint8), np.ones((17, 17), np.uint8)) > 0
        cx0, cy0, cx1, cy1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        sl = (slice(cy0 - y0, cy1 - y0), slice(cx0 - x0, cx1 - x0))
        S[e["name"]] = {"box": (cx0, cy0, cx1, cy1), "rgba": rgba[sl], "vis": vis[sl], "comp": rgba[sl][..., 3] > 127}
    names = list(S)

    def region(n, r):
        b = S[n]["box"]
        return (slice(r[1] - b[1], r[3] - b[1]), slice(r[0] - b[0], r[2] - b[0]))

    front = {}
    for p, q in itertools.permutations(names, 2):
        r = inter(S[p]["box"], S[q]["box"])
        front[(p, q)] = 0 if r is None else int((S[p]["vis"][region(p, r)] & S[q]["comp"][region(q, r)] & ~S[q]["vis"][region(q, r)]).sum())
    score = {n: sum(front[(n, m)] - front[(m, n)] for m in names if m != n) for n in names}
    order = sorted(names, key=lambda n: score[n])          # back ... front

    def blend(canvas, rgba, box):
        x0, y0, x1, y1 = box
        al = rgba[..., 3:4].astype(np.float32) / 255
        cur = canvas[y0:y1, x0:x1].astype(np.float32)
        canvas[y0:y1, x0:x1] = (rgba[..., :3] * al + cur * (1 - al)).astype(np.uint8)

    img = board.copy()
    for n in order:
        blend(img, S[n]["rgba"], S[n]["box"])
    layout = {"size": [W, H], "order_back_to_front": order,
              "stickers": {n: {"box": list(S[n]["box"])} for n in names}, "front_pieces": [], "board_pieces": [],
              "interlocks": [[p, q] for p, q in itertools.combinations(names, 2) if front[(p, q)] > 500 and front[(q, p)] > 500]}

    for i, n in enumerate(order if a.front_pieces else []):
        bx = S[n]["box"]
        above = np.zeros(S[n]["vis"].shape, bool)
        for m in order[i + 1:]:
            r = inter(bx, S[m]["box"])
            if r is not None:
                above[region(n, r)] |= (S[m]["comp"] & ~S[m]["vis"])[region(m, r)]
        pm = S[n]["vis"] & above
        if pm.sum() >= a.min_piece:
            piece = S[n]["rgba"].copy()
            piece[~pm, 3] = 0
            Image.fromarray(piece).save(out / "pieces" / f"front_{n}.png")
            blend(img, piece, bx)
            layout["front_pieces"].append({"of": n, "box": list(bx), "px": int(pm.sum())})

    anyvis = np.zeros((H, W), bool)
    for n in names:
        x0, y0, x1, y1 = S[n]["box"]
        anyvis[y0:y1, x0:x1] |= S[n]["vis"]
    for n in (names if a.board_pieces else []):
        x0, y0, x1, y1 = S[n]["box"]
        bm = S[n]["comp"] & ~S[n]["vis"] & ~anyvis[y0:y1, x0:x1]
        bm = cv2.morphologyEx(bm.astype(np.uint8), cv2.MORPH_OPEN, np.ones((15, 15), np.uint8)) > 0
        if bm.sum() >= a.min_board_piece:
            piece = np.dstack([orig[y0:y1, x0:x1], bm.astype(np.uint8) * 255])
            Image.fromarray(piece).save(out / "pieces" / f"board_over_{n}.png")
            blend(img, piece, (x0, y0, x1, y1))
            layout["board_pieces"].append({"over": n, "box": [x0, y0, x1, y1], "px": int(bm.sum())})

    Image.fromarray(img).save(out / "recompose.png")
    d = np.abs(img.astype(np.int16) - orig.astype(np.int16)).max(axis=2)
    m = {"stickers": len(names), "front_pieces": len(layout["front_pieces"]), "board_pieces": len(layout["board_pieces"]),
         "mean_abs_diff": round(float(d.mean()), 2), "frac_gt48": round(float((d > 48).mean()), 4),
         "frac_gt48_in_sticker_area": round(float((d[anyvis] > 48).mean()), 4)}
    write_json(out / "metrics.json", m)
    write_json(out / "layout.json", layout)
    s = max(1, max(W, H) // 2400)
    Image.fromarray(img).resize((W // s, H // s), Image.LANCZOS).save(out / "preview.jpg", quality=88)
    Image.fromarray(np.clip(d * 3, 0, 255).astype(np.uint8)).resize((W // s, H // s)).save(out / "diff.jpg", quality=85)
    print(json.dumps(m))


if __name__ == "__main__":
    main()
