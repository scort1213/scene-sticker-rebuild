# scene-sticker-rebuild · 场景贴纸拆分

一个 **Codex Skill**：把一张插画场景拆成“**底板 + 完整贴纸**”，交付分层 PSD。

- **底板**：整张重新生成的空场景，只保留建筑外壳。
- **贴纸**：每个角色和主要物件各一张透明 PNG，被挡住的部分会补全。
- 贴纸按原位置、从后往前叠放到底板上，可以还原出原图。

适用于场景贴纸书、拼贴书、插画拆层和遮挡补全。生图只用 Codex 内置的 image_gen，支持 **macOS** 和 **Windows**。

---

## 功能

| | |
|---|---|
| **拆得对** | 底板只留建筑外壳：室内留天花板、墙、地面、门窗（窗帘和天花板主灯也留在底板），室外留地形、天空、水面、远景，建筑立面不拆。其他都做成贴纸。太小的物件按印刷尺寸自动建议并入宿主，阈值开工前先问用户。 |
| **贴纸完整** | 每张贴纸单独打开都完整可用：被遮挡的部分补全，没有缺口、断线、残片，也没有相邻物件的残留。完整优先于还原，贴纸不裁切、不加蒙版。场景边框挡住的部分也会补全。 |
| **放得对** | 生成结果自动对齐回原位（缩放 + 平移配准），按遮挡关系排好前后顺序。前后交错的物件只靠图层顺序处理，顺序解决不了的留给人在 PSD 里微调。 |
| **底板整张重生成** | 全图里所有贴纸元素的区域一次性标出，让模型画出整张空场景，不拼补、不保留原图像素，避免接缝和残留。 |
| **自动独立审核** | 每张贴纸和底板生成后，交给一个不带主流程上下文的独立 Codex 调用，对照原图审核，结果以 JSON 自动回到主流程。不通过就带着审核意见重画，最多 2 轮；仍不通过的写进交付说明，交给人工处理。 |
| **分层 PSD** | 最底层是原图参考（默认隐藏），往上是底板和所有贴纸图层。每层带真实透明度，图层名支持中文，按从后往前排列。 |
| **通用** | 不针对某一种画面。场景、画风、视角都写在项目的 `plan.json` 里，脚本里不写死。CMYK 印刷稿会按内嵌色彩配置自动转成 sRGB 处理。 |

## 流程

```
问成品尺寸 → 准备原图 → 列元素清单（用户确认） → SAM 分割 / 合并 / 尺寸检查
   → 逐张生成贴纸 → 对齐评分 → 独立审核（不过就重画）
   → 整张生成底板 → 独立审核（不过就整张重画）
   → 贴回验收 → 导出分层 PSD
```

详细步骤见 [SKILL.md](scene-sticker-rebuild/SKILL.md)。

## 安装

到 [Releases](../../releases/latest) 下载对应系统的安装包：

| 系统 | 安装包 |
|---|---|
| macOS | `scene-sticker-rebuild-<版本>-macos.zip` |
| Windows | `scene-sticker-rebuild-<版本>-windows.zip` |

两个包里的 Skill 完全一样，区别只在安装说明和双击启动脚本。安装方式任选一种。

### 方式一：交给 Codex 安装（推荐）

把 zip 拖进 Codex 对话框，说一句：

> 按压缩包里的 INSTALL_FOR_CODEX.md 安装这个 skill

Codex 会自己解压、运行安装脚本，并把结果告诉你。看到 `INSTALL OK` 就装好了，从下一轮对话开始可以用。

### 方式二：双击安装

解压后双击启动脚本：

- **macOS**：`install.command`。第一次运行如果被系统拦截，右键 → 打开。
- **Windows**：`install.bat`

### 方式三：命令行

```bash
# macOS（在解压出来的文件夹里执行）
python3.12 install.py
```

```powershell
# Windows
py -3.12 install.py
```

### 安装脚本做了什么

