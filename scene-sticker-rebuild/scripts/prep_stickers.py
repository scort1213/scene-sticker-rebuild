#!/usr/bin/env python3
"""Prepare the image-generation inputs for each sticker.

For each element (plan order, or the names given):
  hidden zone = pixels of its plan `occluders` near the element
              + the picture edge next to it, and the scene border next to it when plan
                "frames" lists the scene borders (an element is cut by the frame it is in)
              + optional plan `extra_zone` polygons (full-image coordinates)
              + optional `fill_gaps`: unassigned pixels inside its convex hull
                (only for a missed occluder, never for background seen through it)
  canvas      = element + nearby hidden zone, padded to a supported aspect
Writes stickers/<name>/:
  input_target.png   visible pixels at their original place on flat grey, hidden zone magenta
  input_context.jpg  the untouched crop (reference)
  visible.png zone.png crop_full.png crop.json
  spec.txt           completion prompt;  spec_short.txt  shorter retry prompt
  method "peel":     also input_scene.png + spec_scene.txt (remove the occluders from the
                     scene first) and spec_peel.txt (complete with that scene as reference)

  python prep_stickers.py --project P [names...]
"""
import argparse
from collections import OrderedDict

import cv2
import numpy as np
from PIL import Image

from common import GEN_SIZES, GREY, MAGENTA, Project, crop_pad, fit_aspect, grow, load_mask, load_rgb, within, write_json

LONG = """Use case: precise-object-edit (amodal completion of a partly hidden {noun})
Asset type: one die-cut sticker for a scene sticker book. The sticker is stuck back onto the original scene at exactly the same place, so position, size, {pose}, identity and art style must match.
Input images:
- Image 1 = EDIT TARGET. The visible pixels of {desc}, cut out of the original illustration and kept at their original position and size, on a flat grey background. {zone_line}
- Image 2 = CONTEXT. The untouched original illustration of the same area, for understanding the subject, its {pose} and the style. Do not copy anything else from it.

Primary request: Complete this {noun}. Keep every visible part from Image 1 exactly where it is, at the same size and with the same design, colours and patterns. {hidden_line} {kind_line}{notes}

Style: identical to the original - {style}. New parts must look drawn by the same artist.

Output: same canvas size and framing as Image 1. Only the completed {noun} on a fully transparent background. Remove the grey and the magenta completely. No other characters or objects, no floor, no cast shadow, no white sticker border{text_rule}.
Avoid: moving or rescaling the subject, redrawing its visible parts differently, changing colours or patterns, adding accessories or details that are not in the original.
{text_line}"""

SHORT = """Use case: precise-object-edit (complete a partly hidden {noun} for a sticker)
Image 1 = edit target: {desc}, cut out of an illustration, on flat grey, at its original position and size. {zone_short}
Image 2 = the original illustration of the same area (reference only).

Task: complete this {noun}. Keep every visible part exactly where it is, same size, same colours and patterns. {hidden_short}{notes}

Style: {style}.
Output: same canvas and framing as Image 1, only the {noun} on a transparent background, no grey, no magenta, no other objects, no shadow{text_rule}.
{text_line}"""

SCENE = """Use case: precise-object-edit (object removal / reveal what is behind)
Asset type: intermediate step for a scene sticker book: we need to see the complete {noun} that stands behind the removed things, at its exact place.
Input images:
- Image 1 = EDIT TARGET. A crop of the original illustration. The flat MAGENTA areas are holes where the things standing in front of {desc} were removed.

Primary request: Fill every magenta hole with what was behind the removed things: mainly the hidden parts of this {noun}, connecting exactly to its visible parts in the same perspective and size, plus the background behind it. Keep every pixel outside the magenta areas unchanged: same composition, same position and size of everything.
Do not add any character, animal or new object.

Style: identical to the original - {style}.
Output: same canvas and framing as Image 1, no magenta left, no text, no border.
"""

