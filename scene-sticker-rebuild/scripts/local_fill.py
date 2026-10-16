#!/usr/bin/env python3
"""Local board repair: refill one region with a specific hint, optionally tone-matched.

Use when the global board fill left a defect in one place: an object or a part of a
character left behind, blotches, a wrong surface. The zone to redraw is
  (board holes inside --poly) + --add masks (grown) + --redraw polygons - --protect masks,
so finished surfaces next to it (e.g. a re-rendered floor) are never touched.

  prep   python local_fill.py --project P prep --name rug --box x0 y0 x1 y1 \
             --poly "x,y;x,y;..." [--add masks/extra.png] [--protect board/pattern_floor_mask.png] \
             --hint "a plain flat lilac rug with a darker blue border band along its edges"
         -> board/local_<name>/input_target.png + spec.txt (generate gen.png from them)
  apply  python local_fill.py --project P apply --name rug [--tone flat | --tone band --band-edges "x,y;x,y|x,y;x,y"]
--tone flat: generated pixels in the zone get the mean/std colour of the original's
  visible pixels inside the polygon (generated flat surfaces drift in saturation).
--tone band: as flat, but pixels within --band-width of the given real edge segments get
  the original's edge-band colour (rugs, cloths, panels with a darker rim).
"""
import argparse

import cv2
import numpy as np
from PIL import Image

from common import GEN_SIZES, Project, fit_aspect, grow, load_mask, load_rgb, write_json
import json

SPEC = """Use case: precise-object-edit (object removal / background completion)
Asset type: part of the empty background board of a scene sticker book.
Input images:
- Image 1 = EDIT TARGET. A crop of an illustration ({scene_short}). The flat MAGENTA areas are holes where things were removed.

What is behind the holes: {hint}

Primary request: Fill every magenta hole with this, continuing the surrounding scene exactly. Keep every pixel outside the magenta areas unchanged.
Do not add any character, animal, object or text.
Style: identical to the original - {style}.
Output: same canvas and framing as Image 1, no magenta left, no text, no border.
"""


