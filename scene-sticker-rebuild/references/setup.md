# 安装（Windows / macOS）

## 1. 放进 Codex 的 skills 目录

| 系统 | 目录 |
|---|---|
| Windows | `%USERPROFILE%\.codex\skills\scene-sticker-rebuild\` |
| macOS | `~/.codex/skills/scene-sticker-rebuild/` |

拷贝整个 Skill 文件夹，但不要带上 `.venv`（虚拟环境不能跨电脑、跨系统用），也不要带 `projects/` 里的旧项目。模型权重 `models/sam2.1_hiera_base_plus.pt` 可以一起拷，和系统无关，能省掉下载。

如果 Codex 在 Windows 上是跑在 WSL 里的，Skill 和下面的环境都要装在 WSL 内部（Linux 路径），按 macOS/Linux 的命令装。

## 2. Python 环境

需要 Python 3.10–3.12，环境建在 Skill 目录下的 `.venv`。SKILL.md 要求用这个环境里的 Python 运行脚本：Windows 是 `.venv\Scripts\python.exe`，macOS/Linux 是 `.venv/bin/python`。

**Windows（PowerShell，在 Skill 目录下执行）**

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r scripts\requirements.txt
$env:SAM2_BUILD_CUDA = "0"
.venv\Scripts\python.exe -m pip install "git+https://github.com/facebookresearch/sam2.git"
```

- 安装 SAM 2.1 需要先装 Git for Windows。`SAM2_BUILD_CUDA=0` 表示跳过 CUDA 扩展的编译：没装 CUDA 工具链时，编译会失败或卡住。少了这个扩展，只是分割时少一步后处理，不影响结果。
- 有 NVIDIA 显卡时，先按 pytorch.org 的安装向导装好对应 CUDA 版本的 torch，再执行上面的命令，速度会快很多。没有显卡时用 CPU 也能跑完，只是分割慢一些。
- 网络要走代理时，先设置 `$env:HTTPS_PROXY`。PyTorch 安装包很大，超时了就重试。

**macOS / Linux**

```bash
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt
.venv/bin/pip install "git+https://github.com/facebookresearch/sam2.git"
```

## 3. SAM 2.1 模型

SAM 是 Meta 官方发布的分割模型，只用来抠图，不生成画面。如果没有从旧电脑拷过来，就下载 base+ 权重（约 324 MB）放到 `models/`。Windows 10 以上自带 `curl.exe`：

```bash
curl -L -C - -o models/sam2.1_hiera_base_plus.pt https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt
```

`-C -` 支持断点续传，下载中断后再执行一次即可。换模型时设置环境变量 `SAM2_CKPT`（权重路径）和 `SAM2_CFG`（对应的配置文件）。

## 4. 自检

```bash
.venv/bin/python scripts/check_setup.py          # Windows: .venv\Scripts\python.exe scripts\check_setup.py
```

逐项检查以下内容，全部 OK 时输出 READY：Python 版本、依赖包、SAM 能否加载并分割测试图、运行设备、中文字体、中文路径和中文图层名、PSD 图层透明度，以及 Codex 命令行工具。独立审核（`review.py`）要另起 `codex` 进程，所以即使在 Codex 应用里跑，命令行里也要能找到 `codex` 并且已登录（`codex login`）。

## 运行设备与资源

- 脚本按 CUDA → Apple MPS → CPU 的顺序自动选择设备。
- 万像素级的原图处理时会占用数 GB 内存，导出 60 多层的分层 PSD 时峰值约 8 GB，建议 16 GB 以上。
- 全部文件读写都用 UTF-8，中文路径、中文图层名在 Windows 上已经处理。

## 生图

- **在 Codex 中**：直接用内置 image_gen，不需要额外配置。
- **在其他代理中**：要装好 Codex CLI 并登录（`codex login`），见 [generation.md](generation.md)。提示词通过标准输入传给 `codex exec`，所以在 Windows 上 `codex` 是 `.cmd` 启动脚本也没问题。
