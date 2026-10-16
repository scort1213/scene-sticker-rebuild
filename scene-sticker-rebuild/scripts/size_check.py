#!/usr/bin/env python3
"""Printed size of every element, to decide which ones are too small to be stickers.

Needs plan.json "print": {"width_cm": W} (or "height_cm") - the finished printed size
of the whole picture, asked from the user at the start - and optionally
"min_sticker_cm" (default 1.5): elements whose printed size - the side of a square of
the same bounding-box area, so long thin vines are not flagged - is below it are listed
with a suggested host (the touching element their box overlaps most). To merge, add
"merge_into": "<host>" to the small element in plan.json, add what it is to the host's
"desc", and rerun merge_masks.py. Sizes come from the visible masks (run before generating,
to save calls); once stickers/<name>/sticker.png exists its completed size is used.

  python size_check.py --project P            run after merge_masks.py
Writes qa/size_check.json.
"""
import argparse
import json

import numpy as np
from PIL import Image

from common import Project, write_json


def overlap(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return max(0, x1 - x0) * max(0, y1 - y0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    a = ap.parse_args()
    P = Project(a.project)
    plan = P.plan()
    pr = plan.get("print") or {}
    W, H = P.size()
    if pr.get("width_cm"):
        cm_per_px = pr["width_cm"] / W
    elif pr.get("height_cm"):
        cm_per_px = pr["height_cm"] / H
    else:
        raise SystemExit('plan.json needs "print": {"width_cm": ...} - ask the user for the finished print size')
    min_cm = pr.get("min_sticker_cm", 1.5)
    index = P.index()
    labels = {e["name"]: e.get("label", e["name"]) for e in P.elements()}
    rows, small = [], []
    for n, v in index.items():
        x0, y0, x1, y1 = v["bbox"]
        src = "visible"
        st = P.sticker_dir(n) / "sticker.png"
        if st.exists():
            bb = Image.open(st).getchannel("A").point(lambda x: 255 if x > 127 else 0).getbbox()
            if bb:
                x0, y0, x1, y1 = 0, 0, bb[2] - bb[0], bb[3] - bb[1]
                src = "sticker"
        w_cm, h_cm = (x1 - x0) * cm_per_px, (y1 - y0) * cm_per_px
        size_cm = float(np.sqrt(w_cm * h_cm))
        row = {"name": n, "label": labels.get(n, n), "w_cm": round(w_cm, 1), "h_cm": round(h_cm, 1),
               "size_cm": round(size_cm, 2), "measured_on": src}
        if size_cm < min_cm:
            cands = [(overlap(v["bbox"], index[m]["bbox"]), m) for m in v.get("neighbours", []) if m in index]
            best = max(cands) if cands else (0, None)
            row["suggest_merge_into"] = best[1] if best[0] > 0 else None
            small.append(row)
        rows.append(row)
    write_json(P.p("qa", "size_check.json"), {"cm_per_px": cm_per_px, "min_sticker_cm": min_cm, "elements": rows})
    print(f"picture printed {W * cm_per_px:.1f} x {H * cm_per_px:.1f} cm; threshold {min_cm} cm")
    for r in sorted(small, key=lambda r: r["size_cm"]):
        host = r.get("suggest_merge_into")
        print(f"  small: {r['label']} ({r['name']}) {r['w_cm']}x{r['h_cm']} cm ({r['measured_on']}) -> merge into "
              f"{labels.get(host, host) if host else '? (nothing touching it; keep, or merge by hand)'}")
    if not small:
        print("  no element below the threshold")


if __name__ == "__main__":
    main()
