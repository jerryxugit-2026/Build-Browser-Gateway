import asyncio
from src.browser_gateway_mcp.server import call_tool
async def main():
    try:
        res = await call_tool("browser_pinchtab", {"command": "nav", "url": "https://example.com"})
        print("RESULT:", res)
    except Exception as e:
        print("ERROR:", e)
asyncio.run(main())
