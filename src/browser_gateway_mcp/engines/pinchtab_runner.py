import os
import subprocess

from browser_gateway_mcp.limits import (
    DEFAULT_MAX_CHARS,
    TIMEOUT_PINCHTAB,
    clamp_max_chars,
    truncate,
)

PINCHTAB_BIN = os.environ.get("PINCHTAB_BIN", "pinchtab")

# ★2026-08-06：pinchtab 真实命令是 snap / eval，旧 schema 写成了 snapshot / evaluate。
#
# 说明（实测确认）：走 MCP 调用时，这张别名表其实**不会被用到**——pydantic 的 Literal
#   校验在进入本 runner 之前就会拒掉 'snapshot'，并把全部合法命令列给调用方
#   （"'snapshot' is not one of ['nav', ..., 'snap', ...]"）。这个拒绝信息比静默改写更好：
#   模型一眼看到正确命令名，下次就不会再错。
# 保留这张表只是为了**直接 import 本模块**的 Python 调用方（不经 schema 校验那条路）。
COMMAND_ALIASES = {
    "snapshot": "snap",
    "evaluate": "eval",
}

# 需要显式给绝对输出路径的命令。
# 起因：screenshot / pdf 不带输出路径时会往**当前工作目录**写，而 MCP 进程的 cwd
#   经常是只读位置——mcp_debug.log 里满是
#   `Write failed: open screenshot-*.jpg: read-only file system`。
FILE_OUTPUT_COMMANDS = {"screenshot", "pdf", "capture"}
FILE_OUTPUT_DIR = os.path.expanduser(
    os.environ.get("BROWSER_GATEWAY_OUTPUT_DIR", "~/.browser-gateway-mcp/output")
)

# 取内容类命令：输出体量最大，截断在这里最要紧。
BULK_OUTPUT_COMMANDS = {"snap", "text", "html", "find", "capture"}

_EXT = {"screenshot": "png", "pdf": "pdf", "capture": "json"}


def _has_output_flag(extra) -> bool:
    return any(str(a) in ("-o", "--output", "--out", "--path") for a in extra)


def run_pinchtab(config: dict) -> str:
    """Executes a PinchTab command."""
    cmd = config.get("command")
    if not cmd:
        raise ValueError("Missing 'command' for PinchTab")

    cmd = COMMAND_ALIASES.get(cmd, cmd)

    args = [PINCHTAB_BIN, cmd]

    url = config.get("url")
    if url and cmd == "nav":
        args.append(url)

    target = config.get("target")
    value = config.get("value")

    if target and cmd in ["click", "dblclick", "fill", "type", "hover", "focus",
                          "select", "check", "uncheck", "scrollintoview", "press"]:
        args.append(target)
    if value and cmd in ["fill", "type", "select", "press"]:
        args.append(value)

    extra = list(config.get("args", []) or [])

    # ★落盘类命令：调用方没给输出路径就补一个**可写的绝对路径**，避免往只读 cwd 写。
    if cmd in FILE_OUTPUT_COMMANDS and not _has_output_flag(extra):
        os.makedirs(FILE_OUTPUT_DIR, exist_ok=True)
        extra += ["-o", os.path.join(FILE_OUTPUT_DIR, f"pinchtab-{cmd}.{_EXT.get(cmd, 'out')}")]

    args.extend(str(a) for a in extra)

    max_chars = clamp_max_chars(config.get("max_chars"), DEFAULT_MAX_CHARS)

    try:
        # ★加 timeout：原先没传，浏览器卡住就永久阻塞整个 MCP 会话。
        result = subprocess.run(
            args, capture_output=True, text=True, check=True, timeout=TIMEOUT_PINCHTAB
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"PinchTab 超时（{TIMEOUT_PINCHTAB}s 未返回）。命令：{' '.join(args)}。"
            "常见原因：页面一直加载不完、浏览器实例没起来、或选择器等不到元素。"
            "先用 `pinchtab tab` 确认浏览器状态，不要原样重试。"
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"PinchTab failed: {e.stderr}\nCommand was: {' '.join(args)}")

    what = "页面内容" if cmd in BULK_OUTPUT_COMMANDS else "输出"
    return truncate(result.stdout, max_chars, what)
