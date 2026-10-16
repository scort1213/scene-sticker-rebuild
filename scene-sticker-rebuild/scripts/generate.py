#!/usr/bin/env python3
"""Headless generation runner for agents outside Codex (inside Codex, call the
built-in image_gen tool step by step instead; see references/generation.md).

One call at a time. A stalled call is retried once (stickers: with the short spec); a
transient network error is retried once after 30 s.
Every sticker, and the board, is reviewed right after it is made (review.py: an
independent Codex run that sees only the item and the original). On "fail" it is
regenerated with the reviewer's fixes added to the prompt, up to --rounds times; what
still fails is listed in qa/review_summary.json and in the delivery notes.
A rate-limit/quota message or any other failure stops the run and is reported;
nothing is retried through another prompt or service.

  python generate.py --project P stickers [names...] [--force]
  python generate.py --project P board [--refine]     (after board_fill.py init)
Progress lines go to stdout and logs/generate.log.
"""
import argparse
import json
import sys
import time

from PIL import Image

from board_fill import global_apply, tile_apply, tile_prep
from codex_imagegen import run_codex
from common import Project
from eval_sticker import evaluate
from review import review_board, review_sticker


def log(P, line):
    P.p("logs").mkdir(exist_ok=True)
    stamp = time.strftime("%H:%M:%S")
    with open(P.p("logs", "generate.log"), "a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {line}\n")
    print(f"{stamp} {line}", flush=True)


def call(P, label, spec_path, images, out, retry_spec=None, timeout=480, stall=150):
    r = run_codex(spec_path.read_text(encoding="utf-8"), [str(i) for i in images], out, timeout, stall)
    if r["status"] == "network":
        log(P, f"NETWORK {label} -> retry once in 30 s")
        time.sleep(30)
        r = run_codex(spec_path.read_text(encoding="utf-8"), [str(i) for i in images], out, timeout, stall)
    if r["status"] == "stall":
        log(P, f"STALL {label} -> retry once" + (" with short spec" if retry_spec else ""))
        r = run_codex((retry_spec or spec_path).read_text(encoding="utf-8"), [str(i) for i in images], out, timeout, stall)
    if r["status"] != "ok":
        tag = "RATE_LIMIT" if r["status"] == "rate_limit" else "FAIL"
        log(P, f"{tag} {label}: {r['status']} stop={r['stop']} thread={r['thread_id']} {r['stderr_tail'][-200:]!r}")
        log(P, "STOPPED")
        sys.exit(4 if tag == "RATE_LIMIT" else 1)
    return r


def check_review(P, r):
    if r["status"] == "rate_limit":
        log(P, f"RATE_LIMIT review {r['name']}"); log(P, "STOPPED"); sys.exit(4)
    if r["status"] != "ok":
        log(P, f"REVIEW_ERROR {r['name']}: {r['status']} {r.get('detail', '')[-200:]!r}")
        return False
    issues = "; ".join(f"{i['type']} @ {i['where']}: {i['problem']}" for i in r["issues"])
    log(P, f"REVIEW {r['verdict'].upper()} {r['name']} round {r['round']}" + (f" | {issues}" if issues else ""))
    return True


def review_sticker_loop(P, e, rounds):
    f = P.sticker_dir(e["name"])
    for rnd in range(rounds + 1):
        r = review_sticker(P, e["name"])
        if not check_review(P, r) or r["verdict"] == "pass" or rnd == rounds:
            return
        if e.get("method") == "peel":
            imgs = [f / "input_target.png", f / "scene_ref.jpg"]
        else:
            imgs = [f / "input_target.png", f / "input_context.jpg"]
        call(P, e["name"] + f" retry {rnd + 1}", f / "spec_retry.txt", imgs, f / "gen.png")
        m = evaluate(f)
        log(P, f"REDONE {m['verdict']} {e['name']} {json.dumps(m)}")


def stickers(P, names, force, rounds=2):
    els = [e for e in P.elements() if not names or e["name"] in names]
    for e in els:
        f = P.sticker_dir(e["name"])
        if not (f / "spec.txt").exists():
            log(P, f"SKIP {e['name']} (run prep_stickers.py first)"); continue
        if (f / "sticker.png").exists() and not force:
            continue
        t0 = time.time()
        if e.get("method") == "peel":
            call(P, e["name"] + " scene", f / "spec_scene.txt", [f / "input_scene.png"], f / "scene.png")
            Image.open(f / "scene.png").convert("RGB").save(f / "scene_ref.jpg", quality=88)
            call(P, e["name"], f / "spec_peel.txt", [f / "input_target.png", f / "scene_ref.jpg"], f / "gen.png")
        else:
            call(P, e["name"], f / "spec.txt", [f / "input_target.png", f / "input_context.jpg"], f / "gen.png",
                 retry_spec=f / "spec_short.txt")
        m = evaluate(f)
        log(P, f"DONE {m['verdict']} {e['name']} {time.time() - t0:.0f}s {json.dumps(m)}")
        if rounds >= 0:
            review_sticker_loop(P, e, rounds)
    log(P, "STICKERS_END")


def board(P, refine=False, rounds=2):
    g = P.p("board", "global")
    if not (g / "spec.txt").exists():
        raise SystemExit("run board_fill.py init first")
    if not P.p("board", "stage1.png").exists():
        call(P, "board global", g / "spec.txt", [g / "input_target.png"], g / "gen.png")
        global_apply(P)
        log(P, "BOARD global done")
        # the board is always redrawn as a whole: a failed review regenerates the whole board
        for rnd in range(rounds + 1 if rounds >= 0 else 0):
            r = review_board(P)
            if not check_review(P, r) or r["verdict"] == "pass" or rnd == rounds:
                break
            call(P, f"board global retry {rnd + 1}", g / "spec_retry.txt", [g / "input_target.png"], g / "gen.png")
            global_apply(P)
            log(P, f"BOARD global redone (round {rnd + 1})")
    meta = json.loads(P.p("board", "meta.json").read_text(encoding="utf-8"))
    if meta.get("mode") != "patch" and not refine:
        log(P, "BOARD_END (full regeneration; sharpening belongs to the later upscaling step)")
        return
    for i in range(len(meta["tiles"])):
        f = P.p("board", f"tile_{i:02d}")
        if (f / "applied").exists():
            continue
        if not tile_prep(P, i):
            log(P, f"BOARD tile {i} skip (no hole)"); continue
        call(P, f"board tile {i}", f / "spec.txt", [f / "input_target.png"], f / "gen.png")
        tile_apply(P, i)
        log(P, f"BOARD tile {i} done")
    log(P, "BOARD_END")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("what", choices=["stickers", "board"])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--force", action="store_true", help="regenerate stickers that already have sticker.png")
    ap.add_argument("--refine", action="store_true", help="board: also run the refine tiles (patch mode always does)")
    ap.add_argument("--rounds", type=int, default=2, help="regenerations after a failed review (-1: no review)")
    a = ap.parse_args()
    P = Project(a.project)
    if a.what == "stickers":
        stickers(P, a.names, a.force, a.rounds)
    else:
        board(P, a.refine, a.rounds)


if __name__ == "__main__":
    main()
