# 经验记忆系统规范

## 为什么需要经验记忆

当前Open-AwA系统的记忆系统仅支持会话级短期记忆（ShortTermMemory）和持久化长期记忆（LongTermMemory），但缺乏对**工作过程经验的抽象、归纳和复用**能力。这导致AI Agent在处理相似任务时无法利用历史积累的有效方法论，每次都需要重新探索解决路径，造成效率低下和资源浪费。

根据Meta AI 2025年的研究《Scaling Agent Learning via Experience Synthesis》，AI Agent的持续学习面临四大挑战：高昂的rollout成本、有限的任务多样性、不可靠的奖励信号、基础设施复杂性。解决这些问题的核心思路是**从工作流中合成高质量经验数据，并建立有效的经验复用机制**（Chen et al., 2025）。

此外，ALMA论文（Xiong et al., 2026）指出基础模型的statelessness（无状态性）是限制Agent持续学习能力的核心瓶颈。当前的人工设计记忆机制无法适应真实世界任务的多样性和非平稳性，需要**元学习驱动的自适应记忆设计**。

## 经验记忆模块与现有系统的关系

### 现有记忆架构

```
用户输入 → Comprehension → Planning → Execution → Feedback → 记忆更新
                              ↑                    ↓
                    ShortTermMemory ← LongTermMemory
```

### 新增经验记忆后的架构

```
用户输入 → Comprehension → Planning → Execution → Feedback → 记忆更新
                              ↑                    ↓
              ExperienceMemory ← Skill自动调用经验提取
                              ↓
                    ShortTermMemory ← LongTermMemory
```

**关键变化**：在Feedback层之后，新增经验提取环节。当AI完成工作后，**经验提取Skill会被自动触发**，从工作流中识别、提取、归纳可复用的经验，并存储到ExperienceMemory中。下次处理类似任务时，系统会检索相关经验并注入上下文。

## 新增内容

### 1. 经验记忆数据模型

**ExperienceMemory表结构**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer (PK) | 经验ID |
| experience_type | String | 经验类型：strategy/method/error_pattern/tool_usage/context_handling |
| title | String(200) | 经验标题（如"处理大文件的分块策略"） |
| content | Text | 经验详细内容 |
| trigger_conditions | Text | 触发条件描述（JSON格式，描述何时应用此经验） |
| success_metrics | Float | 成功率指标（0.0-1.0） |
| usage_count | Integer | 被检索使用次数 |
| success_count | Integer | 成功应用次数 |
| source_task | String | 来源任务类型 |
| created_at | DateTime | 创建时间 |
| last_access | DateTime | 最后访问时间 |
| confidence | Float | 置信度评分（基于提取质量评估） |
| metadata | Text | 附加元数据（JSON格式） |

**ExperienceExtractionLog表**（用于追踪经验提取过程）：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer (PK) | 日志ID |
| session_id | String | 会话ID |
| task_summary | Text | 任务摘要 |
| extracted_experience | Text | 提取的经验内容 |
| extraction_trigger | String | 触发原因：success/failure/manual/periodic |
| extraction_quality | Float | 提取质量评分 |
| reviewed | Boolean | 是否经过人工审核 |
| created_at | DateTime | 创建时间 |

### 2. 经验提取Skill规范

**Skill名称**：experience-extractor

**Skill描述**：在工作流完成后自动分析并提取可复用的经验模式

**触发机制**：

- **自动触发**：任务成功完成或失败后，由AI Agent自动调用
- **手动触发**：用户通过指令"/extract-experience"主动触发
- **定期触发**：系统定时扫描近期会话，提取潜在经验

**核心Prompt模板**：

```yaml
experience_extraction_prompt: |
  你是一个经验提取专家。请分析以下工作会话，提取可复用的经验：

  ## 会话上下文
  用户目标：{user_goal}
  执行过程：{execution_steps}
  最终结果：{final_result}
  状态：{status}（成功/失败）

  ## 提取要求
  1. 识别成功模式：如果任务成功，总结有效的策略、方法、工具使用技巧
  2. 识别失败教训：如果任务失败，分析失败原因和避免方法
  3. 识别通用模式：提炼适用于其他类似任务的通用经验
  4. 定义触发条件：明确说明在什么情况下应使用此经验

  ## 输出格式
  请以以下JSON格式输出经验：
  {
    "experience_type": "strategy|method|error_pattern|tool_usage|context_handling",
    "title": "简短描述性标题（不超过50字）",
    "content": "详细经验描述（100-500字）",
    "trigger_conditions": "在什么情况下应检索和应用此经验",
    "confidence": 0.0-1.0的置信度评分
  }

  如果没有值得提取的经验，请输出：{"no_experience": true, "reason": "原因说明"}
```

