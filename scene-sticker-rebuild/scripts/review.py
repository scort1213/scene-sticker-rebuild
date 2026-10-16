#!/usr/bin/env python3
"""Independent review of finished stickers and of the board.

Each review is a separate `codex exec` run that sees only the item and the original
around it (no context from the main session) and answers with JSON. The result goes to
stdout (one JSON line per item) so the session that ran the script gets it back
directly, and to review.json / qa/review_summary.json.

On "fail" a retry spec is written next to the item: the generation spec plus the
reviewer's problems and fix instructions. Regenerate with it, re-evaluate, review again.
generate.py does this automatically (up to --rounds retries).

  python review.py --project P stickers [names...]     -> stickers/<name>/review.json, spec_retry.txt
  python review.py --project P board                   -> board/review.json, board/global/spec_retry.txt
Exit code 0 when everything reviewed passed, 2 when something failed review,
4 on rate limit/quota, 1 on other errors.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

from codex_imagegen import NET_RE, RATE_RE, _kill_tree
from common import Project, write_json

Image.MAX_IMAGE_PIXELS = None

CLIENT_RULES = """每个物件单独打开都必须完整可用，被遮挡的部分要补全，不能有缺口、断线、残片或邻近物件残留。
完整素材优先，不能为了贴回原图而把物件切坏。"""

ISSUE_TYPES = ["gap", "straight_cut", "broken_line", "fragment", "structure", "identity",
               "leftover", "invented", "artifact", "other"]
SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "issues": {"type": "array", "items": {
            "type": "object",
            "properties": {"type": {"type": "string", "enum": ISSUE_TYPES},
                           "where": {"type": "string"}, "problem": {"type": "string"}, "fix": {"type": "string"}},
            "required": ["type", "where", "problem", "fix"], "additionalProperties": False}},
    },
    "required": ["verdict", "issues"], "additionalProperties": False,
}

HEAD = """You are an independent reviewer. You did not make the images. Do not run commands, do not read or
write files, do not generate images. Look at the attached images and reply only with JSON matching the schema.

Client requirements (verbatim):
{rules}
"""

STICKER_PROMPT = HEAD + """
Image 1 = one finished sticker on its own. The flat blue is transparent background, not part of the sticker.
Image 2 = the original illustration around this object. There, parts of the object may be hidden behind other
things or cut off by the picture or scene border; the sticker must show those parts completed.
The sticker is: {desc}{text}

Fail the sticker if Image 1 shows any of these:
1. gap - a missing part, bite, notch, dent or hole in the object, usually where something stood in front of it in
   Image 2 (a bitten basket bottom, a missing leg or foot, a dented edge). A hidden part left uncompleted is a gap.
2. straight_cut - an edge of the object cut off by a straight line (picture border, scene border, canvas edge)
   instead of its natural shape.
3. broken_line - an outline or a structural part (rail, post, leg, frame, handle, string, stem) interrupted or
   ending abruptly.
