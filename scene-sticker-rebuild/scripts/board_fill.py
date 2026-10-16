#!/usr/bin/env python3
"""Board: the scene with every sticker element removed.

Default (full regeneration): the whole picture, with every element's area in magenta,
goes to the image model once, and the model's whole output IS the board - no original
pixels are kept. One drawing is consistent everywhere: no seams, no leftover fragments,
no colour mismatch between kept and filled areas. Element areas in magenta keep the
walls, floors and ground lines where they were, so stickers still sit correctly.
Cost: the board has the model's resolution (long side about 1536 px), like the
stickers; sharpening/upscaling is a separate later step for board and stickers alike.

--keep-original (patch mode): only the holes are taken from the model and the rest stays
original, followed by optional refine tiles (tile-prep / tile-apply), pattern_fill.py and
local_fill.py. Use it only when the shell itself must stay pixel-faithful; it needs much
more manual control (residue outside holes, seams, colour drift).

  python board_fill.py --project P init [--keep-original]   hole mask, global input + spec
  (generate board/global/gen.png from board/global/input_target.png + spec.txt)
  python board_fill.py --project P global-apply             -> board/state.png
  optional, patch mode or as a sharpening aid:
  python board_fill.py --project P tile-prep I / tile-apply I
The board prompt text comes from plan.json "board".
"""
import argparse
import json

import cv2
import numpy as np
from PIL import Image

from common import GEN_SIZES, Project, grow, load_mask, load_rgb, write_json

PAD_GREY = (128, 128, 128)

GLOBAL_SPEC = """Use case: precise-object-edit (object removal / background completion)
Asset type: the empty background board of a scene sticker book. Stickers of the removed characters and objects will later be stuck on top of it, so everything outside the holes must stay exactly as it is.
Input images:
- Image 1 = EDIT TARGET. {scene} The flat MAGENTA areas are holes where these were removed: {removed}.{pad_line}

What is behind the holes:
{behind}

After the fill, the picture must contain only: {keep}. Everything else that was removed is gone; the space where it stood is simply empty.

Primary request: Fill every magenta hole with this background, continuing the surrounding scene naturally and in correct perspective. Keep every pixel outside the magenta areas unchanged: same composition, same position and size of everything.{pad_keep}
Do not add any character, animal, furniture, plant, sign, text or other new object. Where a hole is surrounded by floor, wall or ground, it is simply empty floor, wall or ground.

Style: identical to the original - {style}.
Output: same canvas and framing as Image 1, no magenta left, no text, no border.
"""

REFINE_SPEC = """Use case: precise-object-edit (detail restoration)
Asset type: one part of the empty background board of a scene sticker book.
Input images:
- Image 1 = EDIT TARGET. A crop of an illustration ({scene_short}). Some areas look soft and blurry because they were filled in at low resolution.

Primary request: Redraw this exact image with the blurry areas made crisp and detailed like the sharp areas: same outline thickness, same flat colours and texture, same pattern scale, same perspective. Keep the composition, every line, shape, colour and position exactly the same.
Do not add, remove or move anything. No new objects, no characters, no text.
Style: {style}.
Output: same canvas and framing as Image 1, no border.
"""


def plan_texts(P):
    plan = P.plan()
    b = plan.get("board", {})
    style = plan.get("style", "the same illustration style")
    if plan.get("view"):
        style += f", {plan['view']}"
    behind = b.get("behind", "the background continues behind them")
    if isinstance(behind, list):
        behind = "\n".join(f"- {x}" for x in behind)
    removed = b.get("removed") or ", ".join(e["desc"].split(",")[0] for e in P.elements()[:12]) + ", and others"
    keep = b.get("keep", "the building shell only: walls, ceiling, floor, doors and windows (indoors); ground, sky, water and distant scenery (outdoors)")
    return dict(scene=plan.get("scene", "An illustration."), scene_short=plan.get("scene", "an illustration").rstrip("."),
                removed=removed, behind=behind, keep=keep, style=style)


def tiles_for(W, H, tile, border):
    def starts(L):
        if L <= tile:
            return [0]
        k = 1
        while (L - tile) / k > tile * (1 - 2 * border) - 20:
            k += 1
        return sorted({int(round(i * (L - tile) / k)) for i in range(k + 1)})
    tw, th = min(tile, W), min(tile, H)
    return [[x, y, x + tw, y + th] for y in starts(H) for x in starts(W)]


