#!/usr/bin/env python3
"""Merge the raw SAM masks of all plan elements into one non-overlapping set.

Element order in plan.json decides who owns overlapping pixels (earlier wins), so
list front-most elements first. Per element: outline-ink recovery for line art (SAM
tends to stop inside dark outlines: dark pixels in a ring outside the mask that no
other element owns are added; off with plan "outlines": false), hole filling, speck
removal. Touching elements are recorded as
`neighbours` for review only; hidden zones always come from plan `occluders`.

  python merge_masks.py --project P [--union name=path ...]
Raw masks: segment/raw/<name>.png, or plan element "mask": "relative/path.png".
An element with "merge_into": "<host>" (too small to be its own sticker, see
size_check.py) is painted as part of the host and gets no sticker of its own.
--union assigns extra masks to an element (a separately segmented tail, or a part
another element's mask grabbed); these pixels override the plan order.
Writes masks/<name>.png, masks/index.json, masks/overlay.jpg.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from common import Project, bbox, load_mask, load_rgb, write_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--raw", default="segment/raw")
    ap.add_argument("--union", action="append", default=[], help="name=path (relative to project or absolute)")
    ap.add_argument("--grow", type=int, default=14, help="outline recovery ring width (px)")
    ap.add_argument("--ink", type=float, default=110, help="max luminance counted as outline ink")
    ap.add_argument("--min-frac", type=float, default=0.004, help="drop components smaller than this share")
    ap.add_argument("--touch", type=int, default=30)
    ap.add_argument("--no-outline", action="store_true", help="skip outline-ink recovery (same as plan \"outlines\": false)")
    a = ap.parse_args()

    P = Project(a.project)
    els = P.elements()                    # elements with "merge_into" are painted as their host
    img = load_rgb(P.source)
    H, W = img.shape[:2]
    # outline recovery only for line-art styles (plan "outlines": false for painterly art,
    # where dark pixels next to a mask are shading or other objects, not its outline)
    outlines = P.plan().get("outlines", True) and not a.no_outline
    ink = (cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) < a.ink) if outlines else np.zeros((H, W), bool)
    unions = {}
    for u in a.union:
        n, path = u.split("=", 1)
        unions.setdefault(n, []).append(P.p(path) if not Path(path).is_absolute() else Path(path))

    label = np.zeros((H, W), np.uint16)          # 0 = board, i+1 = element i
    idx = {e["name"]: i for i, e in enumerate(els)}
    for e in P.all_elements():                   # plan order: earlier wins overlaps
        target = e.get("merge_into") or e["name"]
        if target not in idx:
            print("UNKNOWN merge_into host", target, "for", e["name"]); continue
        src = P.p(e["mask"]) if e.get("mask") else P.p(a.raw, f"{e['name']}.png")
        if not src.exists():
            print("MISSING raw mask", e["name"]); continue
        label[load_mask(src) & (label == 0)] = idx[target] + 1
    # explicit --union corrections override the plan order (e.g. a cart handle lying
    # across a cat's chest that the cat's mask grabbed first)
    for n, paths in unions.items():
        for extra in paths:
            label[load_mask(extra)] = idx[n] + 1

    out = P.p("masks")
    out.mkdir(parents=True, exist_ok=True)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * a.grow + 1, 2 * a.grow + 1))
    final = np.zeros((H, W), np.uint16)
    for i, e in enumerate(els):
        m_full = label == i + 1
        if not m_full.any():
            print("EMPTY", e["name"]); continue
        x0, y0, x1, y1 = bbox(m_full)
        pad = a.grow + 4
        x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
        m = m_full[y0:y1, x0:x1]
        owned = label[y0:y1, x0:x1] > 0
        ring = (cv2.dilate(m.astype(np.uint8), k) > 0) & ~m
        lab, _ = ndi.label((ring & ink[y0:y1, x0:x1] & ~owned) | m)
        keep = np.unique(lab[m]); keep = keep[keep > 0]
        r = np.isin(lab, keep)
        r = cv2.morphologyEx(r.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))) > 0
        r = ndi.binary_fill_holes(r)
        lab, n = ndi.label(r)
        if n > 1:
            sizes = ndi.sum(r, lab, range(1, n + 1))
            r = np.isin(lab, [j + 1 for j, s in enumerate(sizes) if s >= a.min_frac * sizes.sum()])
        sub = final[y0:y1, x0:x1]
        sub[r & (sub == 0)] = i + 1

    index = {}
    td = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * a.touch + 1, 2 * a.touch + 1))
    for i, e in enumerate(els):
        m_full = final == i + 1
        if not m_full.any():
            continue
        x0, y0, x1, y1 = bbox(m_full)
        X0, Y0, X1, Y1 = max(0, x0 - a.touch), max(0, y0 - a.touch), min(W, x1 + a.touch), min(H, y1 + a.touch)
        win = final[Y0:Y1, X0:X1]
        near = np.unique(win[cv2.dilate((win == i + 1).astype(np.uint8), td) > 0])
        Image.fromarray(m_full.astype(np.uint8) * 255).save(out / f"{e['name']}.png")
        index[e["name"]] = {"kind": e.get("kind", "object"), "bbox": [x0, y0, x1, y1], "area": int(m_full.sum()),
                            "occluders": e.get("occluders", []),
                            "neighbours": [els[j - 1]["name"] for j in near if 0 < j != i + 1]}
    write_json(out / "index.json", index)

    s = max(1, max(W, H) // 2400)
    rng = np.random.default_rng(3)
    cols = rng.integers(40, 255, (len(els) + 1, 3)).astype(np.float32)
    pv = cv2.resize(img, (W // s, H // s), interpolation=cv2.INTER_AREA).astype(np.float32)
    lab_s = cv2.resize(final, (W // s, H // s), interpolation=cv2.INTER_NEAREST)
    sel = lab_s > 0
    pv[sel] = pv[sel] * 0.45 + cols[lab_s[sel]] * 0.55
    Image.fromarray(pv.astype(np.uint8)).save(out / "overlay.jpg", quality=88)
    # touching elements that are not declared occluders either way: worth a second look
    review = []
    for n, v in index.items():
        for nb in v["neighbours"]:
            if nb not in v["occluders"] and n not in index.get(nb, {}).get("occluders", []) and (nb, n) not in review:
                review.append((n, nb))
    print(json.dumps({"elements": len(index), "touching_without_occlusion_decision": review}, ensure_ascii=False))


if __name__ == "__main__":
    main()
