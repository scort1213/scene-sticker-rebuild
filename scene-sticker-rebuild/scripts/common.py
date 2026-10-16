"""Shared project layout and helpers for the scene-sticker-rebuild scripts.

Project layout (all paths relative to the project root):
  source/original.*      untouched copy of the input
  source/srgb.png        working copy in sRGB (all scripts read this)
  source/grid/           gridded preview tiles for choosing coordinates
  plan.json              element list, occluders, descriptions (see references/plan.md)
  segment/prompts.json   SAM prompts; segment/raw/<name>.png raw masks
  masks/<name>.png       final non-overlapping visible masks; masks/index.json
  stickers/<name>/       per-element inputs, specs, generation and evaluation
  board/                 hole mask, global fill, refine tiles, state.png (current board)
  recompose/             method-B recomposition, pieces, layout
  deliver/               exported stickers, pieces, board, layout, previews
  logs/                  generation log
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageFont

Image.MAX_IMAGE_PIXELS = None

# Windows consoles may not be UTF-8: never crash on printing Chinese names
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SAM_CKPT = Path(os.environ.get("SAM2_CKPT", SKILL_DIR / "models" / "sam2.1_hiera_base_plus.pt"))
DEFAULT_SAM_CFG = os.environ.get("SAM2_CFG", "configs/sam2.1/sam2.1_hiera_b+.yaml")
GEN_SIZES = {"landscape": (1536, 1024), "portrait": (1024, 1536), "square": (1024, 1024)}
GREY = (200, 200, 200)
MAGENTA = (255, 0, 255)


class Project:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def p(self, *parts) -> Path:
        return self.root.joinpath(*parts)

    @property
    def source(self) -> Path:
        return self.p("source", "srgb.png")

    def plan(self) -> dict:
        return json.loads(self.p("plan.json").read_text(encoding="utf-8"))

    def all_elements(self) -> list[dict]:
        return self.plan()["elements"]

    def elements(self) -> list[dict]:
        """Sticker elements; entries with "merge_into" are part of their host sticker."""
        return [e for e in self.all_elements() if not e.get("merge_into")]

    def element(self, name: str) -> dict:
        for e in self.elements():
            if e["name"] == name:
                return e
        raise KeyError(f"{name} is not in plan.json")

    def index(self) -> dict:
        return json.loads(self.p("masks", "index.json").read_text(encoding="utf-8"))

    def mask_path(self, name: str) -> Path:
        return self.p("masks", f"{name}.png")

    def sticker_dir(self, name: str) -> Path:
        return self.p("stickers", name)

    def size(self) -> tuple[int, int]:
        with Image.open(self.source) as im:
            return im.size  # (W, H)


def load_mask(path: str | Path) -> np.ndarray:
    return np.array(Image.open(path).convert("L")) > 127


def save_mask(path: str | Path, m: np.ndarray) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((m.astype(np.uint8) * 255)).save(path)


def load_rgb(path: str | Path) -> np.ndarray:
    return np.array(Image.open(path).convert("RGB"))


def within(m: np.ndarray, r: float) -> np.ndarray:
    """Pixels within distance r of mask m (distance transform: fast for large r)."""
    return cv2.distanceTransform((~m).astype(np.uint8), cv2.DIST_L2, 5) <= r


def grow(m: np.ndarray, r: int) -> np.ndarray:
    if r > 20:                       # large elliptic kernels are very slow on big images
        return within(m.astype(bool), r)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    return cv2.dilate(m.astype(np.uint8), k) > 0


def fit_aspect(x0: int, y0: int, x1: int, y1: int) -> tuple[list[int], str]:
    """Grow the shorter side of a box to the nearest supported generation aspect."""
    w, h = x1 - x0, y1 - y0
    kind = "landscape" if w / h > 1.25 else "portrait" if w / h < 0.8 else "square"
    tw, th = GEN_SIZES[kind]
    if w / h < tw / th:
        nw = int(round(h * tw / th)); x0 -= (nw - w) // 2; x1 = x0 + nw
    else:
        nh = int(round(w * th / tw)); y0 -= (nh - h) // 2; y1 = y0 + nh
    return [int(x0), int(y0), int(x1), int(y1)], kind


def crop_pad(arr: np.ndarray, box, fill) -> np.ndarray:
    """Crop box from arr; parts outside the image are filled with `fill`."""
    x0, y0, x1, y1 = box
    H, W = arr.shape[:2]
    out = np.full((y1 - y0, x1 - x0) + arr.shape[2:], fill, dtype=arr.dtype)
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    if sx0 < sx1 and sy0 < sy1:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = arr[sy0:sy1, sx0:sx1]
    return out


def bbox(m: np.ndarray) -> list[int]:
    ys, xs = np.nonzero(m)
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def font(size: int):
    candidates = [
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except OSError:
                continue
    return ImageFont.load_default()


def torch_device() -> str:
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        return "mps"
    return "cpu"


def sam_predictor(ckpt: str | Path = DEFAULT_SAM_CKPT, cfg: str = DEFAULT_SAM_CFG):
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    if not Path(ckpt).exists():
        raise SystemExit(f"SAM checkpoint not found: {ckpt} (see references/setup.md)")
    return SAM2ImagePredictor(build_sam2(cfg, str(ckpt), device=torch_device()))


def write_json(path: str | Path, data) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
