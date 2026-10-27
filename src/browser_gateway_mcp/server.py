import os
import sys
import logging
import asyncio
from typing import Any

from mcp.server.stdio import stdio_server
from mcp.server import Server
from mcp.types import TextContent, Tool

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("browser-gateway-mcp")
# Optional file logging: set BROWSER_GATEWAY_LOG_FILE to a writable path to capture debug logs.
_log_file = os.environ.get("BROWSER_GATEWAY_LOG_FILE")
if _log_file:
    logger.addHandler(logging.FileHandler(_log_file))

# Add engines to path if needed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from browser_gateway_mcp.models import UnifiedBrowserRequest, PinchTabArgs, BBBrowserArgs, AgentReachArgs, PlaywrightArgs
from browser_gateway_mcp.engines.pinchtab_runner import run_pinchtab
from browser_gateway_mcp.engines.bb_runner import run_bb_browser
from browser_gateway_mcp.engines.agent_reach_runner import run_agent_reach
from browser_gateway_mcp.engines.playwright_runner import run_playwright_script

app = Server("browser-gateway-mcp")

ALLOW_CUSTOM_SCRIPT = os.environ.get("BROWSER_GATEWAY_ALLOW_CUSTOM_SCRIPT") == "1"
ALLOW_SESSION_AUTH = os.environ.get("BROWSER_GATEWAY_ALLOW_SESSION_AUTH") == "1"

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="unified_browser_operator",
            description="""
            浏览器自动化网关，按 intent 路由到 4 个引擎：
            1. dom_interaction (PinchTab)：导航/点击/填表/取页面内容（snap 可访问性树、text 纯文本、html）。
               注意命令是 snap / eval，不是 snapshot / evaluate。
            2. data_extraction (bb-browser)：用 site adapter 抽结构化数据（如 twitter/search）。
               已装 145 个社区 adapter（google/bing/baidu/duckduckgo/arxiv 等 search 全在）。
            3. session_auth (Agent Reach)：**仅只读诊断**（doctor / version / check-update）。
               ⚠️ 2026-08-06 订正：agent-reach 是安装配置向导，**不做鉴权、不绕验证码**；
               旧描述里的"authenticate / bypass captcha"是能力误标，对应命令根本不存在。
               默认熔断，需 BROWSER_GATEWAY_ALLOW_SESSION_AUTH=1。
            4. custom_script (Playwright)：执行自定义 Python Playwright 脚本。
               默认熔断，需 BROWSER_GATEWAY_ALLOW_CUSTOM_SCRIPT=1。
               Playwright 浏览器通过 PLAYWRIGHT_BROWSERS_PATH 指定目录（chromium/firefox/webkit 任一即可）。

            所有引擎均已加硬超时；所有输出均按 max_chars（默认 10000，硬顶 10000）截断，
            数组结果按 limit（默认 5）截取，截断时会明确告知调用方。
            """,
            inputSchema=UnifiedBrowserRequest.model_json_schema()
        ),
        Tool(
            name="browser_pinchtab",
            description=(
                "用 PinchTab 直接操作 DOM：nav 导航、click/fill/type 交互、"
                "snap 取可访问性树、text 取纯文本、html 取源码、eval 求值、screenshot 截图。"
                "（命令名是 snap / eval，不是 snapshot / evaluate。）"
                "输出按 max_chars 截断，默认 10000 字符——整页 text/snap 常有几十万字符。"
            ),
            inputSchema=PinchTabArgs.model_json_schema()
        ),
        Tool(
            name="browser_bb",
            description=(
                "用 bb-browser 的 site adapter 抽结构化数据（如 twitter/search）。"
                "结果按 limit 截取（默认 5 条）、按 max_chars 截断（默认 10000 字符）。"
                "本机已装 145 个社区 adapter，含 google/search、bing/search、baidu/search、duckduckgo/search、arxiv/search 等。用 `bb-browser site list` 查全表。"
            ),
            inputSchema=BBBrowserArgs.model_json_schema()
        ),
        Tool(
            name="browser_reach",
            description=(
                "Agent Reach 只读诊断：doctor（检查平台可用性）/ version / check-update。"
                "⚠️ 2026-08-06 订正：agent-reach 是**安装配置向导**，不做鉴权、不绕验证码；"
                "旧描述所称的 auth / session / bypass 三个命令根本不存在，属能力误标。"
                "默认熔断，需 BROWSER_GATEWAY_ALLOW_SESSION_AUTH=1。"
            ),
            inputSchema=AgentReachArgs.model_json_schema()
        ),
        Tool(
            name="browser_playwright",
            description=(
                "执行自定义 Python Playwright 脚本。默认熔断，需 BROWSER_GATEWAY_ALLOW_CUSTOM_SCRIPT=1。"
                f"硬超时 180s，输出按 max_chars 截断（默认 10000 字符）。"
                "Playwright chromium/firefox/webkit 均已就位（自定义 PLAYWRIGHT_BROWSERS_PATH）。"
            ),
            inputSchema=PlaywrightArgs.model_json_schema()
        )
    ]

