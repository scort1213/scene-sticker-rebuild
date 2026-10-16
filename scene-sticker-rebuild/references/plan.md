# plan.json 与分割

## 元素取舍

先看完整张图（`source/overview_grid.jpg` 和 `source/grid/`），再列清单。

**判断标准**：把它拿走后，这个“地方”本身（房间、店面、街道、林地）还完整吗？完整，它就是贴纸；拿走后会缺墙、缺地、缺窗、缺地形，它就属于底板。能被搬动、摆放、替换的东西一律做贴纸。底板只保留撑起这个空间的结构，也就是客户说的“只留天花板、墙和地”。

**底板保留**
- 室内：天花板（含横梁、天窗）、墙面（含墙纸、墙板、踢脚线、柱子）、地面（地板、地砖；地毯不算）、嵌在墙里的门和窗（含窗框、玻璃、窗外景色），以及砌在建筑里的固定结构（固定楼梯、壁炉、台阶、平台）。
- 室外：地形（地面、草坡、山崖、石台、小路和踏石）、水面（河、瀑布、水潭）、天空、远景（远山、远处的树林）、环境光效（萤火虫、光斑、薄雾）。
- 建筑立面一律不拆：街景里两侧房屋的墙面、店面的门窗和外墙，都算外壳。
- 窗帘随窗户保留，固定在天花板上的主灯也保留（和客户示例一致，已确认）；其他灯具都拆。

**拆成贴纸**
- 所有角色和动物，包括背影、被挡住一半、被画面边缘截断的。
- 家具和收纳：桌、椅、凳、床、沙发、柜子、货架、墙上的置物架、衣架、人台。
- 墙上和挂着的东西：挂画、地图、钟、招牌、彩旗、串灯、风铃，以及主灯以外的灯具（落地灯、台灯、路灯、吊饰灯）。
- 地面上的覆盖物和隔断：地毯、地垫、护栏、栅栏、篱笆。
- 植物：盆栽、花丛、灌木、藤蔓，以及前景和中景的树。
- 自然场景里像道具一样单独摆着的小建筑：摊位、小棚、蘑菇屋、帐篷。客户示例的户外底板里，这些都拆掉了；构成场景本身的建筑立面不拆（见上）。
- 车、桶、箱、器物和所有小摆件。

**合并规则**
- 装在容器或家具里、单独认不出来的东西，算宿主的一部分，比如书架上的书、柜里的布料、车上的线轴、盒子里的东西。
- 角色手里拿的、身上穿戴的东西（丝带卷、包、蝴蝶结）跟角色算一张。
- 放在家具上面、能单独认出来的东西（玩偶、盆栽、动物）各成一张贴纸。但印刷后太小的要并入宿主，太碎的贴纸没法用手撕贴。阈值来自开工前问用户的成品尺寸（plan 的 `print`），由 `size_check.py` 列出候选，确认后写 `merge_into`。小线轴这类零碎小件一律并入。
- 散落的小碎片（纸屑、花瓣、布头）并入它所在的表面，比如地毯、桌面；落在空地面上的，做成一张小贴纸或并入最近的物件。
- 横跨多个物件的东西（缠在架子上的丝带、搭在桌上的布）归给它主要依附的那个物件。

**其他**
- 遮挡：按外壳标准拆时，挡在贴纸前面的基本都是贴纸。底板里的结构（门框、柱子）挡在贴纸前面时，贴纸会盖住它，和原图略有不同，交付时要说明。
- 画面边缘截断的元素，贴纸要补完整，补到画面外也可以。
- 客户另定标准时（比如保留柜子），把保留范围写进 `board.keep`。用户只想先测一部分时，按区域缩小范围。

## 字段

```json
{
  "print": {"width_cm": 21, "min_sticker_cm": 1.5},
  "scene": "A cosy cat tailor shop drawn in isometric view, ...",
  "style": "cosy hand-drawn storybook illustration, warm dark-brown outlines of the same thickness, flat soft colours with gentle shading, subtle paper texture, same palette",
  "view": "isometric 3/4 view from above",
  "elements": [
    {"name": "c01_calico", "label": "裁缝三花猫", "kind": "character",
     "desc": "a calico cat dressed as a seamstress (white face with black and orange patches, pink bow, white frilled apron, brown dress), sitting and sewing",
     "occluders": ["o05_sewing_table"]},
    {"name": "o07_chair", "label": "中间椅子", "kind": "object", "method": "peel",
     "desc": "a small wooden chair with a wide rounded backrest",
     "occluders": ["c01_calico", "o05_sewing_table"],
     "notes": "The chair is empty: do not draw the cat."},
    {"name": "o09_sign", "label": "招牌小黑板", "kind": "object", "text": "新款Lolita / 和纽扣 / 在内",
     "desc": "a wooden A-frame chalkboard sign with a cat face drawing", "occluders": ["c03_bengal"]}
  ],
  "board": {
    "removed": "all the cats, the bunny, clothes racks, dress forms, the sewing table, chairs, carts, plants, the lamp post and the A-frame sign",
    "keep": "the building shell only: the floral wallpaper walls, the dark-red wooden shop frame, the checkered shop floor, the stone platform with its steps, the brick wall on the right and the cobblestone street",
    "behind": ["Walls: the cream floral wallpaper continues over the whole wall, with its baseboard along the floor", "Shop floor: the checkered floor continuing the same tile grid", "Street: cobblestones and the stone steps"]
  }
}
```

