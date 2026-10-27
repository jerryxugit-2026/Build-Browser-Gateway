import os
import subprocess
import tempfile

from browser_gateway_mcp.limits import (
    DEFAULT_MAX_CHARS,
    TIMEOUT_PLAYWRIGHT,
    clamp_max_chars,
    truncate,
)

# ★2026-08-06 教训：Playwright 浏览器可能装在非默认缓存路径（由环境变量
#   PLAYWRIGHT_BROWSERS_PATH 指定）。此前只查默认路径，据此误判"没装浏览器"——实际装了。
#   这里尊重该环境变量；未设置时交给 Playwright 自己的默认解析。
_PLAYWRIGHT_BROWSERS = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ""

# ★用**明确知道装了 playwright 的解释器**，不要靠 PATH 解析 "python3" 撞运气——
#   启动上下文不同，PATH 里的 python3 可能没有 playwright。可用
#   BROWSER_GATEWAY_PYTHON 显式指定解释器。
_PYTHON = os.environ.get("BROWSER_GATEWAY_PYTHON") or "python3"


def _browser_hint() -> str:
    """
    浏览器二进制找不到时，把可执行的下一步说清楚，免得调用方对着底层报错反复重试。
    """
    if not _PLAYWRIGHT_BROWSERS or os.path.isdir(_PLAYWRIGHT_BROWSERS):
        return ""
    return (
        f"\n提示：未在 {_PLAYWRIGHT_BROWSERS} 找到 Playwright 浏览器二进制。"
        "默认的 chromium 会报 Executable doesn't exist。三条出路："
        "① 确认 PLAYWRIGHT_BROWSERS_PATH 指向正确目录（外置卷未挂载时会失效）；"
        "② 跑 `python3 -m playwright install chromium`（联网下载数百 MB，请先人工确认）；"
        "③ 脚本里改用系统已装的 Chrome：p.chromium.launch(channel='chrome')。"
    )


def run_playwright_script(config: dict) -> str:
    """Executes a pure python playwright script."""
    script_content = config.get("script_content")
    if not script_content:
        raise ValueError("Missing 'script_content' for Playwright")

    max_chars = clamp_max_chars(config.get("max_chars"), DEFAULT_MAX_CHARS)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(script_content)
        temp_path = f.name

    try:
        # ★加 timeout：原先没传，用户脚本里一个死循环或一个等不到的选择器
        #   就能把整个 MCP 会话永久钉死。
        # 显式把浏览器路径传给子进程：MCP 若不是从登录 shell 拉起，环境里可能没有这个变量。
        env = dict(os.environ)
        if _PLAYWRIGHT_BROWSERS:
            env.setdefault("PLAYWRIGHT_BROWSERS_PATH", _PLAYWRIGHT_BROWSERS)
        result = subprocess.run(
            [_PYTHON, temp_path],
            capture_output=True,
            text=True,
            check=True,
            timeout=TIMEOUT_PLAYWRIGHT,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Playwright 脚本超时（{TIMEOUT_PLAYWRIGHT}s 未返回）。"
            "多为死循环、等不到的选择器、或页面一直加载不完。"
            "给脚本内部的 wait/goto 也设上超时，不要原样重试。" + _browser_hint()
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Playwright script failed: {e.stderr}\nStdout: {e.stdout}" + _browser_hint()
        )
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return truncate(result.stdout, max_chars, "脚本输出")