def _format_success(result_text: str, message: str) -> list[TextContent]:
    return [
        TextContent(
            type="text",
            text=f"[SYSTEM FEEDBACK]: {message}\n\n[RESULTS]:\n{result_text}"
        )
    ]

def _format_error(error_msg: str, suggestion: str) -> list[TextContent]:
    return [
        TextContent(
            type="text",
            text=(
                f"[CRITICAL TOOL EXECUTION ERROR] {error_msg}\n"
                f"Actionable Advice: {suggestion}\n"
                f"Do NOT retry identically. If blocked, output the error and stop."
            )
        )
    ]

def _guard_session_auth() -> None:
    if not ALLOW_SESSION_AUTH:
        raise PermissionError(
            "session_auth/browser_reach is blocked by default. "
            "Set BROWSER_GATEWAY_ALLOW_SESSION_AUTH=1 only for a deliberately authorized auth session."
        )

def _guard_custom_script() -> None:
    if not ALLOW_CUSTOM_SCRIPT:
        raise PermissionError(
            "custom_script/browser_playwright is blocked by default. "
            "Set BROWSER_GATEWAY_ALLOW_CUSTOM_SCRIPT=1 only for a deliberately authorized script session."
        )

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    import json
    try:
        if name == "unified_browser_operator":
            intent = arguments.get("browser_intent")

            def parse_config(cfg):
                if isinstance(cfg, str):
                    try:
                        return json.loads(cfg)
                    except Exception:
                        pass
                return cfg

            if intent == "dom_interaction":
                config = parse_config(arguments.get("pinchtab_config"))
                if not config:
                    return _format_error("Missing pinchtab_config.", "Provide pinchtab_config when intent is dom_interaction.")
                result = run_pinchtab(config)
                return _format_success(result, "PinchTab action completed.")

            elif intent == "data_extraction":
                config = parse_config(arguments.get("bb_config"))
                if not config:
                    return _format_error("Missing bb_config.", "Provide bb_config when intent is data_extraction.")
                result = run_bb_browser(config)
                return _format_success(result, "BB-Browser data extraction completed.")

            elif intent == "session_auth":
                _guard_session_auth()
                config = parse_config(arguments.get("reach_config"))
                if not config:
                    return _format_error("Missing reach_config.", "Provide reach_config when intent is session_auth.")
                result = run_agent_reach(config)
                return _format_success(result, "Agent Reach 只读诊断完成。")

            elif intent == "custom_script":
                _guard_custom_script()
                config = parse_config(arguments.get("playwright_config"))
                if not config:
                    return _format_error("Missing playwright_config.", "Provide playwright_config when intent is custom_script.")
                result = run_playwright_script(config)
                return _format_success(result, "Playwright script execution completed.")
            else:
                return _format_error(f"Unknown intent: {intent}", "Use dom_interaction, data_extraction, session_auth, or custom_script.")
                
        elif name == "browser_pinchtab":
            result = run_pinchtab(arguments)
            return _format_success(result, "PinchTab action completed.")
            
        elif name == "browser_bb":
            result = run_bb_browser(arguments)
            return _format_success(result, "BB-Browser data extraction completed.")
            
        elif name == "browser_reach":
            _guard_session_auth()
            result = run_agent_reach(arguments)
            return _format_success(result, "Agent Reach 只读诊断完成。")
            
        elif name == "browser_playwright":
            _guard_custom_script()
            result = run_playwright_script(arguments)
            return _format_success(result, "Playwright script execution completed.")

        else:
            return _format_error(f"Unknown tool: {name}", "Use a valid browser gateway tool.")

    except Exception as e:
        logger.error(f"Execution failed: {e}")
        return _format_error(str(e), "Execution failed. Check parameters and engine configuration.")

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
