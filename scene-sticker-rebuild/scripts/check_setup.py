#!/usr/bin/env python3
"""Check that this machine can run the skill (run once after installing, on any OS).

  python check_setup.py            (with the skill's .venv Python)
Checks: Python version, packages, SAM 2.1 checkpoint loads and segments a test image,
compute device, a CJK font, Unicode file paths, PSD writing with transparency, and the
Codex CLI (needed for the independent review in review.py, and for generate.py).
Prints OK / FAIL per item.
"""
import importlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

results = []


def check(name, fn):
    try:
        info = fn()
        results.append(("OK", name, info or ""))
    except Exception as e:  # noqa: BLE001 - report everything
        results.append(("FAIL", name, f"{type(e).__name__}: {e}"))


def py_version():
    v = sys.version_info
    if not ((3, 10) <= (v.major, v.minor) <= (3, 12)):
        raise RuntimeError(f"Python {v.major}.{v.minor}; use 3.10-3.12")
    return f"{platform.system()} {platform.machine()}, Python {v.major}.{v.minor}.{v.micro}"


def packages():
    out = []
    for mod in ["PIL", "numpy", "cv2", "scipy", "torch", "torchvision", "sam2", "psd_tools"]:
        m = importlib.import_module(mod)
        out.append(f"{mod} {getattr(m, '__version__', '')}".strip())
    return ", ".join(out)


def device():
    sys.path.insert(0, str(Path(__file__).parent))
    from common import torch_device
    return torch_device()


def sam():
    import numpy as np
    sys.path.insert(0, str(Path(__file__).parent))
    from common import DEFAULT_SAM_CKPT, sam_predictor
    pred = sam_predictor()
    img = np.full((256, 256, 3), 230, np.uint8)
    img[80:180, 60:200] = (200, 60, 60)
    pred.set_image(img)
    masks, scores, _ = pred.predict(point_coords=np.array([[130, 130]], np.float32),
                                    point_labels=np.array([1], np.int32), multimask_output=False)
    area = int((masks[0] > 0.5).sum())
    if not 9000 < area < 20000:
        raise RuntimeError(f"unexpected test mask area {area}")
    return f"{DEFAULT_SAM_CKPT.name} loads and segments"


def cjk_font():
    sys.path.insert(0, str(Path(__file__).parent))
    from common import font
    f = font(20)
    name = getattr(f, "path", None)
    if not name:
        raise RuntimeError("no CJK font found; labels on review sheets will be unreadable")
    return name


def unicode_paths_and_psd():
    import numpy as np
    from PIL import Image
    from psd_tools import PSDImage
    from psd_tools.api.layers import PixelLayer
    from psd_tools.constants import Compression
    d = Path(tempfile.mkdtemp(prefix="贴纸检查_"))
    p = d / "测试图.png"
    Image.new("RGBA", (64, 64), (255, 0, 0, 0)).save(p)
    Image.open(p).load()
    psd = PSDImage.new("RGBA", (64, 64))
    im = Image.new("RGBA", (32, 32), (255, 0, 0, 0))
    im.paste((255, 0, 0, 255), (8, 8, 24, 24))
    layer = PixelLayer.frompil(im, psd, "layer", 4, 4, Compression.RLE)
    layer.name = "角色01_测试"
    psd.append(layer)
    psd.save(str(d / "测试.psd"))
    chk = PSDImage.open(str(d / "测试.psd"))
    a = np.asarray(chk[0].topil().convert("RGBA"))[..., 3]
    if chk[0].name != "角色01_测试" or not (a == 0).any():
        raise RuntimeError("PSD layer name or transparency wrong")
    shutil.rmtree(d, ignore_errors=True)
    return "Chinese paths, Chinese layer names and layer transparency OK"


def codex_cli():
    exe = shutil.which("codex")
    if not exe:
        raise RuntimeError("codex CLI not on PATH: the independent review (review.py) runs it; install it "
                           "(npm i -g @openai/codex) and log in (codex login)")
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60)
    return f"{exe} ({(out.stdout or out.stderr).strip()[:40]})"


check("python", py_version)
check("packages", packages)
check("device", device)
check("SAM 2.1", sam)
check("CJK font", cjk_font)
check("files + PSD", unicode_paths_and_psd)
check("codex CLI", codex_cli)
for status, name, info in results:
    print(f"[{status}] {name}: {info}")
hard_fail = [r for r in results if r[0] == "FAIL" and "optional" not in r[1]]
print("READY" if not hard_fail else f"NOT READY: {len(hard_fail)} problem(s) above")
sys.exit(1 if hard_fail else 0)
