import os
import subprocess

from browser_gateway_mcp.limits import (
    DEFAULT_MAX_CHARS_COMPACT,
    TIMEOUT_AGENT_REACH,
    clamp_max_chars,
    truncate,
)

AGENT_REACH_BIN = os.environ.get("AGENT_REACH_BIN", "agent-reach")

# ★★2026-08-06 重大订正：本 runner 原先按 auth / session / bypass 三个命令构造调用，
#   而 agent-reach **根本没有这三个命令**（实测 `agent-reach --help`，真实命令是
#   setup / install / configure / doctor / check-update / watch / version）。
#   也就是说这条路径从设计之初就不可能跑通，工具描述里"鉴权 / 绕验证码"属于能力误标。
#
# 现只允许**只读诊断**三个命令。刻意不放 setup / install / configure：
#   那三个是交互式安装器，会改本机配置，不该由 agent 触发。
ALLOWED_COMMANDS = {"doctor", "version", "check-update"}

# 这三个命令都不接受 URL 位置参数，传了会导致 argparse 报错，故一律不透传。
COMMANDS_TAKING_URL = set()


def run_agent_reach(config: dict) -> str:
    """Runs a read-only Agent Reach diagnostic command."""
    cmd = config.get("command")
    if not cmd:
        raise ValueError("Missing 'command' for Agent Reach")

    if cmd not in ALLOWED_COMMANDS:
        raise ValueError(
            f"Agent Reach 不支持命令 '{cmd}'。本网关只放行只读诊断命令："
            f"{sorted(ALLOWED_COMMANDS)}。"
            "注意：agent-reach 是安装配置向导，不做运行时鉴权、也不绕验证码——"
            "旧 schema 里的 auth / session / bypass 三个命令是虚构的，从不存在。"
        )

    args = [AGENT_REACH_BIN, cmd]

    url = config.get("url")
    if url and str(url).strip() and cmd in COMMANDS_TAKING_URL:
        args.append(str(url))

    max_chars = clamp_max_chars(config.get("max_chars"), DEFAULT_MAX_CHARS_COMPACT)

    try:
        # ★加 timeout：原先没传。注释里自己写着 "output can be long" 却既不截断也不限时。
        result = subprocess.run(
            args, capture_output=True, text=True, check=True, timeout=TIMEOUT_AGENT_REACH
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Agent Reach 超时（{TIMEOUT_AGENT_REACH}s 未返回）。命令：{' '.join(args)}"
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Agent Reach failed: {e.stderr}\nCommand was: {' '.join(args)}")

    return truncate(result.stdout, max_chars, "Agent Reach 输出")