4. fragment - stray pieces, specks or remnants of other objects or of the background attached to the sticker.
5. structure - extra, duplicated or missing parts, a wrong count, or parts in the wrong place compared with Image 2.
6. identity - not the same object as in Image 2 (different design, colours or style).
Ignore small differences in fine detail that come from redrawing, soft edges, and openings that are simply
transparent. For every problem give type, where (position on the sticker in plain words, e.g. "bottom centre"),
problem, and fix (a concrete instruction for redrawing, e.g. "complete the basket bottom as one smooth closed
curve"). verdict is "pass" only when there is no problem.
"""

BOARD_PROMPT = HEAD + """
Image 1 = the empty background board of a scene sticker book, redrawn as a whole. Image 2 = the original illustration.
The board must contain only: {keep}
Everything else was removed and must be completely gone: {removed}

Fail the board if Image 1 shows any of these:
1. leftover - a removed character or object, or any part, piece, outline, shadow or remnant of one.
2. invented - something that is not part of what the board must contain (furniture, plants, objects, text...).
3. structure - walls, floors, ground lines, doors, windows, steps or terrain not where they are in Image 2, or distorted.
4. artifact - blotches, smears, seams or broken patterns.
Ignore small differences in fine detail from redrawing. For every problem give type, where (position in plain
words, e.g. "lower left, in front of the school door"), problem, and fix (a concrete instruction for redrawing the
whole board). verdict is "pass" only when there is no problem.
"""

RETRY_HEAD = """

=== REVIEW OF THE PREVIOUS ATTEMPT ===
An independent reviewer checked the previous attempt against the client requirements:
{rules}
It found these problems. This attempt must fix every one of them while keeping everything else as specified above:
"""


def codex_review(prompt: str, images: list[Path], timeout: int = 300, stall: int = 150) -> dict:
    """One headless Codex run that answers with JSON (no tools, no image generation)."""
    work = Path(tempfile.mkdtemp(prefix="sticker_review_"))
    schema_path, out_path = work / "schema.json", work / "answer.json"
    schema_path.write_text(json.dumps(SCHEMA), encoding="utf-8")
    exe = shutil.which("codex") or "codex"
    cmd = [exe, "exec", "--json", "--skip-git-repo-check", "-s", "read-only", "-C", str(work),
           "--output-schema", str(schema_path), "-o", str(out_path)]
    for p in images:
        cmd += ["-i", str(Path(p).resolve())]
    cmd += ["--", "-"]
    kw = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, text=True,
              encoding="utf-8", errors="replace")
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kw)
    proc.stdin.write(prompt)
    proc.stdin.close()
    lines, err = [], []
    threading.Thread(target=lambda: lines.extend(proc.stdout), daemon=True).start()
    threading.Thread(target=lambda: err.extend(proc.stderr), daemon=True).start()
    t0, seen, last = time.time(), 0, time.time()
    reason = "exited"
    while proc.poll() is None:
        time.sleep(1)
        if len(lines) != seen:
            seen, last = len(lines), time.time()
        if time.time() - last > stall:
            reason = "stall"; break
        if time.time() - t0 > timeout:
            reason = "timeout"; break
    _kill_tree(proc)
    time.sleep(0.3)
    stderr = "".join(err)[-3000:]
    text = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
    shutil.rmtree(work, ignore_errors=True)
    answer = None
    if text.strip():
        try:
            answer = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                try:
                    answer = json.loads(m.group(0))
                except json.JSONDecodeError:
                    answer = None
    if answer and answer.get("verdict") in ("pass", "fail"):
        return {"status": "ok", **answer}
    if RATE_RE.search(stderr + "".join(lines)[-20000:]):
        return {"status": "rate_limit", "detail": stderr[-400:]}
    if reason == "stall":
        return {"status": "stall", "detail": stderr[-400:]}
    if NET_RE.search(stderr):
        return {"status": "network", "detail": stderr[-400:]}
    return {"status": "error", "detail": (stderr or text)[-400:]}


def call_review(prompt, images):
    r = codex_review(prompt, images)
    if r["status"] in ("network", "stall"):
        time.sleep(30)
        r = codex_review(prompt, images)
    return r


def on_blue(rgba: Image.Image, max_side=1024) -> Image.Image:
    bb = rgba.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox() or (0, 0, rgba.width, rgba.height)
    m = int(0.06 * max(bb[2] - bb[0], bb[3] - bb[1]))
    bb = (max(0, bb[0] - m), max(0, bb[1] - m), min(rgba.width, bb[2] + m), min(rgba.height, bb[3] + m))
    c = rgba.crop(bb)
    bg = Image.new("RGBA", c.size, (90, 140, 220, 255))
    bg.alpha_composite(c)
    bg = bg.convert("RGB")
    bg.thumbnail((max_side, max_side), Image.LANCZOS)
    return bg


def write_retry_spec(base_spec: Path, issues: list[dict], out: Path) -> None:
    if not base_spec.exists():
        print(f"note: {base_spec} not found, no retry spec written", file=sys.stderr)
        return
    lines = [f"- [{i['type']}] {i['where']}: {i['problem']} -> FIX: {i['fix']}" for i in issues]
    out.write_text(base_spec.read_text(encoding="utf-8") + RETRY_HEAD.format(rules=CLIENT_RULES) + "\n".join(lines) + "\n",
                   encoding="utf-8")


def _record(path: Path, entry: dict) -> list:
    hist = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    hist.append(entry)
    write_json(path, hist)
    return hist


def _summary(P: Project, key: str, entry: dict) -> None:
    p = P.p("qa", "review_summary.json")
    s = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    s[key] = {"verdict": entry["verdict"], "round": entry["round"], "issues": entry.get("issues", [])}
    write_json(p, s)


def review_sticker(P: Project, name: str) -> dict:
    f = P.sticker_dir(name)
    e = next(x for x in P.elements() if x["name"] == name)
    work = f / "review"
    work.mkdir(exist_ok=True)
    on_blue(Image.open(f / "sticker.png").convert("RGBA")).save(work / "sticker_on_blue.jpg", quality=90)
    ctx = Image.open(f / "crop_full.png").convert("RGB")
    ctx.thumbnail((1024, 1024), Image.LANCZOS)
    ctx.save(work / "original_area.jpg", quality=90)
    text = f"\nIts text must read exactly: {e['text']}" if e.get("text") else ""
    prompt = STICKER_PROMPT.format(rules=CLIENT_RULES, desc=e["desc"], text=text)
    r = call_review(prompt, [work / "sticker_on_blue.jpg", work / "original_area.jpg"])
    if r["status"] != "ok":
        return {"name": name, **r}
    issues = list(r.get("issues", []))
    metrics = json.loads((f / "metrics.json").read_text(encoding="utf-8")) if (f / "metrics.json").exists() else {}
    if metrics.get("coverage") is not None and metrics["coverage"] < 0.8:
        issues.append({"type": "structure", "where": "whole object",
                       "problem": f"the sticker covers only {metrics['coverage']:.0%} of the object's visible area in the "
                                  "original: it is drawn too small, too short or in the wrong place",
                       "fix": "draw the object at its full original size and position so it covers everything that is "
                              "visible of it in the original"})
    if metrics.get("clipped"):
        issues.append({"type": "straight_cut", "where": "canvas edge",
                       "problem": "the object runs into the edge of the canvas and is cut there",
                       "fix": "draw the whole object smaller inside the canvas, keeping it at the same place"})
    verdict = "fail" if issues else "pass"
    hist = json.loads((f / "review.json").read_text(encoding="utf-8")) if (f / "review.json").exists() else []
    entry = {"round": len(hist), "verdict": verdict, "issues": issues, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    _record(f / "review.json", entry)
    _summary(P, name, entry)
    if verdict == "fail":
        base = f / ("spec_peel.txt" if e.get("method") == "peel" else "spec.txt")
        write_retry_spec(base, issues, f / "spec_retry.txt")
    return {"name": name, "status": "ok", **entry}


def review_board(P: Project) -> dict:
    plan = P.plan()
    b = plan.get("board", {})
    work = P.p("board", "review")
    work.mkdir(parents=True, exist_ok=True)
    for src, dst in [(P.p("board", "state.png"), "board.jpg"), (P.source, "original.jpg")]:
        im = Image.open(src).convert("RGB")
        im.thumbnail((1536, 1536), Image.LANCZOS)
        im.save(work / dst, quality=90)
    keep = b.get("keep", "the building shell only: walls, ceiling, floor, doors and windows; ground, sky, water, distant scenery")
    removed = b.get("removed") or ", ".join(e["desc"].split(",")[0] for e in P.elements())
    r = call_review(BOARD_PROMPT.format(rules=CLIENT_RULES, keep=keep, removed=removed),
                    [work / "board.jpg", work / "original.jpg"])
    if r["status"] != "ok":
        return {"name": "board", **r}
    issues = list(r.get("issues", []))
    verdict = "fail" if issues else "pass"
    hist = json.loads(P.p("board", "review.json").read_text(encoding="utf-8")) if P.p("board", "review.json").exists() else []
    entry = {"round": len(hist), "verdict": verdict, "issues": issues, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    _record(P.p("board", "review.json"), entry)
    _summary(P, "board", entry)
    if verdict == "fail":
        g = P.p("board", "global")
        write_retry_spec(g / "spec.txt", issues, g / "spec_retry.txt")
    return {"name": "board", "status": "ok", **entry}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("what", choices=["stickers", "board"])
    ap.add_argument("names", nargs="*")
    a = ap.parse_args()
    P = Project(a.project)
    results = []
    if a.what == "board":
        results.append(review_board(P))
    else:
        names = a.names or [e["name"] for e in P.elements() if (P.sticker_dir(e["name"]) / "sticker.png").exists()]
        for n in names:
            r = review_sticker(P, n)
            results.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
            if r["status"] == "rate_limit":
                break
    if a.what == "board":
        print(json.dumps(results[0], ensure_ascii=False))
    if any(r["status"] == "rate_limit" for r in results):
        sys.exit(4)
    if any(r["status"] != "ok" for r in results):
        sys.exit(1)
    sys.exit(2 if any(r.get("verdict") == "fail" for r in results) else 0)


if __name__ == "__main__":
    main()
