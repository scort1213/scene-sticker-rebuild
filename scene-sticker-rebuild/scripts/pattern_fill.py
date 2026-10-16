#!/usr/bin/env python3
"""Re-render a regular two-colour pattern (checkered floor, tiles) inside board holes so
it continues the original grid exactly. Image models redraw such grids with drift of
tens of pixels and blurry, broken tile edges; this replaces them deterministically.

  mask    segment the whole pattern surface on board/state.png with SAM from seed points
          -> board/pattern_<name>_mask.png   (check it covers the surface and nothing else)
  fit     two colours from a clean original patch (k-means); line angles and spacing from
          Hough lines on that patch; then a sine-product checker model is fitted to all
          visible pattern pixels of the original -> board/pattern_<name>.json
  render  per hole component on the surface: refit the phase locally on the visible
          pattern around it (hand-drawn grids are not perfectly regular), draw crisp
          tiles in the two colours plus paper texture from tile interiors -> state.png

  python pattern_fill.py --project P mask   --name floor --box x0 y0 x1 y1 --pos "x,y;x,y" [--neg "x,y"]
  python pattern_fill.py --project P fit    --name floor --patch x0 y0 x1 y1 [--spacing-a S --spacing-b S]
  python pattern_fill.py --project P render --name floor [--all]
Only for two-colour periodic patterns with straight tile edges. Check the result; where
the original grid itself is irregular, small steps at hole borders remain.
"""
import argparse

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from scipy.optimize import minimize

from common import Project, load_mask, load_rgb, sam_predictor, write_json
import json


def pts(s):
    return [[int(float(v)) for v in p.split(",")] for p in s.split(";") if p.strip()] if s else []


def field(p, X, Y):
    tA, sA, cA, tB, sB, cB = p
    a, b = np.radians(tA), np.radians(tB)
    return np.sin(np.pi * ((X * np.cos(a) + Y * np.sin(a)) / sA - cA)) * np.sin(np.pi * ((X * np.cos(b) + Y * np.sin(b)) / sB - cB))


