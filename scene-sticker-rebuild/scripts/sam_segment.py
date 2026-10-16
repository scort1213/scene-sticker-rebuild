#!/usr/bin/env python3
"""Segment the visible part of each element with SAM 2.1 from box/point prompts.

prompts.json (coordinates in full-resolution source pixels):
  {"elements": {
     "name": {"box": [x0,y0,x1,y1], "pos": [[x,y],...], "neg": [[x,y],...],
              "crop": true, "multimask": false},
     "name2": {"parts": [{...}, {...}]}            # several prompts, unioned
  }}
Per part: "crop": false uses the whole image as context (default: a window around
the box, which gives SAM more resolution); "multimask": true keeps the best of SAM's
three proposals. Parts are unioned, closed, holes filled, and only components that
contain a positive point are kept. Overlaps between elements are resolved later by
merge_masks.py. Writes <out>/<name>.png (full canvas), overlay.jpg, report.json.

  python sam_segment.py --project P [--prompts segment/prompts.json] [--out segment/raw] [names...]
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

from common import DEFAULT_SAM_CFG, DEFAULT_SAM_CKPT, Project, load_rgb, sam_predictor, save_mask, write_json

COLORS = [(255, 64, 64), (64, 160, 255), (64, 220, 96), (255, 180, 0), (200, 80, 255), (0, 220, 220), (255, 120, 200)]


class Segmenter:
    def __init__(self, pred, arr, margin, margin_frac):
        self.pred, self.arr, self.margin, self.margin_frac = pred, arr, margin, margin_frac
        self.win = None

    def part(self, p):
        H, W = self.arr.shape[:2]
        x0, y0, x1, y1 = p["box"]
        if p.get("crop", True):
            m = max(self.margin, int(self.margin_frac * max(x1 - x0, y1 - y0)))
            win = (max(0, x0 - m), max(0, y0 - m), min(W, x1 + m), min(H, y1 + m))
        else:
            win = (0, 0, W, H)
        cx0, cy0, cx1, cy1 = win
        if self.win != win:
            self.pred.set_image(self.arr[cy0:cy1, cx0:cx1])
            self.win = win
        pts = [(x - cx0, y - cy0) for x, y in p.get("pos", [])] + [(x - cx0, y - cy0) for x, y in p.get("neg", [])]
        lbl = [1] * len(p.get("pos", [])) + [0] * len(p.get("neg", []))
        masks, scores, _ = self.pred.predict(
            point_coords=np.array(pts, dtype=np.float32) if pts else None,
            point_labels=np.array(lbl, dtype=np.int32) if pts else None,
            box=np.array([x0 - cx0, y0 - cy0, x1 - cx0, y1 - cy0], dtype=np.float32),
            multimask_output=bool(p.get("multimask", False)),
        )
        k = int(np.argmax(scores))
        return win, masks[k] > 0.5, float(scores[k])


def clean(mask, pos_points, close_px):
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_px, close_px))
    m = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, k) > 0
    m = ndi.binary_fill_holes(m)
    lab, _ = ndi.label(m)
    keep = {lab[y, x] for x, y in pos_points if 0 <= y < m.shape[0] and 0 <= x < m.shape[1] and lab[y, x] > 0}
    return np.isin(lab, list(keep)) if keep else m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--prompts", default="segment/prompts.json")
    ap.add_argument("--image", default=None, help="default: source/srgb.png")
    ap.add_argument("--out", default="segment/raw")
    ap.add_argument("--ckpt", default=str(DEFAULT_SAM_CKPT))
    ap.add_argument("--cfg", default=DEFAULT_SAM_CFG)
    ap.add_argument("--margin", type=int, default=200)
    ap.add_argument("--margin-frac", type=float, default=0.5, help="crop margin as a fraction of the box size")
    ap.add_argument("--close", type=int, default=9)
    ap.add_argument("names", nargs="*")
    a = ap.parse_args()

    P = Project(a.project)
    spec = json.loads(P.p(a.prompts).read_text(encoding="utf-8"))
    arr = load_rgb(a.image or P.source)
    H, W = arr.shape[:2]
    seg = Segmenter(sam_predictor(a.ckpt, a.cfg), arr, a.margin, a.margin_frac)
    out = P.p(a.out)
    out.mkdir(parents=True, exist_ok=True)

    s = max(1, max(W, H) // 2400)
    overlay = cv2.resize(arr, (W // s, H // s), interpolation=cv2.INTER_AREA).astype(np.float32)
    report = {}
    items = [(n, e) for n, e in spec["elements"].items() if not a.names or n in a.names]
    for i, (name, e) in enumerate(items):
        parts = e.get("parts") or [{k: e[k] for k in ("box", "pos", "neg", "crop", "multimask") if k in e}]
        # union the parts inside the bounding window of all parts (keeps memory small)
        wins, pms, scores, pos_all = [], [], [], []
        for p in parts:
            win, pm, sc = seg.part(p)
            wins.append(win); pms.append(pm); scores.append(round(sc, 3)); pos_all += p.get("pos", [])
        X0, Y0 = min(w[0] for w in wins), min(w[1] for w in wins)
        X1, Y1 = max(w[2] for w in wins), max(w[3] for w in wins)
        m = np.zeros((Y1 - Y0, X1 - X0), bool)
        for (cx0, cy0, cx1, cy1), pm in zip(wins, pms):
            m[cy0 - Y0:cy1 - Y0, cx0 - X0:cx1 - X0] |= pm
        m = clean(m, [(x - X0, y - Y0) for x, y in pos_all], a.close)
        full = np.zeros((H, W), bool)
        full[Y0:Y1, X0:X1] = m
        save_mask(out / f"{name}.png", full)
        report[name] = {"part_scores": scores, "area": int(m.sum())}
        c = np.array(COLORS[i % len(COLORS)], np.float32)
        ms = cv2.resize(full.astype(np.uint8), (W // s, H // s), interpolation=cv2.INTER_NEAREST) > 0
        overlay[ms] = overlay[ms] * 0.45 + c * 0.55
        del full

    ov = Image.fromarray(overlay.astype(np.uint8))
    d = ImageDraw.Draw(ov)
    for name, e in items:
        for p in e.get("parts") or [e]:
            for x, y in p.get("pos", []):
                d.ellipse([x / s - 4, y / s - 4, x / s + 4, y / s + 4], fill=(0, 255, 0))
            for x, y in p.get("neg", []):
                d.ellipse([x / s - 4, y / s - 4, x / s + 4, y / s + 4], fill=(255, 0, 0))
    ov.save(out / "overlay.jpg", quality=88)
    old = json.loads((out / "report.json").read_text(encoding="utf-8")) if (out / "report.json").exists() else {}
    old.update(report)
    write_json(out / "report.json", old)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