- `elements` 的顺序决定重叠像素归谁：**越靠前的越在前面**，先写前景。
- `name` 用 ASCII（文件夹名），`label` 写中文（交付文件名）。
- 可选的全局字段：`"outlines": false` 表示画风没有深色描边，合并遮罩时不找回描边。
- `"print": {"width_cm": 21, "min_sticker_cm": 1.5}`：成品尺寸（写宽或高都可以）和最小贴纸尺寸，开工前问用户。
- `"frames": [[[x,y],...], ...]`：画面里有场景边框时（场景不铺满整张图），按全图坐标写每个场景的边框多边形。元素被自己所在场景的边框截断的部分，会和被整张图边缘截断一样，标成需要补全的区域。
- 元素字段 `"merge_into": "<宿主 name>"`：这个元素太小，并入宿主贴纸，不单独生成；要在宿主的 `desc` 里写上它。
- `desc` 用英文写清可识别特征（颜色、花纹、衣服、手持物、姿态）。提示词靠它区分相邻角色；角色的尾巴、蝴蝶结等附属物要写进去。
- `occluders`：只列挡在它前面、遮住它一部分的元素。被画面边缘截断的部分会自动补，不用写。
- `method`：默认 `complete`。大部分被挡住、单独补画容易画错结构或比例的物件（被坐着的椅子、被人挡住的衣架）用 `peel`，见 [stickers.md](stickers.md)。
- `text`：图上需要原样保留的文字。
- 可选字段：`notes`（附加要求）、`reach`（遮挡搜索半径占元素尺寸的比例，默认 0.35）、`pad`、`extra_zone`（全图坐标多边形列表，手动补充的被挡区域）、`fill_gaps`（见 stickers.md，谨慎使用）、`mask`（直接指定已有的原始遮罩）。
- `board.keep` 写清底板最终只剩什么（默认是建筑外壳）；`board.behind` 按区域写清移走之后背后是什么，并明确那里什么都没有。按外壳标准拆时洞会占画面七成以上，等于重画一个空场景，所以要写清墙与地、墙与顶的交线，透视方向，以及墙纸、地面的图案。

## 分割提示

`segment/prompts.json`：

```json
{"elements": {
  "c01_calico": {"box": [5000, 5200, 6300, 7200], "pos": [[5600,5700],[5650,6400]], "neg": [[6400,6000]]},
  "o05_sewing_table": {"parts": [
     {"box": [3900, 6000, 5100, 7100], "pos": [[4500,6500]]},
     {"crop": false, "box": [3400, 6700, 5900, 8200], "pos": [[4300,7300],[5200,7600]], "neg": [[3800,7800]], "multimask": true}]}
}}
```

- 坐标从网格图读取，均为全分辨率像素。正点落在元素内部的不同部位（头、身体、尾巴），负点落在紧挨着、容易被混进来的邻居身上。
- 元素由几块组成或很长（衣架带衣服、桌子带桌布、路灯）时，用 `parts` 分段框选，结果会合并。
- 大型柜体、书架：只给一个整体框时，SAM 常常只抓到玻璃门里的内容。要分段框：柜体框架、柜顶、侧板、下柜、窗帘各一段。
- 护栏、栅栏：按每根木桩分段框，绳子单独一段。不要整片框，否则会把后面的平台、地板一起抓进来。
- 植物：在它后面的墙、砖上加负点，否则灌木会连同砖墙一起被抓进来。
- 默认在框周围的局部窗口里分割，精度更高；`"crop": false` 改用整张图作上下文，适合大物件。`"multimask": true` 让 SAM 从三个候选里挑最好的。
- 检查 overlay 时重点看四类问题：漏掉细小部件（耳朵、尾巴、手里拿的东西）；混进了邻居（另一只猫的尾巴、桌上的线轴）；把物件的底座或它所在的架子也算了进来；描边没包进来（`merge_masks.py` 会自动找回描边）。
- 漏掉的部件单独写一条提示分割出来，合并时用 `merge_masks.py --union 名称=segment/fix/部件.png` 并入。`--union` 指定的像素优先于 plan 的顺序，所以被别的元素“抢走”的部件也用它归还（例如横在猫胸前的推车把手被猫的遮罩先占了：单独分割把手，`--union` 给推车）。
- 归还后，原来占用这些像素的元素会留下一条灰缝，说明该部件挡在它前面，是互相穿插：把该部件所属元素加进它的 `occluders`。遮挡物很大时可以调小该元素的 `reach`（如 0.12），让品红只覆盖贴近的部分。
