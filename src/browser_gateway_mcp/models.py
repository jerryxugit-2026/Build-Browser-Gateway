import json
from typing import Any, Literal, Optional, List, Union
from pydantic import BaseModel, Field, model_validator

from browser_gateway_mcp.limits import (
    DEFAULT_LIMIT,
    DEFAULT_MAX_CHARS,
    DEFAULT_MAX_CHARS_COMPACT,
    HARD_MAX_CHARS,
    MAX_LIMIT,
    MIN_MAX_CHARS,
)


class PinchTabArgs(BaseModel):
    # ★2026-08-06 修：原枚举里的 "snapshot" 和 "evaluate" **是错的**——pinchtab 从来没有
    #   这两个命令，真名是 "snap" 和 "eval"。mcp_debug.log 里堆满了
    #   `unknown command "snapshot"` / `unknown command "evaluate"`，即这两条路径从未跑通过。
    #   现按 `pinchtab --help` 实测的真实命令表重写（0.13.2 核对）。
    #   为兼容旧调用，runner 侧保留 snapshot→snap / evaluate→eval 的别名映射。
    #
    # 只收录"取内容 + 基本交互"这一类；刻意不放 cookies / storage / clipboard / state /
    #   download / upload / record 等触及本机数据或落盘的命令——本网关是给 agent 用的，
    #   不应把浏览器的全部权能直接摊开。
    command: Literal[
        # 导航
        "nav", "back", "forward", "reload", "wait",
        # 取内容（输出体量最大的一档，均受 max_chars 约束）
        "snap", "text", "html", "title", "url", "find", "count",
        # 交互
        "click", "dblclick", "fill", "type", "press", "hover",
        "scroll", "scrollintoview", "select", "check", "uncheck", "focus",
        # 取证
        "screenshot", "pdf", "capture",
        # 脚本求值
        "eval",
    ] = Field(
        description=(
            "PinchTab 命令。取内容用 snap（可访问性树）/ text（纯文本）/ html；"
            "注意是 snap 和 eval，不是 snapshot / evaluate。"
        )
    )
    url: Optional[str] = Field(None, description="nav 命令的目标 URL。")
    target: Optional[str] = Field(None, description="click/fill/type 等的选择器或 ref。")
    value: Optional[str] = Field(None, description="fill/type 的文本值。")
    args: List[str] = Field(default_factory=list, description="透传给 pinchtab 的额外参数。")
    max_chars: int = Field(
        DEFAULT_MAX_CHARS,
        ge=MIN_MAX_CHARS,
        le=HARD_MAX_CHARS,
        description=(
            f"输出字符上限，默认 {DEFAULT_MAX_CHARS}，硬顶 {HARD_MAX_CHARS}。"
            "整页 text/snap 动辄几十万字符，必须截断。"
        ),
    )

    @model_validator(mode='before')
    @classmethod
    def parse_stringified_json(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for field in ['args']:
                val = data.get(field)
                if isinstance(val, str):
                    try:
                        data[field] = json.loads(val)
                    except json.JSONDecodeError:
                        pass
        return data


class BBBrowserArgs(BaseModel):
    site: str = Field(description="adapter 名（如 twitter/search）。")
    args: List[str] = Field(default_factory=list, description="site 命令的位置参数（如 'AI'）。")
    # ★2026-08-06 修：这个字段原先声明了但 bb_runner **从头到尾没读过**，传了等于空转。
    #   现已在 runner 侧真正消费（展开成 --key value / --flag）。
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="额外选项，展开成命令行开关（值为 true 时只加 --key，不加值）。",
    )
    limit: int = Field(
        DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description=f"返回条数上限，默认 {DEFAULT_LIMIT}，硬顶 {MAX_LIMIT}。",
    )
    max_chars: int = Field(
        DEFAULT_MAX_CHARS,
        ge=MIN_MAX_CHARS,
        le=HARD_MAX_CHARS,
        description=f"输出字符上限，默认 {DEFAULT_MAX_CHARS}，硬顶 {HARD_MAX_CHARS}。",
    )

    @model_validator(mode='before')
    @classmethod
    def parse_stringified_json(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for field in ['args', 'options']:
                val = data.get(field)
                if isinstance(val, str):
                    try:
                        data[field] = json.loads(val)
                    except json.JSONDecodeError:
                        pass
        return data


class AgentReachArgs(BaseModel):
    # ★★2026-08-06 重大订正：原枚举 ["auth", "session", "bypass"] **三个命令全是虚构的**，
    #   agent-reach 根本没有它们。实测 `agent-reach --help`，真实命令只有：
    #   setup / install / configure / doctor / check-update / watch / version。
    #   它本质是个**安装配置向导**（自述"给 AI Agent 装上看互联网的眼睛"），
    #   不是运行时的鉴权执行器，更不是验证码破解器。原工具描述属于彻底的能力误标。
    #
    # 这里只暴露**只读诊断**那几个；刻意不放 setup / install / configure——
    #   那三个是交互式安装器，会改本机配置，不该由 agent 触发。
    command: Literal["doctor", "version", "check-update"] = Field(
        description=(
            "Agent Reach 只读诊断命令：doctor=检查平台可用性，version=版本，"
            "check-update=查更新。注意它是安装配置工具，不做鉴权、不绕验证码。"
        )
    )
    # url 改为可选：上面三个命令都不接受 URL 参数，原先声明为必填是照着虚构命令写的。
    url: Optional[str] = Field(None, description="保留字段；当前三个只读命令均不使用。")
    max_chars: int = Field(
        DEFAULT_MAX_CHARS_COMPACT,
        ge=MIN_MAX_CHARS,
        le=HARD_MAX_CHARS,
        description=f"输出字符上限，默认 {DEFAULT_MAX_CHARS_COMPACT}。",
    )


class PlaywrightArgs(BaseModel):
    script_content: str = Field(
        description="要执行的 Python Playwright 异步脚本源码（应自行 asyncio.run(run())）。"
    )
    max_chars: int = Field(
        DEFAULT_MAX_CHARS,
        ge=MIN_MAX_CHARS,
        le=HARD_MAX_CHARS,
        description=f"输出字符上限，默认 {DEFAULT_MAX_CHARS}，硬顶 {HARD_MAX_CHARS}。",
    )


class UnifiedBrowserRequest(BaseModel):
    browser_intent: Literal["dom_interaction", "data_extraction", "session_auth", "custom_script"] = Field(
        description="按需求选择引擎意图。"
    )
    pinchtab_config: Optional[Union[str, PinchTabArgs]] = Field(None, description="intent=dom_interaction 时提供，可传对象或 JSON 字符串。")
    bb_config: Optional[Union[str, BBBrowserArgs]] = Field(None, description="intent=data_extraction 时提供，可传对象或 JSON 字符串。")
    reach_config: Optional[Union[str, AgentReachArgs]] = Field(None, description="intent=session_auth 时提供，可传对象或 JSON 字符串。")
    playwright_config: Optional[Union[str, PlaywrightArgs]] = Field(None, description="intent=custom_script 时提供，可传对象或 JSON 字符串。")

    @model_validator(mode='before')
    @classmethod
    def parse_stringified_json(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for field in ['pinchtab_config', 'bb_config', 'reach_config', 'playwright_config']:
                val = data.get(field)
                if isinstance(val, str):
                    try:
                        data[field] = json.loads(val)
                    except json.JSONDecodeError:
                        pass
        return data
