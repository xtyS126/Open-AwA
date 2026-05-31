# 微信扫码“硬编码参数导致字符串返回”专项排查

## 1. 排查目标与结论

### 1.1 目标

按 `.trae/specs/investigate-weixin-qr-hardcoded-param-impact/spec.md` 的新要求，验证以下问题：

- 是否存在“硬编码参数被改动，直接导致扫码接口仅返回普通字符串”的因果链路。
- 该现象发生在“上游响应阶段”还是“本地解析阶段”。
- 当前代码是否已具备对字符串返回的兼容能力。

### 1.2 最终结论

结论：**未发现“硬编码参数改动 => 扫码仅返回字符串”的直接证据。**

更高概率路径是：

1. 上游在部分场景返回文本、键值串或 JSON 字符串（非标准对象）。
2. 本地若未解析会表现为“字符串返回”。
3. 当前项目后端已实现多形态字符串解析与归一化，能将该类返回转换为结构化状态继续推进。

因此，硬编码参数不是本问题的一阶根因；其影响主要体现在“请求是否成功/命中正确节点”，而不是“把对象强制变成字符串”。

## 2. 参数对照（当前实现 vs 参考实现）

### 2.1 关键硬编码项

| 项目 | 当前项目 | 参考实现（`别人解析`） | 结论 |
|---|---|---|---|
| 二维码起始域名 | `DEFAULT_QR_BASE_URL=https://ilinkai.weixin.qq.com`（固定） | `opts.apiBaseUrl`（可配置） | 差异存在，但不直接决定响应是否为字符串 |
| `bot_type` 默认值 | `"3"` | `"3"` | 一致 |
| 轮询请求头 `iLink-App-ClientVersion` | `"1"` | `"1"` | 一致 |
| 轮询基址切换 | 支持 `scaned_but_redirect` 后切换 `redirect_host` | 同样支持（源码版与当前项目均支持） | 一致 |

### 2.2 对“硬编码致因”判断的影响

- 以上参数即使配置错误，通常表现为 HTTP 错误、超时、无二维码等，不是“把结构化 JSON 变成纯字符串”。
- “字符串返回”更像是上游网关/节点返回文本体（例如纯文本、URL、`k=v` 串），属于响应形态差异，不是参数类型被本地改写。

## 3. 证据链

### 3.1 代码证据：后端具备字符串兼容解析

`backend/api/routes/skills.py` 中 `_coerce_weixin_response_payload(...)` 与 `_normalize_qr_wait_status(...)` 已覆盖：

- JSON 字符串 -> 对象
- URL query / `k=v` 串 -> 对象
- 纯文本状态（`wait/scaned/confirmed/...`）-> 统一字段
- 纯文本消息 -> `raw_text/message`

这说明“收到字符串”不会直接导致流程中断，而是被吸收进入统一状态机。

### 3.2 测试证据：字符串场景可被正确处理

`backend/tests/test_api_skills_weixin.py` 已包含多组用例：

- `test_weixin_qr_start_accepts_json_string_upstream_payload`
- `test_weixin_qr_start_extracts_qrcode_from_key_value_string_payload`
- `test_weixin_qr_wait_parses_json_string_status_payload`
- `test_weixin_qr_wait_parses_key_value_string_status_payload`
- `test_weixin_qr_wait_preserves_plain_string_status_message`

这些用例直接证明：上游返回字符串时，后端可归一化为可消费结构并维持扫码状态流转。

### 3.3 日志证据：源码内可观测点能区分“上游文本”与“本地归一化”

后端日志打点（`backend/api/routes/skills.py`）：

- `qr_start_upstream_result`：记录上游返回预览
- `status_polled`：记录归一化后的 `status/state/connected`
- `confirmed_missing_credentials`：记录“确认但字段未齐”的降级判定
- `transient_upstream_error`：记录临时网络异常回退为 `wait`

适配层日志（`backend/skills/weixin_skill_adapter.py`）：

- `_api_get` debug 输出状态码、`content-type` 与响应体截断
- `get_qrcode_status` 超时回退 `{"status":"wait"}` 的 debug 记录

这些日志足以在排障时确认：

- 原始响应是否为字符串（上游）
- 字符串是否被正确归一化（本地）

## 4. 反证分析（为何不是“硬编码直接致因”）

### 4.1 反证 A：固定二维码域名并未阻断字符串解析

`test_weixin_adapter_fetch_login_qrcode_uses_fixed_qr_base_url` 证明当前实现确实固定使用 `DEFAULT_QR_BASE_URL`。

但与此同时，字符串解析相关测试均通过，说明“固定域名”与“是否能处理字符串返回”是两条独立维度。

### 4.2 反证 B：关键硬编码与参考实现基本一致

- `bot_type=3` 一致
- `iLink-App-ClientVersion=1` 一致
- 长轮询超时回退 `wait` 的策略一致

若根因是这类硬编码漂移，应出现“参数明显不一致”的证据；目前未观察到。

### 4.3 反证 C：字符串可由上游/网关场景自然产生

在网络抖动、网关回包非 JSON、节点切换中间态下，返回文本体是可预期现象。当前代码专门增加了容错路径，符合该事实模型。

## 5. 最小验证（与当前代码一致性）

建议最小验证命令：

```powershell
cd d:\代码\Open-AwA\backend
python -m pytest backend/tests/test_weixin_skill_adapter.py::test_weixin_adapter_fetch_login_qrcode_uses_fixed_qr_base_url backend/tests/test_api_skills_weixin.py::test_weixin_qr_wait_parses_key_value_string_status_payload backend/tests/test_api_skills_weixin.py::test_weixin_qr_wait_preserves_plain_string_status_message
```

验证通过标准：

- 固定参数行为与预期一致（证明“确有硬编码”）。
- 字符串载荷可被解析为结构化状态（证明“硬编码不直接导致字符串问题”）。

## 6. 风险评估

### 6.1 当前剩余风险

- 上游协议新增状态或字段，未被本地归一化规则覆盖。
- 某些网关返回非 UTF-8 或异常拼接文本，解析可能退化为 `raw_text`。
- `DEFAULT_QR_BASE_URL` 固定策略在未来多区/多环境部署时可能带来可用性风险（但不等同于“字符串根因”）。

### 6.2 风险等级

- 根因误判风险：低（证据较完整）
- 未来协议漂移风险：中
- 部署环境域名差异风险：中

## 7. 建议动作

### 7.1 短期

- 线上排查时固定抓取 `qr_start_upstream_result` 与 `status_polled` 两类日志，建立请求-归一化对照。
- 当出现“仅字符串”现象时，优先判断上游响应类型，不要先入为主归因为硬编码参数。

### 7.2 中期

- 为 `_normalize_qr_wait_status` 增加“未知状态字典”的观测埋点，降低协议漂移盲区。
- 将 `DEFAULT_QR_BASE_URL` 是否可配置化纳入后续演进评估（面向多环境/内网代理场景）。

## 8. 本次结论摘要

- **结论**：未证实“硬编码参数改动直接导致扫码仅返回字符串”。
- **证据**：源码解析器、测试用例、日志打点三条证据链均支持“字符串来自上游形态，本地已兼容归一化”。
- **反证**：参数对照未发现关键漂移，且存在独立测试证明“固定参数”与“字符串可解析”同时成立。
- **决策建议**：后续排障应聚焦“上游响应形态 + 本地归一化覆盖率”，而非仅盯硬编码参数本身。
