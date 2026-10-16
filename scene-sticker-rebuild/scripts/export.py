#!/usr/bin/env python3
"""Export the deliverables after recompose.py.

deliver/
  拆分分层.psd      the main deliverable: hidden reference, board, every sticker as a layer
                   at its original position in stacking order (make_psd.py)
  贴纸/            one trimmed RGBA PNG per element, named <角色|物件><NN>_<label>.png
  底板.png         the board, same size as the source
  贴回还原.png      all stickers stacked on the board
  摆放位置.json     position (x, y, w, h in source pixels) and stacking order of every file
  贴纸一览.jpg  原图_底板_还原对比.jpg  交付说明.md
  前景片/ 底板精修片_可选/   only when recompose.py was run with --front-pieces / --board-pieces

  python export.py --project P [--no-psd]
"""
import argparse
import json
import re
import shutil

from PIL import Image, ImageDraw
import numpy as np

from common import Project, font, write_json


def safe(s):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", default="deliver")
    ap.add_argument("--no-psd", action="store_true")
    a = ap.parse_args()
    P = Project(a.project)
    D = P.p(a.out)
    L = json.loads(P.p("recompose", "layout.json").read_text(encoding="utf-8"))
    for sub, key in [("贴纸", None), ("前景片", "front_pieces"), ("底板精修片_可选", "board_pieces")]:
        if key is None or L.get(key):
            (D / sub).mkdir(parents=True, exist_ok=True)
    W, H = L["size"]
    els = {e["name"]: e for e in P.elements()}
    counters, fname = {"character": 0, "object": 0}, {}
    for e in P.elements():
        kind = "character" if e.get("kind") == "character" else "object"
        counters[kind] += 1
        fname[e["name"]] = f"{'角色' if kind == 'character' else '物件'}{counters[kind]:02d}_{safe(e.get('label', e['name']))}"

    def save_trim(src, dst, box):
        im = Image.open(src).convert("RGBA")
        bb = im.getbbox() or (0, 0, im.width, im.height)
        c = im.crop(bb)
        c.save(dst, optimize=True)
        return {"file": str(dst.relative_to(D)).replace("\\", "/"), "x": box[0] + bb[0], "y": box[1] + bb[1], "w": c.width, "h": c.height}

    place = {"image_size": [W, H], "order_back_to_front": [fname[n] for n in L["order_back_to_front"]],
             "stickers": {}, "front_pieces": [], "board_pieces": []}
    for n in L["order_back_to_front"]:
        f = P.sticker_dir(n)
        bx = json.loads((f / "crop.json").read_text(encoding="utf-8"))["box_in_image"]
        # sticker.png is on the crop canvas; its origin is box_in_image (may be outside the picture)
        info = save_trim(f / "sticker.png", D / "贴纸" / f"{fname[n]}.png", (bx[0], bx[1]))
        info["layer"] = L["order_back_to_front"].index(n)
        place["stickers"][fname[n]] = info
    for p in L["front_pieces"]:
        info = save_trim(P.p("recompose", "pieces", f"front_{p['of']}.png"), D / "前景片" / f"{fname[p['of']]}_前景片.png", p["box"])
        info["of"] = fname[p["of"]]
        place["front_pieces"].append(info)
    for p in L["board_pieces"]:
        info = save_trim(P.p("recompose", "pieces", f"board_over_{p['over']}.png"), D / "底板精修片_可选" / f"{fname[p['over']]}_底板精修片.png", p["box"])
        info["over"] = fname[p["over"]]
        place["board_pieces"].append(info)
    write_json(D / "摆放位置.json", place)
    shutil.copy2(P.p("board", "state.png"), D / "底板.png")
    shutil.copy2(P.p("recompose", "recompose.png"), D / "贴回还原.png")

    # overview sheets
    fnt = font(20)
    cells = []
    for k in place["order_back_to_front"]:
        im = Image.open(D / place["stickers"][k]["file"]); im.thumbnail((300, 300))
        a_ = np.full((350, 320, 4), 255, np.uint8)
        yy, xx = np.mgrid[0:350, 0:320]
        a_[((yy // 16 + xx // 16) % 2 == 0)] = (228, 228, 228, 255)
        c = Image.fromarray(a_); c.alpha_composite(im, ((320 - im.width) // 2, 42 + (300 - im.height) // 2))
        ImageDraw.Draw(c).text((6, 8), k, fill=(0, 0, 0), font=fnt); cells.append(c.convert("RGB"))
    cols = 8
    sheet = Image.new("RGB", (cols * 326, ((len(cells) + cols - 1) // cols) * 356), "white")
    for i, c in enumerate(cells):
        sheet.paste(c, ((i % cols) * 326, (i // cols) * 356))
    sheet.save(D / "贴纸一览.jpg", quality=88)
    tw = 1156
    th = int(H * tw / W)
    f2 = font(36)
    comp = Image.new("RGB", (3 * tw + 40, th + 60), "white")
    dr = ImageDraw.Draw(comp)
    for i, (t, p) in enumerate([("原图", P.source), ("底板", D / "底板.png"), ("贴回还原", D / "贴回还原.png")]):
        comp.paste(Image.open(p).convert("RGB").resize((tw, th), Image.LANCZOS), (i * (tw + 20), 60))
        dr.text((i * (tw + 20) + 10, 10), t, fill=(0, 0, 0), font=f2)
    comp.save(D / "原图_底板_还原对比.jpg", quality=88)

    info = json.loads(P.p("source", "info.json").read_text(encoding="utf-8")) if P.p("source", "info.json").exists() else {}
    metrics = json.loads(P.p("recompose", "metrics.json").read_text(encoding="utf-8"))
    readme = f"""# 交付说明

- 主交付：`拆分分层.psd`。最底层“原图（参考）”默认隐藏，往上是“底板”和 {len(place['stickers'])} 个贴纸图层，按从后往前的顺序排列，每层都在原图位置。
- 同样的贴纸也单独导出在 `贴纸/`（透明 PNG），位置和顺序见 `摆放位置.json`；坐标 x、y 是贴纸左上角在原图中的像素位置。
- 原图尺寸 {W}×{H}，色彩：{info.get('colour', '未知')}。全部文件为 sRGB。
- 互相穿插的地方（比如爪子搭在桌上、身体在桌后），上层贴纸会盖住下层的一小部分，和原图略有不同。
- 贴回与原图的平均色差 {metrics['mean_abs_diff']}（0–255）。贴纸和底板都是重画的，细节差异属于预期。
- 贴纸和底板由生图模型输出（长边约 1536）放大到原尺寸，单看偏软；高清放大不在本流程内。
"""
    rs = P.p("qa", "review_summary.json")
    if rs.exists():
        summ = json.loads(rs.read_text(encoding="utf-8"))
        label = {n: fname[n] for n in fname}
        label["board"] = "底板"
        done = [k for k in summ if k in label]
        failed = [(k, v) for k, v in summ.items() if k in label and v["verdict"] != "pass"]
        missing = [label[n] for n in fname if n not in summ]
        readme += f"- 独立审核：{len(done) - len(failed)} 项通过，{len(failed)} 项重画后仍未通过"
        readme += f"，{len(missing)} 项未审核（{', '.join(missing)}）。\n" if missing else "。\n"
        if failed:
            readme += "\n## 审核未通过、需要人工处理的项目\n\n"
            for k, v in failed:
                readme += f"- **{label[k]}**\n"
                for i in v["issues"]:
                    readme += f"  - {i['where']}：{i['problem']}（建议：{i['fix']}）\n"
    else:
        readme += "- 独立审核：没有审核记录（未运行 review.py），贴纸和底板的完整性未经审核。\n"
    (D / "交付说明.md").write_text(readme, encoding="utf-8")
    if not a.no_psd:
        from make_psd import build_psd
        build_psd(P, str(D.relative_to(P.root) / "拆分分层.psd"))
    print(json.dumps({"stickers": len(place["stickers"]), "front_pieces": len(place["front_pieces"]),
                      "board_pieces": len(place["board_pieces"]), "out": str(D)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