def init(P, hole_grow=15, sil_reach=80, round_px=12, close_px=41, tile=None, border=0.06, keep_original=False):
    img = load_rgb(P.source)
    H, W = img.shape[:2]
    vis = load_mask(P.p("board", "vis_kept.png"))
    sil = load_mask(P.p("board", "silhouettes.png"))
    hole = grow(vis, hole_grow) | (sil & grow(vis, sil_reach))
    hole = cv2.morphologyEx(grow(hole, round_px).astype(np.uint8), cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_px, close_px))) > 0
    Image.fromarray(hole.astype(np.uint8) * 255).save(P.p("board", "hole.png"))
    t = img.copy()
    t[hole] = (255, 0, 255)
    # pad to the nearest supported generation aspect with flat grey bars
    kind = "landscape" if W / H > 1.25 else "portrait" if W / H < 0.8 else "square"
    gw, gh = GEN_SIZES[kind]
    if W / H < gw / gh:
        PW, PH = int(round(H * gw / gh)), H
    else:
        PW, PH = W, int(round(W * gh / gw))
    left, top = (PW - W) // 2, (PH - H) // 2
    canvas = np.full((PH, PW, 3), PAD_GREY, np.uint8)
    canvas[top:top + H, left:left + W] = t
    g = P.p("board", "global")
    g.mkdir(parents=True, exist_ok=True)
    Image.fromarray(canvas).resize((gw, gh), Image.LANCZOS).save(g / "input_target.png")
    tx = plan_texts(P)
    padded = PW != W or PH != H
    tx["pad_line"] = " The flat grey bars at the edges are padding." if padded else ""
    tx["pad_keep"] = " Keep the grey padding bars flat grey." if padded else ""
    (g / "spec.txt").write_text(GLOBAL_SPEC.format(**tx), encoding="utf-8")
    tile = tile or int(min(3400, max(1024, round(max(W, H) / 2.3))))   # ~3 tiles per side, never above 3400 px
    tiles = tiles_for(W, H, tile, border) if max(W, H) > 1600 else []
    write_json(P.p("board", "meta.json"), {"mode": "patch" if keep_original else "full",
                                          "W": W, "H": H, "PW": PW, "PH": PH, "left": left, "top": top,
                                          "tile": tile, "border": border, "tiles": tiles})
    print("hole fraction %.3f; %d refine tiles%s" % (hole.mean(), len(tiles), "" if tiles else " (image small: no refine needed)"))


