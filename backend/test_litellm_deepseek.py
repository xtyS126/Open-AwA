import asyncio
from litellm import acompletion
import logging
import httpx
logging.basicConfig(level=logging.DEBUG)
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.DEBUG)

async def main():
    try:
        await acompletion(
            model="deepseek/deepseek-v4-flash",
            messages=[{"role": "user", "content": "hi"}],
            api_key="sk-test",
            api_base="https://api.deepseek.com/v1"
        )
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(main())