- **首次安装**：
  1. 把 Skill 复制到 `~/.codex/skills/scene-sticker-rebuild/`（Windows 是 `%USERPROFILE%\.codex\skills\`）；
  2. 建立独立的 Python 环境（`.venv`），安装依赖和 SAM 2.1；
  3. 下载 SAM 2.1 base+ 模型（约 324 MB）；
  4. 最后运行环境自检。
- **更新**（已经装过）：只替换 Skill 文件。`.venv`、`models`、`projects` 原样保留，旧版本备份到 `~/.codex/skill_backups/`。所以更新时直接装新版本即可，不用重建环境。
- 参数：
  - `--no-env`：只复制文件，不建环境；
  - `--setup-env`：更新时也重新安装依赖；
  - `--codex-home <路径>`：指定 Codex 目录。

### 环境要求

| | macOS | Windows |
|---|---|---|
| Python | 3.10–3.12（推荐 3.12，`brew install python@3.12`） | 3.10–3.12（推荐 3.12，`winget install Python.Python.3.12`） |
| Git（安装 SAM 用） | `xcode-select --install` | `winget install Git.Git` |
| Codex CLI（独立审核用） | `npm i -g @openai/codex`，然后 `codex login` | 先 `winget install OpenJS.NodeJS.LTS`，再 `npm i -g @openai/codex`，然后 `codex login` |
| 运行设备 | Apple 芯片用 MPS 加速 | 有 NVIDIA 显卡时用 CUDA，没有时用 CPU 也能跑 |
| 内存 | 建议 16 GB 以上 | 建议 16 GB 以上 |

- 首次安装需要能访问 PyPI、GitHub 和 dl.fbaipublicfiles.com。走代理时先设置 `HTTPS_PROXY`。
- 即使在 Codex 应用里使用，命令行里也要能找到已登录的 `codex`，因为独立审核要另起一个 Codex 进程。
- 手动安装和排错见 [setup.md](scene-sticker-rebuild/references/setup.md)。

## 使用

在 Codex 里发一张插画，然后说：

> 使用 $scene-sticker-rebuild，把这张插画拆成分层 PSD（底板＋完整贴纸）。

Codex 会按这个顺序推进：

1. 先问成品印刷尺寸，以及多小的东西不再单独做贴纸（默认约 1.5 cm）；
2. 列出元素清单，请你确认拆哪些、哪些并入宿主、底板留什么；
3. 确认后自动跑完分割、生成、审核和导出。

## 交付物

输出在 `projects/<日期_名称>/deliver/`：

| 文件 | 说明 |
|---|---|
| `拆分分层.psd` | 主交付。包含原图参考（隐藏）、底板和全部贴纸图层 |
| `贴纸/` | 每张贴纸一个裁边后的透明 PNG，如 `角色01_xxx.png`、`物件03_xxx.png` |
| `底板.png` | 底板，和原图同尺寸 |
| `贴回还原.png` | 所有贴纸贴回底板后的效果 |
| `摆放位置.json` | 每个文件在原图中的位置（x, y, w, h）和叠放顺序 |
| `贴纸一览.jpg`、`原图_底板_还原对比.jpg` | 预览图 |
| `交付说明.md` | 元素清单、色彩模式说明，以及审核后仍未通过、需要人工处理的项目 |

## 不在范围内

以下内容需要人工处理，或不在本流程内：

- 镂空、开口里残留的背景
- 贴纸投影
- PSD 画布尺寸调整、一页多场景的专门处理
- 高清放大：生图输出长边约 1024–1536 像素，大图里的贴纸和底板单看会偏软
- 转回 CMYK
- 和原图逐像素一致：贴纸是重画的，轮廓、配色和姿态对齐原图，细节会有差异
- 照片、电商图，以及必须保留原图像素的场景

## 仓库结构

```
scene-sticker-rebuild/        Skill 本体（安装后就是 ~/.codex/skills/ 下的这个目录）
  SKILL.md                    主流程与原则
  agents/openai.yaml          Codex 中的显示名和默认提示词
  references/                 拆分规则、贴纸、底板、生成、审核、验收、安装、验证记录
  scripts/                    分割、生成、对齐、审核、贴回、导出 PSD 等脚本
install.py                    跨平台安装 / 更新脚本（只用标准库）
packaging/macos/              macOS 安装说明和 install.command
packaging/windows/            Windows 安装说明和 install.bat
build_release.py              生成两个发布包：python3 build_release.py → dist/
VERSION                       版本号
```

## 第三方组件

- [SAM 2.1](https://github.com/facebookresearch/sam2)（Meta，Apache-2.0）：分割。模型权重在安装时从 Meta 官方地址下载，不随仓库分发。
- [psd-tools](https://github.com/psd-tools/psd-tools)（MIT）：读写 PSD。
- Pillow、NumPy、OpenCV、SciPy、PyTorch：图像处理和推理。
- 生图和审核使用 OpenAI Codex 内置的 image_gen 与 `codex exec`，需要你自己的 Codex 账号。

## 更新日志

### v1.0.0（2026-10-16）

首个公开版本。

- 拆分标准：底板只留建筑外壳；小物件按印刷尺寸并入宿主，阈值开工前先问用户；场景边框也算截断，需要补全。
- 贴纸：锁定位置补画（补画 / 剥洋葱两种方式），三候选配准，贴纸碰到画布边会被标记。
- 底板：默认整张重新生成，审核不通过也整张重画。
- 新增自动独立审核 `review.py`：覆盖每张贴纸和底板，不通过时带着意见重画，最多 2 轮。
- 分层 PSD：图层带真实透明度，支持中文图层名，导出后自动重新打开检查。
- 跨平台：
  - 全程 UTF-8；
  - Windows 下通过标准输入传提示词，避免 `.cmd` 启动脚本的参数问题；
  - 首次安装自动建环境，更新时保留环境。
