import sys
sys.path.insert(0, 'd:/代码/Open-AwA/backend')

from skills.skill_executor import CodeValidator, SkillExecutor
import asyncio

def test_code_validator():
    validator = CodeValidator()

    test_cases = [
        ("安全的数学运算", "result = 2 + 3 * 4", True),
        ("安全的列表操作", "result = [1, 2, 3] + [4, 5]", True),
        ("安全的字典操作", "result = {'a': 1, 'b': 2}", True),
        ("安全的函数定义", "def add(x, y): return x + y\nresult = add(1, 2)", True),
        ("安全的循环", "for i in range(10):\n    print(i)", True),
        ("危险：使用exec", "exec('print(1)')", False),
        ("危险：使用open", "f = open('test.txt')", False),
        ("危险：导入os", "import os", False),
        ("危险：使用subprocess", "import subprocess", False),
        ("危险：访问系统属性", "obj.__class__", False),
        ("危险：嵌套过多", "sum([i for i in range([i for i in range([i for i in range([i for i in range([i for i in range([i for i in range([i for i in range([i for i in range([i for i in range([i for i in range([i for i in range([i for i in range([i for i in range([i for i in range([i for i in range([i for i in range([i for i in range(100)])])])])])])])])])])])])])])])])", False),
    ]

    print("=" * 60)
    print("代码验证器测试")
    print("=" * 60)

    for name, code, should_pass in test_cases:
        is_safe, error_msg = validator.validate_code(code)
        status = "PASS" if is_safe == should_pass else "FAIL"
        print(f"\n[{status}] {name}")
        print(f"  代码: {code[:50]}...")
        print(f"  安全: {is_safe}, 预期: {should_pass}")
        if not is_safe:
            print(f"  错误: {error_msg}")

async def test_skill_executor():
    executor = SkillExecutor()

    safe_code_tests = [
        ("数学运算", "result = sum(range(100))"),
        ("列表推导", "result = [x * 2 for x in range(10)]"),
        ("字典操作", "result = {k: v for k, v in [(1, 2), (3, 4)]}"),
    ]

    print("\n" + "=" * 60)
    print("SkillExecutor集成测试")
    print("=" * 60)

    for name, code in safe_code_tests:
        try:
            skill_config = {
                'name': 'test_skill',
                'steps': [{
                    'action': 'test',
                    'tool': 'code_executor',
                    'params': {
                        'code': code,
                        'language': 'python',
                        'timeout': 5
                    }
                }]
            }

            success = await executor.initialize_environment(skill_config, {})
            if success:
                result = await executor._execute_code_action('test', {
                    'code': code,
                    'language': 'python',
                    'timeout': 5
                })
                print(f"\n[PASS] {name}")
                print(f"  代码: {code}")
                print(f"  结果: {result}")
            else:
                print(f"\n[FAIL] {name} - 环境初始化失败")
        except Exception as e:
            print(f"\n[FAIL] {name}")
            print(f"  错误: {e}")

    await executor.cleanup()

if __name__ == "__main__":
    print("开始测试安全修复...\n")

    test_code_validator()

    asyncio.run(test_skill_executor())

    print("\n" + "=" * 60)
    print("所有测试完成")
    print("=" * 60)
