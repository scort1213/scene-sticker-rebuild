#!/usr/bin/env python3
"""Build the two release packages from this repository (standard library only).

  python3 build_release.py            -> dist/scene-sticker-rebuild-<version>-macos.zip
                                         dist/scene-sticker-rebuild-<version>-windows.zip
Both contain the same skill folder and install.py; they differ in the install guide for
Codex (INSTALL_FOR_CODEX.md) and the double-click launcher (install.command / install.bat).
File names are stored as UTF-8 and the macOS launcher keeps its executable bit.
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILL = "scene-sticker-rebuild"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
SKIP_DIRS = {".venv", "__pycache__", ".git"}


def skill_files():
    base = ROOT / SKILL
    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.name == ".DS_Store" or SKIP_DIRS & set(p.relative_to(base).parts):
            continue
        rel = p.relative_to(base)
        if rel.parts[0] in ("projects", "models") and p.name != ".gitkeep":
            continue                       # user data and model weights never ship
        yield p, f"{SKILL}/{rel.as_posix()}"


def add(z, src: Path, arc: str, executable=False):
    info = zipfile.ZipInfo.from_file(src, arc)
    info.compress_type = zipfile.ZIP_DEFLATED
    mode = 0o755 if executable else 0o644
    info.external_attr = (0o100000 | mode) << 16
    z.writestr(info, src.read_bytes())


def build(platform: str, launcher: str):
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"{SKILL}-{VERSION}-{platform}.zip"
    with zipfile.ZipFile(out, "w") as z:
        add(z, ROOT / "install.py", "install.py")
        add(z, ROOT / "packaging" / platform / "INSTALL_FOR_CODEX.md", "INSTALL_FOR_CODEX.md")
        add(z, ROOT / "packaging" / platform / launcher, launcher, executable=launcher.endswith(".command"))
        add(z, ROOT / "VERSION", "VERSION")
        for src, arc in skill_files():
            add(z, src, arc, executable=src.suffix == ".py")
    names = zipfile.ZipFile(out).namelist()
    print(f"{out.name}: {len(names)} files, {out.stat().st_size / 1024:.0f} KB")
    return out


if __name__ == "__main__":
    build("macos", "install.command")
    build("windows", "install.bat")
