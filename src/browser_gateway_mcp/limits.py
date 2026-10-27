"""
输出与超时的统一护栏（2026-08-06 新建）。

为什么需要：本网关原先是**完全裸奔**的——四个 runner 一律 `return result.stdout`
原样透传子进程输出，没有截断、没有条数上限；`subprocess.run` 连 timeout 都没传，
子进程卡住就永久阻塞整个 MCP 会话。

一次 `pinchtab text`（整页纯文本）或 `pinchtab snap`（整页可访问性树）动辄几万到几十万
字符，足以把下游 agent 的上下文预算一次打爆。浏览器类工具的输出体量**天生不可预估**，
所以护栏必须放在网关这一侧，不能指望调用方自觉。

三条护栏：
  ① 超时：每个引擎按其性质给硬超时，到点杀子进程并明确告知调用方（而不是静默挂死）。
  ② 字符截断：每个工具有默认上限，调用方可在区间内自调，但**不能突破硬顶**。
  ③ 条数上限：对返回 JSON 数组的引擎，截到前 N 条。
"""

# ── 条数上限 ──────────────────────────────────────────────────────────
DEFAULT_LIMIT = 5           # 每工具默认返回条数（2026-08-06 徐总定：与 paper-search-mcp 统一为 5）
MAX_LIMIT = 50              # 调用方可上调的硬顶（再高就失去护栏意义）

# ── 字符截断 ──────────────────────────────────────────────────────────
# 按引擎输出性质分档；调用方可用 max_chars 在 [1000, HARD_MAX_CHARS] 内自调。
DEFAULT_MAX_CHARS = 10_000          # 页面正文/DOM 类输出（体量最大的那一档）
DEFAULT_MAX_CHARS_COMPACT = 5_000   # 状态/诊断类短输出
HARD_MAX_CHARS = 10_000             # 绝对硬顶，任何调用方都不能突破
MIN_MAX_CHARS = 1_000

# ── 超时（秒）─────────────────────────────────────────────────────────
# 依据：浏览器动作要等页面加载与渲染，比纯 API 慢得多；但也不能真的无限等。
TIMEOUT_PINCHTAB = 90      # 导航+渲染+取内容
TIMEOUT_BB = 120           # site adapter 可能翻页
TIMEOUT_AGENT_REACH = 60   # 只剩只读诊断命令，很快
TIMEOUT_PLAYWRIGHT = 180   # 用户脚本，放宽但仍有顶


def clamp_limit(value, default: int = DEFAULT_LIMIT) -> int:
    """把调用方给的 limit 夹到 [1, MAX_LIMIT]；非法值退回默认。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(MAX_LIMIT, n))


def clamp_max_chars(value, default: int = DEFAULT_MAX_CHARS) -> int:
    """把调用方给的 max_chars 夹到 [MIN_MAX_CHARS, HARD_MAX_CHARS]；非法值退回默认。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(MIN_MAX_CHARS, min(HARD_MAX_CHARS, n))


def truncate(text: str, max_chars: int, what: str = "输出") -> str:
    """
    超长即截断，并**明确告诉调用方被截了**（静默截断会让 agent 以为自己拿到了全部内容，
    据此做出错误判断——这比直接报错更危险）。
    """
    if text is None:
        return ""
    text = str(text)
    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars]
        + f"\n\n[⚠️ {what}已截断：原长 {len(text)} 字符，按上限 {max_chars} 截取。"
        + "需要更多内容请缩小抓取范围（例如改用更精确的选择器），而不是简单调大 max_chars。]"
    )


# 结果数组在响应里的常见嵌套位置。bb-browser 的 adapter 返回的是
#   {"id":..., "success":true, "data":{"results":[...], "metadata":{...}}}
#   而不是裸数组——只认顶层数组的话，limit 会**静默失效**（实测踩过：传 limit=3 仍回 10 条）。
#
# ⚠️ bb-browser 的响应外层**随版本变过**（2026-08-06 升级时踩到）：
#   0.11.2：{"id":..,"success":true,"data":{"results":[...],"count":N}}
#   0.14.2：{"result":{"query":..,"count":N,"results":[...]}}
#   两种都要认，否则 limit 会静默失效。
_NESTED_LIST_PATHS = (
    ("result", "results"),   # bb-browser ≥0.14
    ("result", "items"),
    ("data", "results"),     # bb-browser ≤0.11
    ("data", "items"),
    ("data", "list"),
    ("results",),
    ("items",),
)


def _dig(obj, path):
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj if isinstance(obj, list) else None


def cap_json_list(parsed, limit: int):
    """
    把结果数组截到前 limit 条；同时回报原始条数（供调用方知道被截了多少）。
    既处理顶层裸数组，也处理常见的嵌套结构（见 _NESTED_LIST_PATHS）。
    返回 (截断后的对象, 原始条数 or None)。
    """
    # ① 顶层就是数组
    if isinstance(parsed, list):
        return (parsed[:limit], len(parsed)) if len(parsed) > limit else (parsed, None)

    # ② 嵌套数组：原地截断（保留外层元数据，调用方仍能看到 success / query 等字段）
    if isinstance(parsed, dict):
        for path in _NESTED_LIST_PATHS:
            arr = _dig(parsed, path)
            if arr is None or len(arr) <= limit:
                continue
            original = len(arr)
            node = parsed
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = arr[:limit]
            # 同步修正条数字段，免得 count 与实际条数对不上、误导调用方
            for counter in ("count", "total", "total_results"):
                if isinstance(node, dict) and counter in node:
                    node[counter] = limit
                if isinstance(parsed.get("data"), dict) and counter in parsed["data"]:
                    parsed["data"][counter] = limit
            return parsed, original

    return parsed, None
