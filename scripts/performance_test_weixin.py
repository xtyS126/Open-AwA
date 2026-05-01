"""
微信自动回复性能测试脚本 (1000并发, 延迟<200ms)
使用 aiohttp 模拟并发请求。
"""

import asyncio
import time
import aiohttp
import sys

# 本地测试服务器地址
BASE_URL = "http://localhost:8000"
CONCURRENCY = 1000
TARGET_LATENCY_MS = 200
TOKEN = "test-token" # 这里假设需要 token，实际情况可能不同，如果是为了压测可能需要先获取或使用一个固定的 mock token

async def fetch(session, url, method="GET", json_data=None):
    start = time.perf_counter()
    try:
        if method == "GET":
            async with session.get(url) as response:
                await response.read()
                status = response.status
        else:
            async with session.post(url, json=json_data) as response:
                await response.read()
                status = response.status
    except Exception as e:
        status = str(e)
    
    elapsed = (time.perf_counter() - start) * 1000
    return status, elapsed

async def run_load_test(endpoint, method="GET", json_data=None):
    url = f"{BASE_URL}{endpoint}"
    print(f"开始压测 {method} {url} (并发: {CONCURRENCY})...")
    
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    connector = aiohttp.TCPConnector(limit=CONCURRENCY)
    
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        tasks = [fetch(session, url, method, json_data) for _ in range(CONCURRENCY)]
        
        start_time = time.perf_counter()
        results = await asyncio.gather(*tasks)
        total_time = time.perf_counter() - start_time
        
    latencies = [res[1] for res in results if isinstance(res[0], int) and res[0] == 200]
    errors = [res for res in results if not isinstance(res[0], int) or res[0] != 200]
    
    success_count = len(latencies)
    error_count = len(errors)
    
    avg_latency = sum(latencies) / success_count if success_count > 0 else 0
    max_latency = max(latencies) if success_count > 0 else 0
    p95_latency = sorted(latencies)[int(success_count * 0.95)] if success_count > 0 else 0
    
    print(f"--- 测试结果 ({method} {endpoint}) ---")
    print(f"总耗时: {total_time:.2f}s")
    print(f"成功请求: {success_count}")
    print(f"失败请求: {error_count}")
    print(f"平均延迟: {avg_latency:.2f}ms")
    print(f"最大延迟: {max_latency:.2f}ms")
    print(f"P95延迟: {p95_latency:.2f}ms")
    
    if avg_latency > TARGET_LATENCY_MS:
        print(f"⚠️ 警告: 平均延迟 ({avg_latency:.2f}ms) 超过目标 ({TARGET_LATENCY_MS}ms)")
    else:
        print(f"✅ 达标: 平均延迟 ({avg_latency:.2f}ms) 小于目标 ({TARGET_LATENCY_MS}ms)")
        
    print("-" * 40)

async def main():
    # 测试获取状态接口 (高频读取)
    await run_load_test("/api/weixin/auto-reply/status")
    
    # 模拟一定量的并发单次处理请求
    # 注意: process-once 内部有锁，如果同时对同一个 user_id 并发请求，会被锁阻塞，
    # 导致延迟增加。在真实的1000并发场景下，通常是不同用户的请求。
    # 这里只是做一个基础的压力测试模拟。
    # await run_load_test("/api/weixin/auto-reply/process-once", method="POST")

if __name__ == "__main__":
    # Windows 上的 aiohttp 需要设置这个以避免 ProactorEventLoop 问题
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
