#!/usr/bin/env python3
"""Register a generated sticker back onto its original crop and score the fit.

Image models move and rescale the subject; this finds the similarity transform
(scale + shift) that best explains the original: generated pixels should cover the
visible region V and stay inside V or the hidden zone Z. Three candidates are tried
(strict, tolerant of a band around V for outline pixels SAM missed, and identity);
among those with near-best coverage the one closest in colour to the original wins.
The registered result is the sticker (stickers/<name>/sticker.png, crop canvas,
original coordinates).

Metrics after registration (at full crop resolution):
  coverage   |G & V| / |V|            visible part reproduced        (want >= 0.95)
  leak       |G - (V | Z)| / |G|      drawn where the original shows something else (want <= 0.05)
  color_mae  mean |RGB diff| on eroded V   informational: redraws differ in detail
  scale, shift_px                     informational: registration corrects them
verdict PASS needs coverage and leak within limits; every sticker still gets a visual check.

  python eval_sticker.py --project P [names...]     (or --folder DIR for one folder)
Writes sticker.png, sheet.jpg (original | registered | outlines | hybrid), metrics.json;
--hybrid also writes sticker_hybrid.png (original visible pixels + generated hidden parts).
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy.signal import fftconvolve

from common import Project, load_mask, within, write_json


def warp(arr, s, tx, ty, size, interp):
    M = np.float32([[s, 0, tx], [0, s, ty]])
    return cv2.warpAffine(arr, M, size, flags=interp, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def register(G, V, Z, scales, ds=4):
    """(s, tx, ty) maximising sum(G' * Wt), Wt = +1 on V, -1 outside V|Z, 0 on Z."""
    h, w = V.shape
    hs, ws = h // ds, w // ds
    Wt = cv2.resize(np.where(V, 1.0, np.where(Z, 0.0, -1.0)).astype(np.float32), (ws, hs), interpolation=cv2.INTER_AREA)
    best = (-1e18, 1.0, 0.0, 0.0)
    cx, cy = w / 2, h / 2
    for s in scales:
        Gs = warp(G.astype(np.float32), s, cx - s * cx, cy - s * cy, (w, h), cv2.INTER_LINEAR)
        Gs = cv2.resize(Gs, (ws, hs), interpolation=cv2.INTER_AREA)
        corr = fftconvolve(Wt, Gs[::-1, ::-1], mode="full")
        iy, ix = np.unravel_index(np.argmax(corr), corr.shape)
        dy, dx = iy - (hs - 1), ix - (ws - 1)
        if corr[iy, ix] > best[0]:
            best = (corr[iy, ix], s, cx - s * cx + dx * ds, cy - s * cy + dy * ds)
    return best[1:]


def alpha_of(gen):
    """Alpha in 0..1. Models sometimes return an opaque image on a flat backdrop:
    then the backdrop colour connected to the border becomes transparent."""
    a = gen[..., 3]
    if a.min() < 250:
        return np.clip(a / 240.0, 0, 1)                    # Codex alpha tops out around 250
    rgb = gen[..., :3]
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    key = np.median(border, axis=0)
    close = (np.abs(rgb - key).max(axis=2) < 28).astype(np.uint8)
    n, lab = cv2.connectedComponents(close)
    edge_labels = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    bg = np.isin(lab, edge_labels[edge_labels > 0]) & (close > 0)
    return (~bg).astype(np.float32)


def evaluate(f: Path, gen_name="gen.png", hybrid=False, cov_min=0.95, leak_max=0.05):
    orig = np.array(Image.open(f / "crop_full.png").convert("RGB"))
    V, Z = load_mask(f / "visible.png"), load_mask(f / "zone.png")
    h, w = V.shape
    gen = np.array(Image.open(f / gen_name).convert("RGBA").resize((w, h), Image.LANCZOS)).astype(np.float32)
    alpha = alpha_of(gen)
    G = alpha > 0.5

    # Candidates: strict mask registration; registration that forgives a band around V
    # (outline/frame pixels SAM missed would otherwise push the fit to a wrong, smaller
    # scale); and the identity (models often keep the subject exactly in place).
    def fit(Zx):
        s, tx, ty = register(G, V, Zx, np.arange(0.60, 1.61, 0.02))
        return register(G, V, Zx, np.arange(s - 0.02, s + 0.021, 0.005))
    band = within(V, 0.03 * max(h, w)) & ~V
    cands = {"strict": fit(Z), "band": fit(Z | band), "identity": (1.0, 0.0, 0.0)}
    k = 4
    Vs, Os = V[::k, ::k], orig[::k, ::k].astype(np.float32)
    stats = {}
    for key, (s, tx, ty) in cands.items():
        aw = warp(alpha, s, tx, ty, (w, h), cv2.INTER_LINEAR)[::k, ::k] > 0.5
        rgb = warp(gen[..., :3], s, tx, ty, (w, h), cv2.INTER_LINEAR)[::k, ::k]
        both = Vs & aw
        stats[key] = (both.sum() / max(1, Vs.sum()),
                      float(np.abs(rgb[both] - Os[both]).mean()) if both.any() else 1e9)
    best_cov = max(c for c, _ in stats.values())
    pick = min((key for key in cands if stats[key][0] >= best_cov - 0.05), key=lambda key: stats[key][1])
    s, tx, ty = cands[pick]
    rgb_w = warp(gen[..., :3], s, tx, ty, (w, h), cv2.INTER_LINEAR)
    a_w = warp(alpha, s, tx, ty, (w, h), cv2.INTER_LINEAR)
    Gw = a_w > 0.5

    cov = (Gw & V).sum() / max(1, V.sum())
    leak = (Gw & ~(V | Z)).sum() / max(1, Gw.sum())
    Ve = cv2.erode(V.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    both = Ve & Gw
    diff = np.abs(rgb_w[both] - orig[both].astype(np.float32))
    mae = float(diff.mean()) if both.any() else None

    # object running into the canvas edge = cut off (reported to the reviewer)
    border = np.zeros_like(Gw)
    border[:2, :] = border[-2:, :] = True
    border[:, :2] = border[:, -2:] = True
    clipped = bool((Gw & border).sum() > max(20, 0.003 * 2 * (w + h)))
    sticker = np.dstack([rgb_w, a_w * 255]).clip(0, 255).astype(np.uint8)
    Image.fromarray(sticker).save(f / "sticker.png")
    hyb = None
    if hybrid:
        hyb_a = np.maximum(V.astype(np.float32), a_w)
        wv = cv2.GaussianBlur(cv2.erode(V.astype(np.float32), np.ones((7, 7), np.uint8)), (0, 0), 3)[..., None]
        hyb = np.dstack([orig * wv + rgb_w * (1 - wv), hyb_a * 255]).clip(0, 255).astype(np.uint8)
        Image.fromarray(hyb).save(f / "sticker_hybrid.png")

    def on_grey(rgba):
        al = rgba[..., 3:4].astype(np.float32) / 255
        return (rgba[..., :3] * al + 128 * (1 - al)).astype(np.uint8)

    ov = on_grey(sticker).copy()
    ov[V ^ (cv2.erode(V.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0)] = (0, 255, 255)
    ov[Z ^ (cv2.erode(Z.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0)] = (255, 0, 255)
    tiles = [("original", orig), ("sticker (registered)", on_grey(sticker)), ("visible=cyan hidden=magenta", ov)]
    if hyb is not None:
        tiles.append(("hybrid", on_grey(hyb)))
    tw = 700
    th = int(h * tw / w)
    sheet = Image.new("RGB", (tw * len(tiles), th + 30), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for i, (name, im) in enumerate(tiles):
        sheet.paste(Image.fromarray(im).resize((tw, th), Image.LANCZOS), (i * tw, 30))
        d.text((i * tw + 6, 8), name, fill=(0, 0, 0))
    sheet.save(f / "sheet.jpg", quality=88)

    m = {"verdict": "PASS" if cov >= cov_min and leak <= leak_max and not clipped else "CHECK",
         "clipped": clipped,
         "coverage": round(float(cov), 4), "leak": round(float(leak), 4),
         "leak_outside_band": round(float((Gw & ~(V | Z | band)).sum() / max(1, Gw.sum())), 4),
         "scale": round(float(s), 4), "shift_px": [round(float(tx), 1), round(float(ty), 1)],
         "registration": pick, "color_mae": None if mae is None else round(mae, 2)}
    write_json(f / "metrics.json", m)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--folder", help="evaluate one sticker folder directly")
    ap.add_argument("--gen", default="gen.png")
    ap.add_argument("--hybrid", action="store_true")
    ap.add_argument("names", nargs="*")
    a = ap.parse_args()
    if a.folder:
        print(json.dumps(evaluate(Path(a.folder), a.gen, a.hybrid)))
        return
    P = Project(a.project)
    names = a.names or [e["name"] for e in P.elements() if (P.sticker_dir(e["name"]) / a.gen).exists()]
    for n in names:
        print(n, json.dumps(evaluate(P.sticker_dir(n), a.gen, a.hybrid)))


if __name__ == "__main__":
    main()