def global_apply(P):
    meta = json.loads(P.p("board", "meta.json").read_text(encoding="utf-8"))
    W, H, PW, PH, left, top = (meta[k] for k in ("W", "H", "PW", "PH", "left", "top"))
    img = load_rgb(P.source).astype(np.float32)
    hole = load_mask(P.p("board", "hole.png"))
    g = Image.open(P.p("board", "global", "gen.png")).convert("RGB").resize((PW, PH), Image.LANCZOS)
    g = np.array(g)[top:top + H, left:left + W].astype(np.float32)
    # compensate a small global drift using the known (non-hole) pixels
    s = 8
    small = lambda x: cv2.resize(cv2.cvtColor(x.astype(np.uint8), cv2.COLOR_RGB2GRAY), (W // s, H // s)).astype(np.float32)
    win = cv2.resize((~hole).astype(np.float32), (W // s, H // s))
    (sx, sy), _ = cv2.phaseCorrelate(small(img) * win, small(g) * win)
    g = cv2.warpAffine(g, np.float32([[1, 0, -sx * s], [0, 1, -sy * s]]), (W, H), borderMode=cv2.BORDER_REPLICATE)
    w = np.clip(cv2.distanceTransform(hole.astype(np.uint8), cv2.DIST_L2, 5) / 8.0, 0, 1)[..., None]
    out = (g * w + img * (1 - w)).astype(np.uint8) if meta.get("mode") == "patch" else g.clip(0, 255).astype(np.uint8)
    Image.fromarray(out).save(P.p("board", "stage1.png"))
    Image.fromarray(out).save(P.p("board", "state.png"))
    diff = np.abs(g - img).max(axis=2)[~hole]
    # Debris finder: where the model's clean drawing disagrees with the original outside
    # the holes. Leftover object fragments (shelf edges, ribbon ends, rug corners) show up
    # as compact bright blobs; regular patterns (floor tiles, cobbles) also light up because
    # of small drift - judge visually, then clean real debris with local_fill.py --redraw.
    k = max(1, max(W, H) // 1600)
    gs = cv2.resize(g.astype(np.uint8), (W // k, H // k), interpolation=cv2.INTER_AREA)
    os_ = cv2.resize(img.astype(np.uint8), (W // k, H // k), interpolation=cv2.INTER_AREA)
    hs = cv2.resize(hole.astype(np.uint8), (W // k, H // k), interpolation=cv2.INTER_NEAREST) > 0
    dm = np.abs(gs.astype(np.int16) - os_.astype(np.int16)).max(axis=2)
    dm[hs] = 0
    pair = np.concatenate([os_, gs, np.dstack([np.clip(dm * 3, 0, 255).astype(np.uint8)] * 3)], axis=1)
    Image.fromarray(pair).save(P.p("board", "global", "debris_finder.jpg"), quality=85)
    note = "; see board/global/debris_finder.jpg" if meta.get("mode") == "patch" else "; whole output used as the board"
    print("global drift corrected (%.1f, %.1f) px; mean diff outside holes %.1f%s" % (sx * s, sy * s, diff.mean(), note))


def _tile_geom(meta, i):
    x0, y0, x1, y1 = meta["tiles"][i]
    W, H = meta["W"], meta["H"]
    b = int(meta["border"] * meta["tile"])
    px0, py0 = (x0 if x0 == 0 else x0 + b), (y0 if y0 == 0 else y0 + b)
    px1, py1 = (x1 if x1 == W else x1 - b), (y1 if y1 == H else y1 - b)
    return (x0, y0, x1, y1), (px0, py0, px1, py1)


def tile_prep(P, i) -> bool:
    meta = json.loads(P.p("board", "meta.json").read_text(encoding="utf-8"))
    (x0, y0, x1, y1), (px0, py0, px1, py1) = _tile_geom(meta, i)
    if meta.get("mode") == "patch" and not load_mask(P.p("board", "hole.png"))[py0:py1, px0:px1].any():
        return False
    f = P.p("board", f"tile_{i:02d}")
    f.mkdir(exist_ok=True)
    st = load_rgb(P.p("board", "state.png"))
    Image.fromarray(st[y0:y1, x0:x1]).resize((1024, 1024), Image.LANCZOS).save(f / "input_target.png")
    (f / "spec.txt").write_text(REFINE_SPEC.format(**plan_texts(P)), encoding="utf-8")
    return True


def tile_apply(P, i):
    meta = json.loads(P.p("board", "meta.json").read_text(encoding="utf-8"))
    (x0, y0, x1, y1), (px0, py0, px1, py1) = _tile_geom(meta, i)
    st = load_rgb(P.p("board", "state.png"))
    hole = load_mask(P.p("board", "hole.png"))[y0:y1, x0:x1]
    if meta.get("mode") != "patch":
        hole[:] = True                     # full regeneration: the whole tile is model output
    f = P.p("board", f"tile_{i:02d}")
    gen = np.array(Image.open(f / "gen.png").convert("RGB").resize((x1 - x0, y1 - y0), Image.LANCZOS)).astype(np.float32)
    paste = np.zeros(hole.shape, bool)
    paste[py0 - y0:py1 - y0, px0 - x0:px1 - x0] = True
    w = np.clip(cv2.distanceTransform(hole.astype(np.uint8), cv2.DIST_L2, 5) / 8.0, 0, 1)
    w *= np.clip(cv2.distanceTransform(paste.astype(np.uint8), cv2.DIST_L2, 5) / 40.0, 0, 1)   # soft tile seams
    w[~paste] = 0
    cur = st[y0:y1, x0:x1].astype(np.float32)
    st[y0:y1, x0:x1] = (gen * w[..., None] + cur * (1 - w[..., None])).astype(np.uint8)
    Image.fromarray(st).save(P.p("board", "state.png"))
    (f / "applied").touch()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["init", "global-apply", "tile-prep", "tile-apply"])
    ap.add_argument("i", nargs="?", type=int)
    ap.add_argument("--project", required=True)
    ap.add_argument("--tile", type=int, default=None, help="refine tile size in source px")
    ap.add_argument("--hole-grow", type=int, default=15)
    ap.add_argument("--keep-original", action="store_true", help="patch mode: keep original pixels outside the holes")
    a = ap.parse_args()
    P = Project(a.project)
    if a.cmd == "init":
        init(P, hole_grow=a.hole_grow, tile=a.tile, keep_original=a.keep_original)
    elif a.cmd == "global-apply":
        global_apply(P)
    elif a.cmd == "tile-prep":
        print("PREP" if tile_prep(P, a.i) else "SKIP")
    else:
        tile_apply(P, a.i)
        print("APPLIED", a.i)


if __name__ == "__main__":
    main()