### 3. 经验检索与复用机制

**检索时机**：在PlanningLayer创建计划之前

**检索流程**：

```python
async def retrieve_relevant_experiences(task_context: Dict) -> List[ExperienceMemory]:
    # 1. 分析当前任务特征
    task_features = extract_task_features(task_context)

    # 2. 多维度检索
    experiences = []

    # 精确匹配：同类型任务的成功经验
    exact_matches = await memory_manager.search_experiences(
        source_task=task_context['task_type'],
        min_success_rate=0.7
    )
    experiences.extend(exact_matches)

    # 语义检索：基于任务描述的语义相似度
    semantic_matches = await memory_manager.semantic_search_experiences(
        query=task_context['description'],
        limit=5
    )
    experiences.extend(semantic_matches)

    # 规则检索：基于触发条件匹配
    rule_matches = await memory_manager.rule_based_search(
        conditions=task_features
    )
    experiences.extend(rule_matches)

    # 3. 去重和排序
    experiences = deduplicate_and_rank(experiences)

    # 4. 注入上下文提示
    return experiences[:3]  # 最多返回3个最相关经验
```

**上下文注入方式**：将检索到的经验作为系统提示注入到PlanningLayer的上下文中

### 4. 经验质量保障机制

**评估维度**：

- **实用性评分**：经验被检索后成功应用的比率
- **时效性评分**：经验与当前任务的相关程度
- **泛化性评分**：经验在不同场景下的适用广度
- **独特性评分**：经验与其他经验的差异化程度

**质量更新触发**：

- 每次经验被检索使用时，更新usage_count
- 每次经验被成功应用时，更新success_count
- 定期（每周）重新计算confidence：`(success_count / usage_count) * (1 - decay_rate)^weeks_since_creation`

**低质量经验处理**：

- confidence < 0.3且usage_count > 10的经验标记为"待审核"
- confidence < 0.2且usage_count > 20的经验自动归档到"经验归档库"

### 5. API路由设计

**新增路由**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /experiences | 获取经验列表（支持分页、筛选、排序） |
| GET | /experiences/{id} | 获取单个经验详情 |
| POST | /experiences | 手动创建经验 |
| PUT | /experiences/{id} | 更新经验 |
| DELETE | /experiences/{id} | 删除经验 |
| POST | /experiences/extract | 手动触发经验提取 |
| GET | /experiences/search | 检索相关经验 |
| GET | /experiences/stats | 获取经验统计信息 |
| GET | /experiences/logs | 获取提取日志 |
| PUT | /experiences/{id}/review | 审核经验 |

**查询参数**：

- `type`: 经验类型筛选
- `min_confidence`: 最低置信度筛选
- `source_task`: 来源任务筛选
- `sort_by`: 排序字段（confidence/usage_count/success_count/created_at）
- `order`: 升序/降序（asc/desc）
- `page`, `limit`: 分页参数

## 技术实现要点

### 1. Skill调用集成

在现有的`core/agent.py`中，在`process()`方法的Feedback层之后添加经验提取调用：

```python
async def process(self, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
    # ... 现有流程 ...

    # 经验提取触发
    if context.get('extract_experience', False):
        await self.extract_and_store_experience(
            session_id=context['session_id'],
            task_result=results,
            status='completed' if final_response else 'failed'
        )

    return {
        "status": "completed",
        "response": final_response,
        "results": results
    }
```

### 2. 触发条件配置

通过配置决定何时自动触发经验提取：

```yaml
experience_auto_extraction:
  enabled: true
  triggers:
    - on_task_success: true  # 任务成功时提取
    - on_task_failure: true  # 任务失败时提取
    - min_task_complexity: 3  # 最低复杂度（1-5）
  batch_interval_hours: 24  # 批量提取间隔
```

### 3. 性能优化

- 经验检索使用向量数据库（如ChromaDB）加速语义检索
- 热门经验缓存在内存中
- 定期清理过期经验，控制数据库大小

## 经验类型分类

### Strategy（策略经验）

**定义**：关于任务分解、规划、优先级排序的高层策略

**示例**：

```json
{
  "title": "大型重构任务应先建立测试覆盖",
  "content": "在进行涉及多个模块的重构时，首先应建立或完善单元测试和集成测试。这能在重构过程中快速发现回归问题，减少调试时间。",
  "trigger_conditions": "任务涉及多个文件/模块的修改，且修改存在依赖关系"
}
```

