import asyncio
import sys
import os

# Add src to sys.path so we can import
sys.path.insert(0, os.path.abspath('src'))

from browser_gateway_mcp.server import call_tool

async def run_tests():
    print("Testing PinchTab Engine...")
    try:
        res1 = await call_tool("unified_browser_operator", {
            "browser_intent": "dom_interaction",
            "pinchtab_config": {
                "command": "nav",
                "url": "https://example.com"
            }
        })
        for r in res1: print(r.text if hasattr(r, 'text') else r)
    except Exception as e:
        print(f"PinchTab Test Failed: {e}")
    print("-" * 40)

    print("Testing bb-browser Engine...")
    try:
        res2 = await call_tool("unified_browser_operator", {
            "browser_intent": "data_extraction",
            "bb_config": {
                "site": "recommend",
                "args": []
            }
        })
        for r in res2: print(r.text if hasattr(r, 'text') else r)
    except Exception as e:
        print(f"bb-browser Test Failed: {e}")
    print("-" * 40)

    print("Testing Agent Reach Engine...")
    try:
        res3 = await call_tool("unified_browser_operator", {
            "browser_intent": "session_auth",
            "reach_config": {
                "command": "version",
                "url": ""
            }
        })
        for r in res3: print(r.text if hasattr(r, 'text') else r)
    except Exception as e:
        print(f"Agent Reach Test Failed: {e}")
    print("-" * 40)

    print("Testing Playwright Engine...")
    try:
        # A simple non-browser playwright script just to test the runner
        script = '''
import asyncio
async def main():
    print("Playwright Python Env is Working!")
asyncio.run(main())
'''
        res4 = await call_tool("unified_browser_operator", {
            "browser_intent": "custom_script",
            "playwright_config": {
                "script_content": script
            }
        })
        for r in res4: print(r.text if hasattr(r, 'text') else r)
    except Exception as e:
        print(f"Playwright Test Failed: {e}")
    print("-" * 40)

if __name__ == "__main__":
    asyncio.run(run_tests())
