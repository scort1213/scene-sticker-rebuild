#!/usr/bin/env python3
"""Install or update the scene-sticker-rebuild skill into Codex (Windows / macOS / Linux).

Standard library only, so it runs with any Python 3.10+:
  Windows:  py -3 install.py [--setup-env]
  macOS:    python3 install.py [--setup-env]

Update (the skill is already installed):
  - the old version is backed up to <CODEX_HOME>/skill_backups/ (outside skills/, so
    Codex does not see a second copy of the skill)
  - SKILL.md, agents/, references/, scripts/ and .gitignore are replaced
  - .venv/ (Python environment), models/ (SAM weights) and projects/ are kept untouched
  - new Python packages, if any, are installed into the existing .venv
New install: the skill is copied, the Python environment (.venv) is created, the
packages and SAM 2.1 are installed and the SAM weights are downloaded (skip with --no-env).
--setup-env forces the environment setup on an update as well.
Finally scripts/check_setup.py runs and its result is printed (READY = done).
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

NAME = "scene-sticker-rebuild"
MANAGED = ["SKILL.md", "agents", "references", "scripts", ".gitignore"]
KEPT = [".venv", "models", "projects"]
SAM_URL = "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt"
SAM_FILE = "sam2.1_hiera_base_plus.pt"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def say(msg):
    print(msg, flush=True)


def venv_python(dest: Path) -> Path:
    return dest / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(cmd, env=None):
    say("  $ " + " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], env=env).returncode


def pip_install(py, args, env=None):
    """pip install into the skill's .venv; falls back to uv, then to ensurepip."""
    has_pip = subprocess.run([str(py), "-m", "pip", "--version"], capture_output=True).returncode == 0
    if not has_pip and shutil.which("uv"):
        return run(["uv", "pip", "install", "-q", "--python", py] + args, env=env)
    if not has_pip:
        run([py, "-m", "ensurepip", "--upgrade"])
    return run([py, "-m", "pip", "install", "-q"] + args, env=env)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup-env", action="store_true", help="also (re)install packages and SAM on an update")
    ap.add_argument("--no-env", action="store_true", help="new install: copy files only, no environment setup")
    ap.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    ap.add_argument("--no-check", action="store_true", help="skip check_setup.py at the end")
    a = ap.parse_args()

    src = Path(__file__).resolve().parent / NAME
    if not (src / "SKILL.md").exists():
        sys.exit(f"cannot find {NAME}/SKILL.md next to install.py")
    home = Path(a.codex_home).expanduser()
    dest = home / "skills" / NAME
    updating = (dest / "SKILL.md").exists()
    say(f"{'UPDATE' if updating else 'NEW INSTALL'}: {dest}")

    if updating:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = home / "skill_backups" / f"{NAME}-{stamp}"
        backup.mkdir(parents=True, exist_ok=True)
        for item in MANAGED:
            p = dest / item
            if p.is_dir():
                shutil.copytree(p, backup / item, ignore=shutil.ignore_patterns("__pycache__"))
            elif p.exists():
                shutil.copy2(p, backup / item)
        say(f"backup of the old version: {backup}")
        for item in MANAGED:
            p = dest / item
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
    dest.mkdir(parents=True, exist_ok=True)
    for item in MANAGED:
        s = src / item
        if s.is_dir():
            shutil.copytree(s, dest / item, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
        elif s.exists():
            shutil.copy2(s, dest / item)
    for item in ("models", "projects"):
        (dest / item).mkdir(exist_ok=True)
        (dest / item / ".gitkeep").touch()
    say("skill files copied (" + ", ".join(MANAGED) + "); kept: " +
        ", ".join(k for k in KEPT if (dest / k).exists()))

    py = venv_python(dest)
    req = dest / "scripts" / "requirements.txt"
    if not py.exists() and not a.no_env:
        a.setup_env = True              # first install: build the environment automatically
    if not py.exists() and a.setup_env:
        v = sys.version_info
        if not ((3, 10) <= (v.major, v.minor) <= (3, 12)):
            sys.exit(f"Python {v.major}.{v.minor} is running this installer; the skill needs Python 3.10-3.12. "
                     "Run it with 3.12, e.g. Windows: py -3.12 install.py   macOS: python3.12 install.py")
        say("creating the Python environment (.venv) ...")
        if run([sys.executable, "-m", "venv", dest / ".venv"]) != 0:
            sys.exit("could not create .venv; install Python 3.10-3.12 and retry")
    if py.exists():
        say("installing / checking Python packages ...")
        pip_install(py, ["-r", req])
        if a.setup_env:
            env = dict(os.environ, SAM2_BUILD_CUDA="0")
            pip_install(py, ["git+https://github.com/facebookresearch/sam2.git"], env=env)
    else:
        say("no .venv yet: run install.py again without --no-env to create it (see references/setup.md)")

    model = dest / "models" / SAM_FILE
    bundled = Path(__file__).resolve().parent / SAM_FILE
    if not model.exists() and bundled.exists():
        shutil.copy2(bundled, model)
        say(f"SAM weights copied from the package: {model}")
    if not model.exists() and a.setup_env:
        say(f"downloading SAM weights (~324 MB) to {model} ...")
        tmp = model.with_suffix(".part")
        urllib.request.urlretrieve(SAM_URL, tmp)
        tmp.replace(model)
    if not model.exists():
        say(f"SAM weights missing: put {SAM_FILE} into {dest / 'models'} or run install.py again without --no-env")

    if a.no_check or not py.exists():
        say("done (environment check skipped)")
        return
    say("running the environment check ...")
    rc = run([py, dest / "scripts" / "check_setup.py"])
    say("INSTALL OK - the skill is ready; it is available from the next Codex turn" if rc == 0
        else "INSTALLED, but the environment check found problems (see the FAIL lines above)")
    sys.exit(rc)


if __name__ == "__main__":
    main()