def poly_pts(s):
    return np.array([[int(float(v)) for v in p.split(",")] for p in s.split(";") if p.strip()], np.int32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "apply"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--box", type=int, nargs=4)
    ap.add_argument("--poly", default="", help="region polygon 'x,y;x,y;...' (default: the whole box)")
    ap.add_argument("--add", action="append", default=[], help="extra mask to redraw (grown 25 px), e.g. a leftover part")
    ap.add_argument("--redraw", default="", help="polygons redrawn even outside the board holes, 'x,y;x,y|x,y;...' "
                                                  "(leftover tail tips, soft cast shadows of removed elements)")
    ap.add_argument("--protect", action="append", default=[], help="mask that must not change")
    ap.add_argument("--hint", default="")
    ap.add_argument("--tone", choices=["none", "flat", "band"], default="none")
    ap.add_argument("--band-edges", default="", help="real edge segments 'x,y;x,y|x,y;x,y'")
    ap.add_argument("--band-width", type=float, default=60)
    a = ap.parse_args()
    P = Project(a.project)
    f = P.p("board", f"local_{a.name}")
    st = load_rgb(P.p("board", "state.png"))
    H, W = st.shape[:2]

    if a.cmd == "prep":
        if not a.box:
            raise SystemExit("prep needs --box x0 y0 x1 y1")
        box, kind = fit_aspect(*a.box)
        # shift (not clip) the box into the picture, so the crop keeps the generation aspect
        bw, bh = box[2] - box[0], box[3] - box[1]
        x0 = min(max(0, box[0]), max(0, W - bw)); y0 = min(max(0, box[1]), max(0, H - bh))
        box = [x0, y0, min(W, x0 + bw), min(H, y0 + bh)]
        region = np.zeros((H, W), np.uint8)
        if a.poly:
            cv2.fillPoly(region, [poly_pts(a.poly)], 1)
        else:
            region[box[1]:box[3], box[0]:box[2]] = 1
        zone = load_mask(P.p("board", "hole.png")) & (region > 0)
        for m in a.add:
            zone |= grow(load_mask(P.p(m)), 25)
        for seg in [x for x in a.redraw.split("|") if x.strip()]:
            rm = np.zeros((H, W), np.uint8)
            cv2.fillPoly(rm, [poly_pts(seg)], 1)
            zone |= rm > 0
        for m in a.protect:
            zone &= ~load_mask(P.p(m))
        x0, y0, x1, y1 = box
        zc = zone[y0:y1, x0:x1]
        crop = st[y0:y1, x0:x1].copy()
        crop[zc] = (255, 0, 255)
        tw, th = GEN_SIZES[kind]
        f.mkdir(parents=True, exist_ok=True)
        Image.fromarray(crop).resize((tw, th), Image.LANCZOS).save(f / "input_target.png")
        Image.fromarray(zc.astype(np.uint8) * 255).save(f / "zone.png")
        Image.fromarray((region[y0:y1, x0:x1] * 255).astype(np.uint8)).save(f / "region.png")
        plan = P.plan()
        style = plan.get("style", "the same illustration style") + (f", {plan['view']}" if plan.get("view") else "")
        (f / "spec.txt").write_text(SPEC.format(scene_short=plan.get("scene", "an illustration").rstrip("."),
                                                hint=a.hint or "the background continues", style=style), encoding="utf-8")
        write_json(f / "box.json", {"box": box, "poly": a.poly, "band_edges": a.band_edges})
        print("zone px", int(zc.sum()), "box", box)
        return

    meta = json.loads((f / "box.json").read_text(encoding="utf-8"))
    x0, y0, x1, y1 = meta["box"]
    zc = load_mask(f / "zone.png")
    region = load_mask(f / "region.png")
    g = np.array(Image.open(f / "gen.png").convert("RGB").resize((x1 - x0, y1 - y0), Image.LANCZOS)).astype(np.float32)
    cur = st[y0:y1, x0:x1].astype(np.float32)
    w = np.clip(cv2.distanceTransform(zc.astype(np.uint8), cv2.DIST_L2, 5) / 8.0, 0, 1)[..., None]
    cur = g * w + cur * (1 - w)

    if a.tone != "none":
        orig = load_rgb(P.source)[y0:y1, x0:x1].astype(np.float32)
        hole = load_mask(P.p("board", "hole.png"))[y0:y1, x0:x1]
        ref = region & ~grow(hole, 10)
        if ref.sum() < 1000:
            raise SystemExit("too few visible original pixels inside the region for tone matching")
        tgt = zc & region
        ty, tx = np.nonzero(tgt)
        src = cur[ty, tx]
        hp = src - cv2.GaussianBlur(cur, (0, 0), 5)[ty, tx]            # keep the fill's paper texture
        if a.tone == "band":
            edges = np.full(zc.shape, 255, np.uint8)
            for seg in (a.band_edges or meta.get("band_edges", "")).split("|"):
                pts = poly_pts(seg) - [x0, y0]
                for p, q in zip(pts[:-1], pts[1:]):
                    cv2.line(edges, tuple(map(int, p)), tuple(map(int, q)), 0, 3)
            dist = cv2.distanceTransform(edges, cv2.DIST_L2, 5)
            bw = a.band_width
            band_ref = ref & (dist < bw * 0.9)
            in_ref = ref & (dist > bw * 3)
            band_col = np.median(orig[band_ref], axis=0) if band_ref.sum() > 500 else None
            in_col = np.median(orig[in_ref] if in_ref.sum() > 500 else orig[ref], axis=0)
            t = np.clip((dist[ty, tx] - bw * 0.85) / 25.0, 0, 1)[:, None]
            base = (band_col if band_col is not None else in_col) * (1 - t) + in_col * t
            new = base + hp * 0.5
        else:
            mu, sd = orig[ref].mean(0), orig[ref].std(0)
            smu, ssd = src.mean(0), src.std(0) + 1e-3
            new = (src - smu) / ssd * np.minimum(ssd, sd * 1.2) + mu
        wb = np.clip(cv2.distanceTransform(tgt.astype(np.uint8), cv2.DIST_L2, 5) / 20.0, 0, 1)[ty, tx][:, None]
        cur[ty, tx] = new * wb + src * (1 - wb)

    st[y0:y1, x0:x1] = cur.clip(0, 255).astype(np.uint8)
    Image.fromarray(st).save(P.p("board", "state.png"))
    print("applied", a.name)


if __name__ == "__main__":
    main()
