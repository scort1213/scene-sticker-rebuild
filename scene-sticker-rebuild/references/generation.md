# 生成方式

所有图片都由 Codex 内置的 image_gen 生成，有两种调用方式。

## 在 Codex 中

1. 读 `imagegen` skill，用内置 image_gen，不用 CLI 回退模式。
2. 每次调用前，用 `view_image` 按顺序载入该步的输入图：

| 步骤 | 输入（按顺序） | 提示词 | 结果存放 |
|---|---|---|---|
| 贴纸 complete | `input_target.png`、`input_context.jpg` | `spec.txt`（卡住时用 `spec_short.txt`） | `stickers/<name>/gen.png` |
| 贴纸 peel 第一步 | `input_scene.png` | `spec_scene.txt` | `stickers/<name>/scene.png`，另存一份 `scene_ref.jpg` |
| 贴纸 peel 第二步 | `input_target.png`、`scene_ref.jpg` | `spec_peel.txt` | `stickers/<name>/gen.png` |
| 贴纸审核后重画 | 和该贴纸第一次生成时相同 | `stickers/<name>/spec_retry.txt` | `stickers/<name>/gen.png` |
| 底板全图 | `board/global/input_target.png` | `board/global/spec.txt` | `board/global/gen.png` |
| 底板审核后重画 | `board/global/input_target.png` | `board/global/spec_retry.txt` | `board/global/gen.png` |
| 底板细化（可选，拼补模式） | `board/tile_NN/input_target.png` | 同目录 `spec.txt` | 同目录 `gen.png` |
| 局部修复（可选） | `board/local_<name>/input_target.png` | 同目录 `spec.txt` | 同目录 `gen.png` |

3. 提示词使用 spec 文件原文；需要调整时直接改 spec 文件，保证记录与实际使用一致。
4. 生成后把文件从 `$CODEX_HOME/generated_images/...` 复制到上表中的路径，再运行对应的评分或应用脚本，然后运行 `review.py` 审核（见 [review.md](review.md)）。审核本身由 `review.py` 另起一个独立的 Codex 进程完成，不在当前对话里审。

## 在其他代理中（无界面）

用 `scripts/generate.py`，它通过 `scripts/codex_imagegen.py` 调用 `codex exec`。需要先安装并登录 Codex CLI；消耗的是该账号套餐的额度，不需要 API Key。

`codex_imagegen.py` 已经处理了实测中遇到的问题：

- **提示词从标准输入传入**（`codex exec … -- -`），写完就关闭。`codex exec` 会一直等管道输入结束，不关会卡住；另外 Windows 上 `codex` 是 `.cmd` 启动脚本，多行长参数经过 cmd.exe 会被截断，走标准输入就没有这个问题。
- **按本次会话的 thread id 取图**，即 `$CODEX_HOME/generated_images/<thread_id>/`，从不取“最新的文件”。同一账号的其他 Codex 会话同时出图时，也不会取错。
- **图片落盘、大小稳定后立即结束会话**。Codex 生成完图片后的收尾回复偶尔会卡住，不必等它。会结束整个进程组，不留残留进程。
- **卡住检测**：`--stall` 秒内没有任何输出，退出码为 3。`generate.py` 会换短提示词重试一次，仍失败就停止。
- **限流和配额**：错误信息中出现 rate limit、usage limit、quota、429 时退出码为 4，`generate.py` 立即停止。不要自动重试，也不要换别的服务或改写请求去绕过。
- **网络错误**（如 “error sending request”“Transport channel closed”）：退出码为 5，`generate.py` 等 30 秒后自动重试一次；还失败就停止。先确认网络或代理可用，再从中断处继续，已经完成的元素会自动跳过。

不改动、也不删除 `$CODEX_HOME` 下的任何文件。

## 节奏

两种方式都是一次只发起一个生成调用。流程本身不设固定等待时间；如果用户因为额度或账号原因要求放慢，只在当次运行时加，不写进流程。