def cmd_mask(P, a):
    st = load_rgb(P.p("board", "state.png"))
    X0, Y0, X1, Y1 = a.box
    sub = st[Y0:Y1, X0:X1]
    s = max(1, int(np.ceil(max(sub.shape[:2]) / 2048)))
    small = cv2.resize(sub, (sub.shape[1] // s, sub.shape[0] // s), interpolation=cv2.INTER_AREA)
    pred = sam_predictor()
    pred.set_image(small)
    pos, neg = pts(a.pos), pts(a.neg)
    Pt = (np.array(pos + neg, np.float32) - [X0, Y0]) / s
    L = np.array([1] * len(pos) + [0] * len(neg), np.int32)
    masks, scores, _ = pred.predict(point_coords=Pt, point_labels=L, multimask_output=True)
    m = masks[int(np.argmax(scores))] > 0.5
    m = cv2.resize(m.astype(np.uint8), (sub.shape[1], sub.shape[0]), interpolation=cv2.INTER_NEAREST)
    m = ndi.binary_fill_holes(cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((41, 41), np.uint8)) > 0)
    full = np.zeros(st.shape[:2], np.uint8)
    full[Y0:Y1, X0:X1] = m.astype(np.uint8) * 255
    Image.fromarray(full).save(P.p("board", f"pattern_{a.name}_mask.png"))
    pv = cv2.resize(st, (st.shape[1] // 8, st.shape[0] // 8)).astype(np.float32)
    ms = cv2.resize(full, (st.shape[1] // 8, st.shape[0] // 8)) > 0
    pv[ms] = pv[ms] * 0.5 + np.array([0, 200, 255]) * 0.5
    Image.fromarray(pv.astype(np.uint8)).save(P.p("board", f"pattern_{a.name}_mask_preview.jpg"), quality=85)
    print("pattern surface px", int(m.sum()), "score", round(float(scores.max()), 3))


def hough_families(cls_img):
    edges = cv2.Canny(cls_img, 50, 150)
    thr = max(60, int(0.15 * min(cls_img.shape)))
    lines = cv2.HoughLines(edges, 1, np.pi / 720, thr)
    if lines is None:
        return []
    th, rho = np.degrees(lines[:, 0, 1]), lines[:, 0, 0]
    hist = np.bincount(np.round(th).astype(int) % 180, minlength=180)
    fams = []
    for t0 in np.argsort(hist)[::-1]:
        if hist[t0] == 0 or any(min(abs(t0 - f[0]), 180 - abs(t0 - f[0])) < 20 for f in fams):
            continue
        sel = np.abs(th - t0) < 1.5
        r = np.sort(rho[sel])
        centres, cur = [], [r[0]]
        for v in r[1:]:
            if v - cur[-1] <= 15:
                cur.append(v)
            else:
                centres.append(np.mean(cur)); cur = [v]
        centres.append(np.mean(cur))
        d = np.diff(centres)
        d = d[d > 40]
        fams.append((float(np.median(th[sel])), float(np.median(d)) if len(d) else None))
        if len(fams) == 2:
            break
    return fams


def cmd_fit(P, a):
    o = load_rgb(P.source).astype(np.float32)
    x0, y0, x1, y1 = a.patch
    patch = o[y0:y1, x0:x1].reshape(-1, 3)
    _, _, cen = cv2.kmeans(patch, 2, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5), 3, cv2.KMEANS_PP_CENTERS)
    cen = cen[np.argsort(cen.sum(1))]
    g = o[y0:y1, x0:x1]
    d = np.stack([np.linalg.norm(g - c, axis=2) for c in cen])
    cls = (d[1] < d[0]).astype(np.uint8) * 255
    cls[np.minimum(d[0], d[1]) > 30] = 0
    fams = hough_families(cls)
    if len(fams) < 2 and not (a.angle_a and a.angle_b):
        raise SystemExit(f"could not find two line families in the patch (found {fams}); pass --angle-a/--angle-b")
    tA = a.angle_a or fams[0][0]
    tB = a.angle_b or fams[1][0]
    sA = a.spacing_a or (fams[0][1] if fams else None)
    sB = a.spacing_b or (fams[1][1] if len(fams) > 1 else None)
    if not sA or not sB:
        raise SystemExit(f"spacing not measurable from the patch (families {fams}); pass --spacing-a/--spacing-b")
    print("colours", cen.round(1).tolist(), "start angles/spacings", round(tA, 1), round(sA, 1), round(tB, 1), round(sB, 1))

    surf = load_mask(P.p("board", f"pattern_{a.name}_mask.png"))
    hole = load_mask(P.p("board", "hole.png"))
    vis = surf & ~cv2.dilate(hole.astype(np.uint8), np.ones((31, 31), np.uint8)).astype(bool)
    ys, xs = np.nonzero(vis)
    rng = np.random.default_rng(1)
    pick = rng.choice(len(xs), min(400000, len(xs)), replace=False)
    ys, xs = ys[pick], xs[pick]
    dd = np.stack([np.linalg.norm(o[ys, xs] - c, axis=1) for c in cen])
    ok = dd.min(0) < 30
    X, Y = xs[ok].astype(np.float64), ys[ok].astype(np.float64)
    S = np.where(dd[1][ok] < dd[0][ok], 1.0, -1.0)
    loss = lambda p: -abs(np.mean(field(p, X, Y) * S))
    best = (0, None)
    for fa in (0.97, 1.0, 1.03):
        for fb in (0.97, 1.0, 1.03):
            for cA in np.linspace(0, 1, 8, endpoint=False):
                for cB in np.linspace(0, 1, 8, endpoint=False):
                    q = [tA, sA * fa, cA, tB, sB * fb, cB]
                    v = loss(q)
                    if v < best[0]:
                        best = (v, q)
    r = minimize(loss, best[1], method="Nelder-Mead", options={"maxiter": 6000, "xatol": 1e-4, "fatol": 1e-7})
    p = r.x
    sgn = np.sign(np.mean(field(p, X, Y) * S))
    acc = float(np.mean(np.sign(field(p, X, Y)) * sgn == S))
    write_json(P.p("board", f"pattern_{a.name}.json"), {"params": list(map(float, p)), "sign": float(sgn),
                                                        "colors": cen.tolist(), "agreement": acc})
    print("fitted", np.round(p, 3).tolist(), "parity agreement %.3f" % acc,
          "(below ~0.85: the grid is irregular; render still refits locally)")


def cmd_render(P, a):
    orig = load_rgb(P.source).astype(np.float32)
    st = load_rgb(P.p("board", "state.png"))
    hole = load_mask(P.p("board", "hole.png"))
    surf = load_mask(P.p("board", f"pattern_{a.name}_mask.png"))
    L = json.loads(P.p("board", f"pattern_{a.name}.json").read_text(encoding="utf-8"))
    p0, cen = np.array(L["params"]), np.array(L["colors"], np.float32)
    d = np.stack([np.linalg.norm(orig - c, axis=2) for c in cen])
    clean = surf & ~cv2.dilate(hole.astype(np.uint8), np.ones((31, 31), np.uint8)).astype(bool) & (d.min(0) < 30)
    sig = np.where(d[1] < d[0], 1.0, -1.0)
    tex = orig - cv2.GaussianBlur(orig, (0, 0), 6)            # paper texture, tile interiors only
    clean_tex = np.zeros_like(clean)
    for c in (0, 1):
        cm = (clean & ((d[1] < d[0]) == bool(c))).astype(np.uint8)
        clean_tex |= cv2.erode(cm, np.ones((15, 15), np.uint8)).astype(bool)
    del d
    out = st.astype(np.float32)
    # --all: redraw the whole surface (shell boards: removes leftover fragments of rugs,
    # legs and shadows that lie outside the holes; visible tiles are matched by the fit)
    lab, n = ndi.label(surf if a.all else (surf & hole))
    rng = np.random.default_rng(0)
    R = a.ring
    for k in range(1, n + 1):
        comp = lab == k
        if comp.sum() < 3000:
            continue
        ys, xs = np.nonzero(comp)
        X0, Y0 = max(0, xs.min() - R), max(0, ys.min() - R)
        X1, Y1 = min(st.shape[1], xs.max() + 1 + R), min(st.shape[0], ys.max() + 1 + R)
        cw = comp[Y0:Y1, X0:X1]
        ring = (cv2.distanceTransform((~cw).astype(np.uint8), cv2.DIST_L2, 5) <= R) & clean[Y0:Y1, X0:X1]
        ry, rx = np.nonzero(ring)
        if len(rx) < 5000:
            print(k, "too little visible pattern nearby; kept the fill"); continue
        pick = rng.choice(len(rx), min(120000, len(rx)), replace=False)
        PX, PY = (rx[pick] + X0).astype(np.float64), (ry[pick] + Y0).astype(np.float64)
        S = sig[PY.astype(int), PX.astype(int)]
        loss = lambda p: -abs(np.mean(field(p, PX, PY) * S))
        best = (0, p0)
        for dA in np.linspace(-0.5, 0.5, 9):
            for dB in np.linspace(-0.5, 0.5, 9):
                q = p0.copy(); q[2] += dA; q[5] += dB
                v = loss(q)
                if v < best[0]:
                    best = (v, q)
        p = minimize(loss, best[1], method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-4, "fatol": 1e-7}).x
        sgn = np.sign(np.mean(field(p, PX, PY) * S))
        acc = np.mean(np.sign(field(p, PX, PY)) * sgn == S)
        band = cv2.dilate(cw.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool) & surf[Y0:Y1, X0:X1]
        yy, xx = np.nonzero(band)
        tA, sA, cA, tB, sB, cB = p
        Xg, Yg = (xx + X0).astype(np.float64), (yy + Y0).astype(np.float64)
        uA = (Xg * np.cos(np.radians(tA)) + Yg * np.sin(np.radians(tA))) / sA - cA
        uB = (Xg * np.cos(np.radians(tB)) + Yg * np.sin(np.radians(tB))) / sB - cB
        par = np.sign(np.sin(np.pi * uA)) * np.sign(np.sin(np.pi * uB)) * sgn
        dist = np.minimum(np.abs(uA - np.round(uA)) * sA, np.abs(uB - np.round(uB)) * sB)
        w = np.where(dist >= 1.0, (par > 0).astype(np.float64), np.clip(0.5 + par * dist * 0.5, 0, 1))[:, None]
        col = cen[0][None, :] * (1 - w) + cen[1][None, :] * w
        oy, ox = rng.integers(-R // 2, R // 2, 2)
        ty = np.clip(yy + Y0 + oy, 0, st.shape[0] - 1)
        tx = np.clip(xx + X0 + ox, 0, st.shape[1] - 1)
        col += tex[ty, tx] * clean_tex[ty, tx][:, None]
        out[yy + Y0, xx + X0] = col
        print(k, int(comp.sum()), "px, local agreement %.3f" % acc)
    Image.fromarray(out.clip(0, 255).astype(np.uint8)).save(P.p("board", "state.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["mask", "fit", "render"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--name", default="floor")
    ap.add_argument("--box", type=int, nargs=4, help="mask: region containing the whole pattern surface")
    ap.add_argument("--pos", default="", help="mask: seed points on the surface, 'x,y;x,y'")
    ap.add_argument("--neg", default="", help="mask: points that are not the surface")
    ap.add_argument("--patch", type=int, nargs=4, help="fit: a clean, unoccluded patch of the pattern in the original")
    ap.add_argument("--angle-a", type=float); ap.add_argument("--angle-b", type=float)
    ap.add_argument("--spacing-a", type=float); ap.add_argument("--spacing-b", type=float)
    ap.add_argument("--ring", type=int, default=700, help="render: visible pattern used around each hole (px)")
    ap.add_argument("--all", action="store_true", help="render: redraw the whole surface, not only the holes")
    a = ap.parse_args()
    P = Project(a.project)
    {"mask": cmd_mask, "fit": cmd_fit, "render": cmd_render}[a.cmd](P, a)


if __name__ == "__main__":
    main()
