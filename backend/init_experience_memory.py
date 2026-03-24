"""
经验记忆系统初始化脚本
自动注册experience-extractor skill并创建示例经验
"""
import sys
sys.path.insert(0, '.')

from db.models import init_db, SessionLocal, ExperienceMemory, ExperienceExtractionLog, Skill
import yaml
import uuid

def initialize_experience_memory():
    print("[工具] 初始化经验记忆系统...")

    # 1. 初始化数据库表
    print("[统计] 创建数据库表...")
    init_db()
    print("[成功] 数据库表创建完成")

    db = SessionLocal()

    try:
        # 2. 检查并注册experience-extractor skill
        print("[目标] 检查experience-extractor Skill...")
        existing_skill = db.query(Skill).filter(Skill.name == 'experience-extractor').first()

        if not existing_skill:
            print("[包] 注册experience-extractor Skill...")

            # 读取YAML配置文件
            with open('skills/experience_extractor.yaml', 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            new_skill = Skill(
                id=str(uuid.uuid4()),
                name='experience-extractor',
                version='1.0.0',
                description='从工作流中自动提取可复用的经验模式，帮助AI越干越聪明',
                config=yaml.dump(config),
                enabled=True
            )

            db.add(new_skill)
            db.commit()
            print("[成功] experience-extractor Skill注册成功")
        else:
            print("[信息] experience-extractor Skill已存在")

        # 3. 创建示例经验
        print("[笔记] 创建示例经验...")
        existing_experiences = db.query(ExperienceMemory).count()

        if existing_experiences == 0:
            sample_experiences = [
                {
                    'experience_type': 'method',
                    'title': '大型重构任务应先建立测试覆盖',
                    'content': '在进行涉及多个模块的重构时，首先应建立或完善单元测试和集成测试。这能在重构过程中快速发现回归问题，减少调试时间。',
                    'trigger_conditions': '任务涉及多个文件/模块的修改，且修改存在依赖关系',
                    'confidence': 0.8,
                    'source_task': 'refactoring',
                    'usage_count': 5,
                    'success_count': 4
                },
                {
                    'experience_type': 'method',
                    'title': '使用git stash临时保存未完成的修改',
                    'content': '当需要临时切换分支处理紧急任务，但当前修改尚未完成时，使用git stash保存工作进度。完成紧急任务后，使用git stash pop恢复修改。',
                    'trigger_conditions': '用户需要切换任务但不想提交未完成的修改',
                    'confidence': 0.9,
                    'source_task': 'git_workflow',
                    'usage_count': 8,
                    'success_count': 8
                },
                {
                    'experience_type': 'error_pattern',
                    'title': 'Python ImportError处理流程',
                    'content': '当遇到ImportError时，首先检查包是否已安装（pip list），然后确认Python版本兼容性，最后检查__init__.py是否存在。按此顺序排查可以快速定位问题。',
                    'trigger_conditions': '执行Python代码时遇到ImportError',
                    'confidence': 0.85,
                    'source_task': 'debugging',
                    'usage_count': 12,
                    'success_count': 11
                },
                {
                    'experience_type': 'strategy',
                    'title': '模糊需求应先澄清再执行',
                    'content': '当用户需求描述不明确时（如"优化性能"、"改进界面"），应先向用户确认具体目标、指标和约束条件，再开始实施。避免在未澄清的情况下投入大量时间。',
                    'trigger_conditions': '用户的需求描述包含模糊词汇（优化/改进/调整等）',
                    'confidence': 0.75,
                    'source_task': 'requirement_analysis',
                    'usage_count': 3,
                    'success_count': 3
                },
                {
                    'experience_type': 'tool_usage',
                    'title': 'VSCode多光标编辑技巧',
                    'content': '使用Alt+Click添加光标，Ctrl+Shift+L选择所有相同内容，Ctrl+D逐个选择。对于批量重命名，先选中一个，然后使用Ctrl+Shift+L全选后统一修改。',
                    'trigger_conditions': '用户需要进行批量文本编辑',
                    'confidence': 0.9,
                    'source_task': 'code_editing',
                    'usage_count': 6,
                    'success_count': 6
                }
            ]

            for exp_data in sample_experiences:
                experience = ExperienceMemory(**exp_data)
                db.add(experience)

            db.commit()
            print(f"[成功] 创建了 {len(sample_experiences)} 条示例经验")
        else:
            print(f"[信息] 数据库中已有 {existing_experiences} 条经验")

        # 4. 验证初始化结果
        print("\n[列表] 验证初始化结果...")
        skills_count = db.query(Skill).filter(Skill.name == 'experience-extractor').count()
        experiences_count = db.query(ExperienceMemory).count()
        logs_count = db.query(ExperienceExtractionLog).count()

        print(f"  - Skills数量: {db.query(Skill).count()}")
        print(f"  - experience-extractor: {'[成功]' if skills_count > 0 else '[失败]'}")
        print(f"  - 经验总数: {experiences_count}")
        print(f"  - 提取日志数: {logs_count}")

        print("\n[启动] 经验记忆系统初始化完成!")

    except Exception as e:
        print(f"[失败] 初始化失败: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    initialize_experience_memory()
