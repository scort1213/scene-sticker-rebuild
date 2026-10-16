#!/usr/bin/env python3
"""Run one Codex built-in image_gen call headlessly (from another agent or a script)
and copy its output. Not needed when the workflow itself runs inside Codex: there,
call the built-in image_gen tool directly.

Behaviour learned in practice:
- the prompt is written to stdin (`codex exec ... -- -`) and stdin is then closed:
  `codex exec` waits for EOF on a piped stdin, and on Windows `codex` is a .cmd shim
  through which a long multi-line argument would be mangled by cmd.exe.
- outputs are found by this run's own thread id under $CODEX_HOME/generated_images/,
  never by "newest file", so other Codex sessions generating at the same time are safe.
- the image is saved before the agent's closing reply, which can hang: the session is
  stopped as soon as the image file exists and its size is stable.
- a call that produces no output at all for --stall seconds is reported as a stall
  (exit 3) so the caller can retry once with a shorter prompt.
- rate-limit / quota messages are reported as exit 4; never retry them automatically.
- transient network errors ("error sending request", "transport channel closed") are
  reported as exit 5; callers may retry once after a short pause.
Nothing under $CODEX_HOME is modified or deleted.

  python codex_imagegen.py --spec spec.txt --image target.png --image ref.jpg --out gen.png
Exit codes: 0 ok, 1 error/no image, 3 stall, 4 rate limit or quota, 5 network error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
GEN_ROOT = CODEX_HOME / "generated_images"
RATE_RE = re.compile(r"rate.?limit|usage limit|quota|too many requests|\b429\b", re.I)
NET_RE = re.compile(r"network error|error sending request|transport channel closed|connection (reset|refused|closed)|timed out", re.I)

WRAPPER = """You are being run headlessly to produce exactly one image.
Use your built-in image_gen tool exactly once, following the specification below.
Do not run shell commands, do not read or write any files, and do not use any other tool.
{image_roles}
When the image has been generated, reply with the single word DONE.

=== IMAGE SPECIFICATION ===
{spec}
"""


def _kill_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue


def run_codex(spec_text: str, images: list[str], out: str | Path, timeout: int = 900, stall: int = 150,
              workdir: str | None = None) -> dict:
    """Returns {"status": ok|stall|rate_limit|error, "outputs": [...], "thread_id": ..., "record": path}."""
    roles = ""
    if images:
        roles = "Attached images, in order: " + ", ".join(f"Image {i + 1} = {Path(p).name}" for i, p in enumerate(images)) + "."
    prompt = WRAPPER.format(image_roles=roles, spec=spec_text)
    workdir = Path(workdir or tempfile.mkdtemp(prefix="codex_imagegen_"))
    workdir.mkdir(parents=True, exist_ok=True)
    exe = shutil.which("codex") or "codex"
    cmd = [exe, "exec", "--json", "--skip-git-repo-check", "-s", "read-only", "-C", str(workdir)]
    for p in images:
        cmd += ["-i", str(Path(p).resolve())]
    cmd += ["--", "-"]                    # "-": read the prompt from stdin
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    record = {"cmd": cmd, "prompt": prompt, "images": [str(p) for p in images], "started": time.time()}

    kw = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, text=True,
              encoding="utf-8", errors="replace")
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kw)
    proc.stdin.write(prompt)
    proc.stdin.close()
    events, err, state = [], [], {"thread_id": None}

    def read_out():
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(ev)
            if ev.get("type") == "thread.started":
                state["thread_id"] = ev.get("thread_id")

    threading.Thread(target=read_out, daemon=True).start()
    threading.Thread(target=lambda: err.extend(proc.stderr), daemon=True).start()

    t0, last_sizes, reason = time.time(), None, "exited"
    seen, last_change = 0, time.time()
    while proc.poll() is None:
        time.sleep(2)
        if len(events) != seen:
            seen, last_change = len(events), time.time()
        if stall and not last_sizes and time.time() - last_change > stall:
            reason = "stall"; break
        tid = state["thread_id"]
        if tid and (GEN_ROOT / tid).is_dir():
            sizes = tuple(p.stat().st_size for p in sorted((GEN_ROOT / tid).glob("*.png")))
            if sizes and sizes == last_sizes:
                reason = "image_ready"; break
            last_sizes = sizes
        if time.time() - t0 > timeout:
            reason = "timeout"; break
    _kill_tree(proc)
    time.sleep(0.5)
    tid = state["thread_id"]
    record.update(returncode=proc.returncode, stop_reason=reason, thread_id=tid,
                  stderr_tail="".join(err)[-4000:], events=events, finished=time.time())

    copied = []
    if tid and (GEN_ROOT / tid).is_dir():
        pngs = sorted((GEN_ROOT / tid).glob("*.png"), key=lambda p: p.stat().st_mtime)
        for i, src in enumerate(pngs):
            dst = out if i == 0 else out.with_name(f"{out.stem}_{i + 1}{out.suffix}")
            shutil.copy2(src, dst)
            copied.append({"src": str(src), "dst": str(dst)})
    record["outputs"] = copied
    rec_path = out.with_suffix(".codex.json")
    rec_path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")

    if copied:
        status = "ok"
    elif RATE_RE.search(record["stderr_tail"] + json.dumps(events)[-20000:]):
        status = "rate_limit"
    elif reason == "stall":
        status = "stall"
    elif NET_RE.search(record["stderr_tail"]):
        status = "network"
    else:
        status = "error"
    return {"status": status, "stop": reason, "outputs": copied, "thread_id": tid, "record": str(rec_path),
            "stderr_tail": record["stderr_tail"][-600:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="text file with the image specification")
    ap.add_argument("--image", action="append", default=[], help="input image (repeatable, order = Image 1, 2, ...)")
    ap.add_argument("--out", required=True, help="output PNG path (suffix _2, _3 if several)")
    ap.add_argument("--workdir", default=None, help="empty scratch dir used as Codex cwd (default: a new temp dir)")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--stall", type=int, default=150, help="seconds without any Codex output before giving up; 0 = off")
    a = ap.parse_args()
    r = run_codex(Path(a.spec).read_text(encoding="utf-8"), a.image, a.out, a.timeout, a.stall, a.workdir)
    print(json.dumps({k: r[k] for k in ("status", "stop", "thread_id", "outputs")}, ensure_ascii=False))
    sys.exit({"ok": 0, "stall": 3, "rate_limit": 4, "network": 5}.get(r["status"], 1))


if __name__ == "__main__":
    main()
