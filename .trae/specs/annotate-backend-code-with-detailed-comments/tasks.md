# Tasks
- [x] Task 1: 盘点 backend 代码文件并制定注释补充顺序
  - [x] SubTask 1.1: 按目录梳理入口层、路由层、核心执行层、配置层、存储层、插件层、安全层、技能层、计费层与测试层文件
  - [x] SubTask 1.2: 识别高复杂度、高风险与高耦合文件，作为优先补充对象
  - [x] SubTask 1.3: 明确每类文件需要补充的注释类型（模块说明、类说明、函数说明、关键分支说明）

- [x] Task 2: 为后端入口、路由、核心与配置代码补充详细中文注释
  - [x] SubTask 2.1: 完成 backend/main.py 与 api 目录下文件的注释补充
  - [x] SubTask 2.2: 完成 core、config、db、memory 目录下文件的注释补充
  - [x] SubTask 2.3: 复查注释是否准确描述参数、返回值、流程与异常处理

- [x] Task 3: 为插件、安全、技能与计费相关代码补充详细中文注释
  - [x] SubTask 3.1: 完成 plugins 与 security 目录下文件的注释补充
  - [x] SubTask 3.2: 完成 skills 与 billing 目录下文件的注释补充
  - [x] SubTask 3.3: 对沙箱、权限、适配器、执行器、计费与追踪等复杂逻辑补充更细粒度说明

- [x] Task 4: 为测试与辅助脚本补充必要中文注释并统一风格
  - [x] SubTask 4.1: 完成 backend/tests 下测试文件的注释补充
  - [x] SubTask 4.2: 完成 init_experience_memory.py、migrate_db.py、test_final_validation.py 等辅助文件的注释补充
  - [x] SubTask 4.3: 删除或避免无效、重复、过时注释，统一措辞与结构

- [x] Task 5: 进行质量验证并回填规格清单
  - [x] SubTask 5.1: 运行后端相关语法检查、类型检查、测试或项目既有验证命令
  - [x] SubTask 5.2: 抽样复核关键模块，确认注释与代码实现一致且未改变逻辑
  - [x] SubTask 5.3: 回填 checklist.md，标记通过的验收项

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 1
- Task 4 依赖 Task 1
- Task 5 依赖 Task 2、Task 3、Task 4