PEEL = """Use case: precise-object-edit (complete a mostly hidden {noun} for a sticker)
Image 1 = edit target: {desc}, cut out of an illustration, on flat grey, at its original position and size. Magenta marks where it is hidden behind other things; magenta is a hole, not an object.
Image 2 = the same scene with those things removed, so the whole {noun} is visible there. Use it to see how the complete {noun} looks.

Task: complete this {noun} exactly like it appears in Image 2, keeping every visible part from Image 1 exactly where it is and at the same size. Do not add any part that is not in Image 2.{notes}

Style: {style}.
Output: same canvas and framing as Image 1, only the {noun} on a transparent background, no grey, no magenta, no floor, no wall, no other objects, no shadow{text_rule}.
{text_line}"""


class MaskCache:
    """Small LRU of full-canvas masks (a large image's masks do not fit in memory at once)."""
    def __init__(self, P, size=6):
        self.P, self.size, self.d = P, size, OrderedDict()

    def get(self, name):
        if name in self.d:
            self.d.move_to_end(name)
            return self.d[name]
        m = load_mask(self.P.mask_path(name))
        self.d[name] = m
        if len(self.d) > self.size:
            self.d.popitem(last=False)
        return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--reach", type=float, default=0.35, help="occluder search radius, fraction of element size")
    ap.add_argument("--pad", type=float, default=0.08)
    ap.add_argument("names", nargs="*")
    a = ap.parse_args()

    P = Project(a.project)
    plan = P.plan()
    style = plan.get("style", "the same hand-drawn illustration style, outlines, colours and texture")
    if plan.get("view"):
        style += f", {plan['view']}"
    index = P.index()
    img = load_rgb(P.source)
    H, W = img.shape[:2]
    cache = MaskCache(P)
    els = [e for e in P.elements() if (not a.names or e["name"] in a.names) and e["name"] in index]

    for e in els:
        name = e["name"]
        occ = [o for o in e.get("occluders", []) if o in index]
        x0, y0, x1, y1 = index[name]["bbox"]
        r = int(e.get("reach", a.reach) * max(x1 - x0, y1 - y0))
        wx0, wy0, wx1, wy1 = max(0, x0 - r), max(0, y0 - r), min(W, x1 + r), min(H, y1 + r)
        vis_w = cache.get(name)[wy0:wy1, wx0:wx1]
        near = np.zeros_like(vis_w)
        for o in occ:
            near |= cache.get(o)[wy0:wy1, wx0:wx1]
        near &= within(vis_w, r)
        if near.any():
            ys, xs = np.nonzero(near)
            x0, y0 = min(x0, wx0 + xs.min()), min(y0, wy0 + ys.min())
            x1, y1 = max(x1, wx0 + xs.max() + 1), max(y1, wy0 + ys.max() + 1)
        for poly in e.get("extra_zone", []):
            pa = np.array(poly)
            x0, y0 = min(x0, int(pa[:, 0].min())), min(y0, int(pa[:, 1].min()))
            x1, y1 = max(x1, int(pa[:, 0].max())), max(y1, int(pa[:, 1].max()))
        pad = e.get("pad", a.pad)
        bw, bh = x1 - x0, y1 - y0
        box, kind = fit_aspect(int(x0 - pad * bw), int(y0 - pad * bh), int(x1 + pad * bw), int(y1 + pad * bh))
        tw, th = GEN_SIZES[kind]

        c_img = crop_pad(img, box, 255)
        c_vis = crop_pad(cache.get(name), box, False)
        inside = np.zeros(c_vis.shape, bool)
        inside[max(0, -box[1]):min(c_vis.shape[0], H - box[1]), max(0, -box[0]):min(c_vis.shape[1], W - box[0])] = True
        if plan.get("frames"):
            # scene borders count like the picture edge: outside the element's own frame is "cut off"
            best, best_n = None, -1
            for poly in plan["frames"]:
                fm = np.zeros(c_vis.shape, np.uint8)
                cv2.fillPoly(fm, [np.array(poly, np.int32) - [box[0], box[1]]], 1)
                n = int((fm.astype(bool) & c_vis).sum())
                if n > best_n:
                    best, best_n = fm.astype(bool), n
            if best_n > 0:
                inside &= best
        c_occ = np.zeros_like(c_vis)
        for o in occ:
            c_occ |= crop_pad(cache.get(o), box, False)
        reach = within(c_vis, r)
        zone = ((c_occ & reach) | (~inside & reach)) & ~c_vis
        for poly in e.get("extra_zone", []):
            pm = np.zeros(c_vis.shape, np.uint8)
            cv2.fillPoly(pm, [np.array(poly, np.int32) - [box[0], box[1]]], 1)
            zone |= (pm > 0) & ~c_vis
        if e.get("fill_gaps"):
            hull = np.zeros(c_vis.shape, np.uint8)
            cv2.fillConvexPoly(hull, cv2.convexHull(cv2.findNonZero(c_vis.astype(np.uint8))), 1)
            assigned = np.zeros_like(c_vis)
            for other in index:
                ob = index[other]["bbox"]
                if ob[2] > box[0] and ob[0] < box[2] and ob[3] > box[1] and ob[1] < box[3]:
                    assigned |= crop_pad(cache.get(other), box, False)
            zone |= (hull > 0) & ~c_vis & ~assigned

        target = np.empty_like(c_img)
        target[:] = GREY
        target[zone] = MAGENTA
        target[c_vis] = c_img[c_vis]
        f = P.sticker_dir(name)
        f.mkdir(parents=True, exist_ok=True)
        Image.fromarray(target).resize((tw, th), Image.LANCZOS).save(f / "input_target.png")
        # JPEG reference: large PNG attachments have stalled headless generation
        Image.fromarray(c_img).resize((tw, th), Image.LANCZOS).save(f / "input_context.jpg", quality=88)
        Image.fromarray(zone.astype(np.uint8) * 255).save(f / "zone.png")
        Image.fromarray(c_vis.astype(np.uint8) * 255).save(f / "visible.png")
        Image.fromarray(c_img).save(f / "crop_full.png")
        write_json(f / "crop.json", {"box_in_image": box, "gen_size": [tw, th], "element": name, "occluders": occ,
                                     "method": e.get("method", "complete")})

        is_char = e.get("kind") == "character"
        hidden = zone.sum() > 0.01 * c_vis.sum()
        noun = "character" if is_char else "object"
        text = e.get("text")
        fields = dict(
            noun=noun, pose="pose" if is_char else "perspective", desc=e["desc"], style=style,
            zone_line=("The flat MAGENTA areas mark where parts of it are hidden in the original: other things stand in front of it there, "
                       "or the picture or scene border cuts it off. The magenta shapes are only holes, they are NOT objects to be drawn."
                       if hidden else "The subject is almost fully visible."),
            hidden_line=("Draw the hidden parts only inside the magenta areas, so that the whole subject is complete; "
                         "leave magenta empty where the subject does not extend." if hidden
                         else "Redraw it cleanly as a complete standalone sticker without changing anything."),
            kind_line=("The body must be anatomically continuous and believable for the pose." if is_char
                       else "Keep its construction and perspective consistent."),
            zone_short=("Magenta marks where parts of it are hidden behind other things or cut off by the picture or scene border; "
                        "magenta is a hole, not an object." if hidden else ""),
            hidden_short="Draw its hidden parts only inside the magenta area." if hidden else "Redraw it cleanly as a standalone sticker.",
            notes=(" " + e["notes"]) if e.get("notes") else "",
            text_rule="" if text else ", no text",
            text_line=(f"Text: keep the text on it exactly as in the original: {text}. Do not add other text.\n" if text else ""),
        )
        (f / "spec.txt").write_text(LONG.format(**fields), encoding="utf-8")
        (f / "spec_short.txt").write_text(SHORT.format(**fields), encoding="utf-8")
        if e.get("method") == "peel":
            hole = grow(zone, 6) & ~c_vis
            sc = c_img.copy()
            sc[hole] = MAGENTA
            Image.fromarray(sc).resize((tw, th), Image.LANCZOS).save(f / "input_scene.png")
            (f / "spec_scene.txt").write_text(SCENE.format(**fields), encoding="utf-8")
            (f / "spec_peel.txt").write_text(PEEL.format(**fields), encoding="utf-8")
        print(name, kind, box, "hidden/visible=%.2f" % (zone.sum() / max(1, c_vis.sum())), e.get("method", "complete"))


if __name__ == "__main__":
    main()
