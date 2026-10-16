---
name: scene-sticker-rebuild
description: 把一张插画场景拆成“底板 + 完整贴纸”：角色和主要物件各成一张透明贴纸并补全被遮挡部分，底板移除全部贴纸元素并补全背后场景，贴纸按原位贴回即可复原原图。适用于场景贴纸书、拼贴书、插画拆层、遮挡补全和“底板＋完整贴纸重新生成”；生图使用 Codex 内置 image_gen。不适用于必须保留原图像素、提取原始投影的照片或电商图。
---

# 场景贴纸重建

输入一张插画（任意题材、构图、视角），输出一个分层 PSD：底板（移除了所有贴纸元素的空场景）加上每个角色和主要物件各一层完整的透明贴纸，每层都放在原图位置，并按从后往前的顺序排列。同时导出单独的贴纸 PNG、底板、摆放位置和贴回效果图。

## 核心原则

1. **锁定位置补画。** 输入里可见部分保持原位置、原大小，被挡区域标成品红，让模型在这个框架里画出完整的贴纸，生成后自动对齐回原位。不要让模型凭空单独“画出这个角色”，那样比例、位置和姿态都会变，贴不回去。
2. **遮挡关系靠判断，不靠相邻。** 每个元素的 `occluders` 只列真正挡在它前面的元素；只是挨着的元素不能当成遮挡。
3. **底板必须整张重新生成。** 全图里所有元素的区域标成品红，让模型一次画出整张空场景，整张作为底板。不保留原图像素，不拼补，不做局部修补；审核不通过也是带着意见整张重画。拼补模式只在用户明确要求保留原图像素时使用。
4. **每张贴纸单独打开都必须完整，完整优先于还原。** 客户原话：“每个物件单独打开都必须完整可用，被遮挡的部分要补全，不能有缺口、断线、残片或邻近物件残留。完整素材优先，不能为了贴回原图而把物件切坏。”贴纸永远不裁、不加蒙版；前后交错只靠图层顺序处理，顺序处理不了的保持原样，交给人在 PSD 里微调。
5. **生成后立刻独立审核。** 每张贴纸和底板生成后，交给不带主流程上下文的独立 Codex 调用审核（`review.py`），结果直接回到主流程。不通过就带着审核意见重画，最多两轮，仍不通过的列给人工。见 [review.md](references/review.md)。指标只用于筛选；没有审核或看图确认，不能说已经完成。

## 工作流程

脚本在 `scripts/`，用本 Skill 目录下 `.venv` 的 Python 运行（Windows：`.venv\Scripts\python.exe`；macOS/Linux：`.venv/bin/python`）。环境不存在或换了电脑时，按 [setup.md](references/setup.md) 安装，并先跑 `scripts/check_setup.py`，输出 READY 再开工。统一用 `--project projects/YYYYMMDD_slug` 指定项目目录（目录结构见 [common.py](scripts/common.py)，`projects/` 被 Git 忽略）。

