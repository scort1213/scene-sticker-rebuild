# 安装 / 更新 scene-sticker-rebuild（Windows，给 Codex 的操作说明）

用户把这个安装包交给你，要你把 `scene-sticker-rebuild` 技能安装或更新到这台 Windows 电脑的 Codex 里。请按下面的步骤做。

1. 把安装包解压到一个新的临时文件夹，可以用 PowerShell：`Expand-Archive <压缩包> -DestinationPath <新文件夹>`。解压后应该看到 `install.py`、`install.bat`、本说明和 `scene-sticker-rebuild\` 文件夹。
2. 在解压后的文件夹里运行：`py -3.12 install.py`（没有 3.12 时用 `py -3 install.py`）。
   - **更新**（已经装过）：只替换技能文件。`.venv`、`models`、`projects` 原样保留，旧版本自动备份到 `%USERPROFILE%\.codex\skill_backups\`。
   - **首次安装**：会自动建立 Python 环境，安装依赖和 SAM 2.1，并下载 SAM 模型（约 324 MB）。耗时较长，需要能访问 PyPI、GitHub 和 dl.fbaipublicfiles.com。走代理时，先设置 `$env:HTTPS_PROXY`。
   - 需要 Python 3.10–3.12。电脑上没有的话，请用户先从 python.org 安装 3.12，或者 `winget install Python.Python.3.12`。
   - 安装 SAM 2.1 需要 Git for Windows（`winget install Git.Git`）。安装脚本会自动设置 `SAM2_BUILD_CUDA=0`，跳过 CUDA 扩展的编译。
3. 脚本会写入 `%USERPROFILE%\.codex\skills\`，这个目录在工作区之外。如果被沙箱拦截，先向用户申请权限，再运行。
4. 把脚本最后的输出原样告诉用户：
   - 出现 `INSTALL OK`：安装完成，技能从下一轮对话开始可用。
   - 出现 `FAIL`：逐条说明是哪一项失败，并给出 `scene-sticker-rebuild\references\setup.md` 里对应的处理办法。常见的是 `codex CLI`：独立审核需要命令行版 Codex。先安装 Node.js（`winget install OpenJS.NodeJS.LTS`），再执行 `npm i -g @openai/codex` 和 `codex login`。

注意：
- 不要修改其他技能，也不要删除 `scene-sticker-rebuild` 下的 `.venv`、`models`、`projects`。
- 如果 Codex 运行在 WSL 里，要在 WSL 内部按 Linux 的方式安装（`python3 install.py`）。
- 安装完成后，临时解压的文件夹可以删除。
