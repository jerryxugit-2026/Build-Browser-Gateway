import json
import os
import re
import subprocess

from browser_gateway_mcp.limits import (
    DEFAULT_LIMIT,
    DEFAULT_MAX_CHARS,
    TIMEOUT_BB,
    cap_json_list,
    clamp_limit,
    clamp_max_chars,
    truncate,
)

BB_BIN = os.environ.get("BB_BROWSER_BIN", "bb-browser")
BB_SITES_DIR = os.path.expanduser(os.environ.get("BB_SITES_DIR", "~/.bb-browser/bb-sites"))

# ★★2026-08-06（bb-browser 0.11.2 → 0.14.2 升级后踩到）：
#   **0.14.2 不再在运行 adapter 前自动导航到它声明的域名。**
#   adapter 的实现是在**页面上下文里 fetch**（见 bb-sites/*/*.js），浏览器不在目标域上时
#   请求会被跨域拦掉 —— 表现为 `count: 0, results: []` 的**静默零结果**
#   （baidu 更直白：TypeError: Failed to fetch）。0.11.2 下同样的 adapter 是好的。
#   实测：手动 `bb-browser open https://duckduckgo.com` 之后再跑，立刻恢复 10 条。
#
#   故这里在调 adapter 前，先读它 @meta 里的 domain 并把浏览器导过去，
#   把 0.11.2 的行为补回来。读不到 domain 就跳过导航（不阻断，让 adapter 自己去试）。
_META_DOMAIN_RE = re.compile(r'"domain"\s*:\s*"([^"]+)"')


def _adapter_domain(site: str):
    """从 adapter 源码的 @meta 块里取 domain。取不到返回 None。"""
    safe = str(site).strip().strip("/")
    # 只允许 vendor/name 这种形状，挡住 ../ 之类的路径穿越
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", safe):
        return None
    path = os.path.join(BB_SITES_DIR, safe + ".js")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            head = fh.read(2048)   # @meta 在文件开头，读前 2KB 足够
    except OSError:
        return None
    m = _META_DOMAIN_RE.search(head)
    return m.group(1) if m else None


def _ensure_on_domain(domain: str) -> None:
    """把浏览器导到 adapter 的域名。失败不抛——导航失败不该直接判死整次调用。"""
    try:
        subprocess.run(
            [BB_BIN, "open", f"https://{domain}"],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


def _expand_options(options: dict) -> list:
    """
    ★2026-08-06 修：options 字段原先声明了却**从未被消费**，调用方传了等于空转。
    现按常规约定展开：值为 True → 只加 --key；值为 False/None → 跳过；其余 → --key value。
    """
    out = []
    for key, val in (options or {}).items():
        flag = f"--{str(key).lstrip('-')}"
        if val is True:
            out.append(flag)
        elif val in (False, None):
            continue
        else:
            out.extend([flag, str(val)])
    return out


def run_bb_browser(config: dict) -> str:
    """Executes a bb-browser command for data extraction."""
    site = config.get("site")
    if not site:
        raise ValueError("Missing 'site' for bb-browser")

    limit = clamp_limit(config.get("limit"), DEFAULT_LIMIT)
    max_chars = clamp_max_chars(config.get("max_chars"), DEFAULT_MAX_CHARS)

    # ★先把浏览器导到 adapter 声明的域名（0.14.2 起不再自动做这件事，见文件头部说明）。
    domain = _adapter_domain(site)
    if domain:
        _ensure_on_domain(domain)

    args = [BB_BIN, "site", str(site)]
    args.extend(str(a) for a in (config.get("args") or []))
    args.extend(_expand_options(config.get("options") or {}))
    # 始终强制 JSON 输出（MCP 侧要结构化）。已由调用方传入就不重复加。
    if "--json" not in args:
        args.append("--json")

    try:
        # ★加 timeout：原先没传，adapter 卡住会永久阻塞整个 MCP 会话。
        result = subprocess.run(
            args, capture_output=True, text=True, check=True, timeout=TIMEOUT_BB
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"bb-browser 超时（{TIMEOUT_BB}s 未返回）。命令：{' '.join(args)}。"
            "adapter 可能在翻页或等待渲染，缩小检索范围后再试。"
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        # 2026-08-06 起本机已装 145 个社区 adapter，所以"0 adapter"不再是默认怀疑对象。
        # 现在最常见的失败是 adapter 名写错，或该站点需要登录态。
        hint = (
            "\n提示：先用 `bb-browser site list` 确认 adapter 名是否正确"
            "（形如 `google/search`、`duckduckgo/search`、`arxiv/search`），"
            "再用 `bb-browser site info <name>` 看它要什么参数。"
            "若该站点需要登录，得先在 bb-browser 的浏览器里登录过。"
            "adapter 库更新：`bb-browser site update`。"
        )
        raise RuntimeError(f"bb-browser failed: {stderr}{hint}\nCommand was: {' '.join(args)}")

    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return truncate(result.stdout, max_chars, "bb-browser 输出")

    # ★条数上限：数组结果截到前 limit 条，并明确告知原始条数（不做静默截断）。
    parsed, original_count = cap_json_list(parsed, limit)
    text = json.dumps(parsed, ensure_ascii=False, indent=2)
    if original_count:
        text += f"\n\n[⚠️ 结果已按 limit={limit} 截取；原始共 {original_count} 条。]"

    # ★静默零结果识别（2026-08-06 实测遇到）：部分 adapter 会返回 success=true 但 results 为空，
    #   例如 google/search 与 arxiv/search 当前就是这样（站点改版/反爬页/选择器失效）。
    #   这比直接报错更危险——调用方会当成"确实没搜到"，据此得出错误结论。
    #   这里无法区分"真没结果"和"adapter 坏了"，所以不下判断，只把这个歧义**明确摆出来**。
    if _looks_empty(parsed):
        text += (
            "\n\n[⚠️ 该 adapter 返回 success 但结果为空。这有两种可能，本工具无法区分："
            "① 确实没有匹配结果；② 该 adapter 已失效（站点改版 / 反爬页 / 选择器过期）。"
            "**不要直接当成『没搜到』**——请换一个 adapter 交叉验证"
            "（实测 bing/search、baidu/search、duckduckgo/search 工作正常；"
            "google/search 与 arxiv/search 在 2026-08-06 实测为静默零结果）。]"
        )
    return truncate(text, max_chars, "bb-browser 输出")


def _looks_empty(parsed) -> bool:
    """判断"声称成功但没有任何结果"。只认常见结构，认不出就返回 False（不误报）。"""
    if isinstance(parsed, list):
        return len(parsed) == 0
    if not isinstance(parsed, dict):
        return False
    if parsed.get("success") is False:
        return False  # 已经明确失败了，走的是另一条路径，不重复提示
    for path in (("result", "results"), ("result", "items"),
                 ("data", "results"), ("data", "items"), ("results",), ("items",)):
        node = parsed
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, list):
            return len(node) == 0
    return False
