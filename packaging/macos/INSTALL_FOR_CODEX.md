# 安装 / 更新 scene-sticker-rebuild（macOS，给 Codex 的操作说明）

用户把这个安装包交给你，要你把 `scene-sticker-rebuild` 技能安装或更新到这台 Mac 的 Codex 里。请按下面的步骤操作。

1. 把安装包解压到一个新的临时文件夹。解压后应该有 `install.py`、`install.command`、本说明和 `scene-sticker-rebuild/` 文件夹。
2. 在解压出来的文件夹里运行：`python3 install.py`
   - **更新**（已经装过）：只替换技能文件，`.venv`、`models`、`projects` 原样保留，旧版本自动备份到 `~/.codex/skill_backups/`。
   - **首次安装**：会自动建立 Python 环境、安装依赖和 SAM 2.1、下载 SAM 模型（约 324 MB）。耗时较长，需要能访问 PyPI、GitHub 和 dl.fbaipublicfiles.com。
   - 如果提示 Python 版本不对（需要 3.10–3.12），改用 `python3.12 install.py`。没有的话，请用户先安装 Python 3.12（python.org 或 `brew install python@3.12`）。
   - 安装 SAM 2.1 需要 git。如果没有，先执行 `xcode-select --install`。
3. 脚本会写入 `~/.codex/skills/`，这个位置在工作区之外。如果被沙箱拦截，向用户申请权限后再运行。
4. 把脚本最后的输出原样告诉用户：
   - 出现 `INSTALL OK`：安装完成，技能从下一轮对话开始可用。
   - 出现 `FAIL`：逐条说明是哪一项失败，并给出 `scene-sticker-rebuild/references/setup.md` 里对应的处理办法。常见的是 `codex CLI`：需要安装命令行版 Codex（`npm i -g @openai/codex`，需要 Node.js）并执行 `codex login`。

注意：
- 不要修改其他技能，也不要删除 `scene-sticker-rebuild` 下的 `.venv`、`models`、`projects`。
- 安装完成后，可以删除临时解压的文件夹。