### Method（方法经验）

**定义**：具体操作步骤、工具使用技巧

**示例**：

```json
{
  "title": "使用git stash临时保存未完成的修改",
  "content": "当需要临时切换分支处理紧急任务，但当前修改尚未完成时，使用git stash保存工作进度。完成紧急任务后，使用git stash pop恢复修改。",
  "trigger_conditions": "用户需要切换任务但不想提交未完成的修改"
}
```

### Error_Pattern（错误模式）

**定义**：常见错误及其解决方案

**示例**：

```json
{
  "title": "Python ImportError处理",
  "content": "当遇到ImportError时，首先检查包是否已安装（pip list），然后确认Python版本兼容性，最后检查__init__.py是否存在。",
  "trigger_conditions": "执行Python代码时遇到ImportError"
}
```

### Tool_Usage（工具使用经验）

**定义**：特定工具的高效使用技巧

**示例**：

```json
{
  "title": "VSCode多光标编辑技巧",
  "content": "使用Alt+Click添加光标，Ctrl+Shift+L选择所有相同内容，Ctrl+D逐个选择。对于批量重命名，先选中一个，然后使用Ctrl+Shift+L全选后统一修改。",
  "trigger_conditions": "用户需要进行批量文本编辑"
}
```

### Context_Handling（上下文处理经验）

**定义**：关于如何理解和管理任务上下文的经验

**示例**：

```json
{
  "title": "模糊需求应先澄清再执行",
  "content": "当用户需求描述不明确时（如'优化性能'、'改进界面'），应先向用户确认具体目标、指标和约束条件，再开始实施。避免在未澄清的情况下投入大量时间。",
  "trigger_conditions": "用户的需求描述包含模糊词汇（优化/改进/调整等）"
}
```

## 前端页面需求

### 经验管理页面（ExperiencePage.tsx）

**功能模块**：

1. **经验列表视图**
   - 卡片式展示，每个经验显示：标题、类型标签、置信度、成功率、使用次数
   - 支持筛选：类型、置信度范围、来源任务
   - 支持排序：按置信度、使用次数、创建时间
   - 分页显示

2. **经验详情面板**
   - 完整经验内容展示
   - 触发条件说明
   - 使用统计图表（随时间的使用趋势）
   - 编辑和删除操作

3. **经验提取日志**
   - 显示系统自动提取的经验
   - 支持人工审核：批准/修改/拒绝
   - 显示提取质量评分

4. **统计概览**
   - 经验总数、各类型分布
   - 平均置信度、平均成功率
   - 近期活跃经验排行
   - 提取趋势图

5. **手动提取入口**
   - 选择历史会话触发经验提取
   - 输入任务描述进行经验生成

## 依赖关系

- **数据库**：新增ExperienceMemory和ExperienceExtractionLog两张表
- **现有模块**：复用MemoryManager的模式和接口
- **Skill系统**：创建新的experience-extractor Skill
- **Agent集成**：在core/agent.py的Feedback层后添加调用
- **前端**：创建ExperiencePage.tsx页面

## 迁移策略

1. **数据迁移**：无需迁移，现有记忆数据保持不变
2. **功能开关**：通过配置项控制经验记忆功能，默认关闭
3. **渐进启用**：先开放手动提取，验证稳定后开启自动提取

## 风险与缓解

### 风险1：经验质量参差不齐

**缓解措施**：

- 设置置信度阈值，低于阈值的经验不自动注入
- 提供人工审核机制
- 基于成功率动态调整经验权重

### 风险2：经验过拟合

**缓解措施**：

- 限制同一来源任务的经验数量
- 定期评估经验的泛化性
- 鼓励提取更通用的经验而非特定案例

### 风险3：数据库膨胀

**缓解措施**：

- 设置经验存储上限（如1000条）
- 自动归档低置信度经验
- 支持经验合并和去重

## 参考资料

1. Chen, Z., et al. (2025). Scaling Agent Learning via Experience Synthesis. Meta AI.
2. Xiong, Y., et al. (2026). Learning to Continually Learn via Meta-learning Agentic Memory Designs. arXiv:2602.07755.
3. Wang, Y., & Chen, X. (2025). MIRIX: Multi-Agent Memory System for LLM-Based Agents. arXiv:2507.07957.
4. Hinton, G., et al. (2015). Distilling the Knowledge in a Neural Network.