0. **开工前先问用户**：这张图印出来的成品尺寸大约是多少（例如宽 21 cm），以及多小的东西不再单独做贴纸（默认约 1.5 cm，按面积折算的边长计算，细长的藤蔓不会被误判；用户可以改）。把答案记进 plan.json 的 `print`，第 3 步用它判断哪些元素要并入宿主。
1. **建项目**：`prepare_source.py --source 原图` 复制原图，按内嵌色彩配置转成 sRGB 工作副本（CMYK 印刷稿也适用），并输出带全分辨率坐标的网格预览图，供后续标注坐标。
2. **写 plan.json**：默认按客户标准拆，**底板只留建筑外壳**（室内：天花板、墙、地面、门窗；室外：地形、天空、水面、远景），其余全部做成贴纸。看完整张图后列出元素清单，写清每个元素的描述、挡在它前面的元素、补全方式和图上文字，以及底板保留什么、背后是什么。规则见 [plan.md](references/plan.md)。客户另定标准时，按客户的来。**元素清单先给用户确认**（拆哪些、哪些并入宿主、底板留什么），确认后再分割和生成。
3. **分割**：写 `segment/prompts.json`（框和正负点）→ `sam_segment.py` → 查看 overlay，补上漏掉的耳朵、尾巴，去掉混进来的邻居 → `merge_masks.py` 合并成互不重叠的遮罩，自动找回描边，检查 overlay 和它列出的“相邻但未判断遮挡”的元素 → `size_check.py` 按成品尺寸列出太小的元素和建议的宿主，确认后在 plan 里写 `merge_into`，并重跑 `merge_masks.py`。
4. **贴纸**：`prep_stickers.py` → `qa_sheets.py inputs`，确认品红正好覆盖被挡部分 → 逐张执行：生成（见下方“生成”）→ `eval_sticker.py` 对齐评分 → `review.py ... stickers <name>` 独立审核，不通过就用 `spec_retry.txt` 重画，再评分、再审核（最多两轮）→ 全部完成后用 `qa_sheets.py stickers` 总览一遍。失败的处理办法见 [stickers.md](references/stickers.md)。
5. **底板**：`board_masks.py` → `board_fill.py init` → 整张生成 → `global-apply` → `review.py ... board` 独立审核，不通过就用 `board/global/spec_retry.txt` 整张重画（最多两轮）。结构性问题（墙、地的位置不对）要改写 `board.behind`/`board.keep` 后整张重新生成。见 [board.md](references/board.md)。
6. **还原验收**：`recompose.py` 把完整贴纸按遮挡顺序贴回底板 → `qa_sheets.py hotspots` 查看差异最大的区域。标准见 [acceptance.md](references/acceptance.md)。
7. **交付**：`export.py` 输出分层 PSD（`拆分分层.psd`），以及贴纸 PNG、底板、摆放位置、预览图和交付说明；审核后仍未通过的项目会列在交付说明里。

## 生成

- **在 Codex 中运行**：读 `imagegen` skill，用内置 image_gen。按 spec 中的顺序用 `view_image` 载入输入图（Image 1、Image 2），提示词使用 `spec.txt` 原文，把结果复制到约定路径（如 `stickers/<name>/gen.png`）。一次调用只生成一张图。
- **在其他代理中运行**：`generate.py stickers` / `generate.py board` 通过 `codex exec` 调用 Codex 内置 image_gen。具体行为见 [generation.md](references/generation.md)。
- 生成调用一个接一个进行。调用卡住时换短提示词重试一次；遇到限流、配额不足或内容拦截，立即停止并报告，不改写请求、不换服务绕过。

## 通用性

流程不针对某一类画面。场景内容、画风、视角都写进 plan.json（`scene`、`style`、`view`、元素描述），脚本里不写死。以下情况要先确认：
- 没有深色描边的画风（厚涂、水彩）：在 plan 里设 `"outlines": false`，不用自动找回描边。
- 画面里本身有大量品红：`prepare_source.py` 会提醒，需要把标记色换成画面里没有的颜色。
- 拼补模式下的规则图案工具只适用于两色网格，其他图案只能靠整张重生成。

## 边界

- 贴纸是重画版本：轮廓、配色和姿态对齐原图，细节（褶边、蝴蝶结位置等）会有差异，不承诺与原图像素一致。需要保真时可用 `eval_sticker.py --hybrid` 输出“原像素＋补画”混合版，但边缘可能带背景碎点，必须人工检查。
- 生图输出长边约 1024–1536 像素，大图的贴纸和底板都是放大后的结果，单看偏软；高清放大不在本流程内。
- 全程在 sRGB 下处理，交付说明会写明原图的色彩模式；转换为印刷色彩不在本流程内。
- 贴纸和底板都不带投影。
- 交付时说明每张贴纸和底板是否经过视觉检查、还剩哪些已知问题；只验证了脚本运行时，不能说成视觉验收通过。

## 参考

- [plan.md](references/plan.md)：plan.json 字段、元素取舍、遮挡判断、分割提示写法
- [stickers.md](references/stickers.md)：补画与剥洋葱两种方式、提示词、失败模式与修复
- [board.md](references/board.md)：底板整张重生成、检查方法，以及可选的拼补模式工具
- [generation.md](references/generation.md)：Codex 内外两种生成方式及无界面调用的注意事项
- [review.md](references/review.md)：独立审核的标准、结果回传、重画规则
- [acceptance.md](references/acceptance.md)：验收指标、看图清单、贴回方式、交付物
- [setup.md](references/setup.md)：Windows / macOS 安装、SAM 模型、自检
- [validation.md](references/validation.md)：首次实图验证记录
