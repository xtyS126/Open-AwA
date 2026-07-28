# bilibili-toolkit-builtin

bilibili-toolkit-builtin 内置插件，以 vendored 方式将 OpenBiliClaw 完整源码嵌入 Open-AwA，
通过 OpenClaw 适配层对外暴露 10 个技能（账号同步、推荐、对话、推测探针等）。

## 来源与版本

- 上游项目: OpenBiliClaw
- 上游版本: v0.3.147
- 上游仓库: https://github.com/whiteguo233/OpenBiliClaw
- 上游 License: MIT

## 接入方式

- **vendored**：将上游 `src/openbiliclaw/` 完整复制到本目录 `src/openbiliclaw/`，
  不依赖系统已安装的 `openbiliclaw` 包，避免版本漂移。
- 加载入口：`plugin.py` 中的 `BilibiliToolkitBuiltinPlugin(BasePlugin)`，
  在 `initialize()` 内通过 `importlib.util.spec_from_file_location` 显式加载
  `src/openbiliclaw/integrations/openclaw/bootstrap.py`，避免污染全局 `sys.path`。
- 适配层：`adapter.py` 中的 `BilibiliToolkitAdapter` 包装上游 `OpenClawAdapter`，
  并将 `build_openclaw_skills()` 返回的 `OpenClawSkillDescriptor` 转换为
  Open-AwA 工具定义（`name` / `description` / `parameters` / `handler`）。

## 依赖清单

见 `requirements.txt`。关键依赖：

- `httpx>=0.27`
- `pydantic>=2.0`
- `loguru>=0.7`
- `bilibili-api-python>=16`
- `google-genai>=1.66`
- `ollama>=0.4`
- `openai>=1.0`
- `anthropic>=0.40`

## 如何初始化

1. 安装依赖：`pip install -r backend/plugins/bilibili_toolkit_builtin/requirements.txt`
2. 启动 Open-AwA 后端，`PluginManager` 会在 `_startup_plugin_load_enabled()`
   中自动 seed 一条 `name="bilibili-toolkit-builtin"`、`source="builtin"`、
   `category="builtin"`、`enabled=True`、`is_uninstallable=True` 的记录。
3. 加载时若关键依赖缺失，`BilibiliToolkitBuiltinPlugin.initialize()` 会抛出
   `BuiltinPluginDependencyError`（携带 `missing_packages` 列表），
   `main.py` 中捕获后仅记录 WARNING，不阻塞启动。
4. 加载成功后通过 `GET /api/plugins` 可见，工具通过 `get_tools()` 暴露给 Agent。

## 卸载说明

该插件 `is_uninstallable=True`，`DELETE /api/plugins/bilibili-toolkit-builtin` 与
`POST /api/plugins/bilibili-toolkit-builtin/disable` 端点会返回 403，仅允许"查看配置"。

## 数据迁移说明

启动时 `main.py` 的 `_seed_builtin_plugins_sync()` 会自动检测旧名 `openbiliclaw-builtin`
的数据库种子记录，将其 UPDATE 为 `bilibili-toolkit-builtin`，保留 `enabled` / `source` /
`category` / `is_uninstallable` / 配置 JSON（含加密字段）。迁移幂等，已迁移过则跳过。

## 视频下载能力

本插件在原 OpenBiliClaw 信息获取能力之上，移植了 bili-sync（Rust 实现）的视频同步下载
链路，用 Python 完整重写，支持 B 站视频的自动化同步下载与媒体库元数据生成。

### 四种订阅源

- **Favorite（收藏夹）**：按 `media_id` 订阅用户收藏夹，调用 `/x/v3/fav/resource/list`
  拉取视频列表，按 mtime 倒序增量扫描（`latest_row_at` 水位线）。
- **Collection（合集）**：按 `season_id` 或 `series_id` 订阅合集，Season 调用
  `/x/polymer/web-space/seasons_archives_list`，Series 调用 `/x/series/archives`，
  全量拉取后过滤已下载视频。
- **Submission（UP 主投稿）**：按 `upper_mid` 订阅 UP 主投稿，调用
  `/x/space/wbi/arc/search`（需 WBI 签名），可选 `use_dynamic_api` 处理置顶视频。
- **WatchLater（稍后再看）**：全局唯一订阅（id=1），调用 `/x/v2/history/toview`
  拉取稍后再看列表，不增量扫描。

### ffmpeg 依赖

视频下载流程依赖外部 `ffmpeg` 可执行文件用于合并 DASH 格式的独立视频流（m4s）与音频流
（m4s）为 mp4 容器（`-c copy -strict unofficial -f mp4`，不重新编码）。

- 插件 `initialize()` 时通过 `merger.check_ffmpeg()` 检测可用性，不可用仅记录 WARNING，
  不阻塞插件加载。
- 下载任务在合并阶段失败时标记为 `Failed`，错误原因记录 `ffmpeg_unavailable`。
- 安装方式：`apt install ffmpeg` / `brew install ffmpeg` / Windows 从
  https://ffmpeg.org/download.html 下载并加入 PATH。

### 配置项

视频下载相关配置项通过 `schema.json` 定义，支持 WebUI 热更新（无需重启）。主要分组：

- `filter_option`：流筛选选项（清晰度范围、编码偏好、杜比/HDR/HiRES 开关）
- `danmaku_option`：弹幕 ASS 渲染参数（字体、字号、透明度、描边、轨道高度等）
- `skip_option`：跳过子任务开关（封面 / 视频 NFO / UP 主 / 弹幕 / 字幕）
- `concurrent_limit`：并发与限流（video / page / rate_limit / download 分块）
- `trigger`：调度触发器（interval 固定间隔 / cron 表达式）
- `video_name` / `page_name` / `video_default_path` / `page_default_path`：Jinja2 路径模板
- `upper_path` / `nfo_time_type` / `time_format` / `cdn_sorting`：辅助配置

详细字段说明见下方"配置项参考"章节。

### 下载流程

完整下载流水线按以下顺序执行：

1. **订阅扫描**：调度器按 `trigger` 配置定期触发，调用对应订阅源的扫描 API 拉取视频列表，
   按 `latest_row_at` 增量水位线过滤已处理视频。
2. **元数据落库**：视频元信息（bvid / title / cover / upper / pages）写入
   `bilibili_toolkit_videos` 与 `bilibili_toolkit_pages` 表。
3. **playurl 调用**：对每个分 P 调用 `/x/player/wbi/playurl?bvid=&cid=&qn=127&fnval=4048&fourk=1`
   （WBI 签名），解析 5 种流类型（Flv / Html5Mp4 / EpisodeTryMp4 / DashVideo / DashAudio）。
4. **流筛选**：根据 `filter_option` 过滤清晰度范围、编码偏好、杜比/HDR/HiRes，选择最佳
   video 流与 audio 流（或单混合流 Mixed）。
5. **CDN 排序**：`cdn_sorting=true` 时按 `upos-` > `cn-` > `mcdn` > 其他对下载 URL 排序，
   主 URL 与 `backup_url` 一起参与排序。
6. **下载**：大文件（>= `concurrent_limit.download.threshold`，默认 20MB）使用并发分块下载
   （`Range` header），小文件串行流式下载；主 URL 失败按序尝试 `backup_url`。
7. **ffmpeg 合并**：DASH 流合并为 mp4 容器，`-c copy` 不重新编码，完成后 `shutil.copy`
   到最终路径并清理临时文件。
8. **NFO / 弹幕 / 字幕生成**：根据 `skip_option` 并发执行 5 路子任务：
   - 封面下载（视频封面 + 分 P 封面 + UP 主头像）
   - 视频 NFO 生成（Movie / TVShow / Episode / Upper 四种 XML 模板，Emby/Jellyfin 兼容）
   - 弹幕下载（protobuf 解析 + ASS 渲染，lane 碰撞算法）
   - 字幕下载（`/x/player/wbi/v2` + JSON body → SRT 转换，过滤 AI 字幕）
9. **状态记录**：5 个子任务状态按位记录到 `download_status` 字段（每子任务 2 bit，4 态：
   Skipped / Succeeded / Ignored / Failed），失败下轮自动重试，达到 `MAX_RETRY=3` 标记永久失败。
10. **风控熔断**：检测到 `code=-352` / `v_voucher` 非空 / HTTP 412/403 立即抛出
    `RiskControlError`，整轮终止，等待下一轮调度再尝试。

## 数据库表

视频下载能力新增 4 张数据库表，ORM 模型定义在 `backend/db/models/bilibili_toolkit.py`，
Alembic 迁移脚本位于 `backend/migrations/versions/`。

### bilibili_toolkit_videos

视频元数据表，记录每个 B 站视频的基础信息与整体下载状态。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer (PK) | 自增主键 |
| bvid | String (unique) | B 站视频 BV 号 |
| aid | Integer | B 站视频 AV 号 |
| title | String | 视频标题 |
| cover | String | 视频封面 URL |
| upper_mid | String | UP 主 mid |
| upper_name | String | UP 主名称 |
| pages_count | Integer | 分 P 数量 |
| pubtime | Integer | 发布时间戳 |
| fav_time | Integer | 收藏时间戳 |
| download_status | Integer | 下载状态位图（5 子任务 × 2 bit） |
| created_at | DateTime | 记录创建时间 |
| updated_at | DateTime | 记录更新时间 |

### bilibili_toolkit_pages

视频分 P 信息表，每个分 P 对应一条记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer (PK) | 自增主键 |
| video_id | Integer (FK) | 关联 `bilibili_toolkit_videos.id` |
| cid | Integer | B 站分 P cid |
| page | Integer | 分 P 序号（从 1 开始） |
| name | String | 分 P 标题 |
| duration | Integer | 分 P 时长（秒） |
| width | Integer | 视频宽度 |
| height | Integer | 视频高度 |
| download_status | Integer | 分 P 下载状态位图 |

### bilibili_toolkit_subscriptions

订阅源表，记录用户的订阅配置。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer (PK) | 自增主键 |
| type | String | 订阅类型（favorite / collection / submission / watchlater） |
| source_id | String | 订阅源 ID（media_id / season_id / series_id / upper_mid） |
| name | String | 订阅名称 |
| path | String | 下载根路径 |
| rule | JSON | 订阅规则配置 |
| filter_option | JSON | 流筛选选项（覆盖全局配置） |
| latest_row_at | Integer | 增量扫描水位线（最新视频时间戳） |
| enabled | Boolean | 是否启用 |
| created_at | DateTime | 订阅创建时间 |

### bilibili_toolkit_download_tasks

下载任务记录表，记录每个子任务的执行状态与重试信息。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer (PK) | 自增主键 |
| video_id | Integer (FK) | 关联 `bilibili_toolkit_videos.id` |
| page_id | Integer (FK) | 关联 `bilibili_toolkit_pages.id` |
| subtask | String | 子任务类型（cover / video / nfo / danmaku / subtitle） |
| status | String | 任务状态（pending / running / succeeded / failed / skipped） |
| retry_count | Integer | 已重试次数（达到 MAX_RETRY=3 后永久失败） |
| error | Text | 失败原因 |
| created_at | DateTime | 任务创建时间 |
| updated_at | DateTime | 任务更新时间 |

## API 路由

视频下载能力新增 8 个 REST API 路由，前缀为 `/api/plugins/bilibili-toolkit-builtin`，
路由定义在 `backend/plugins/bilibili_toolkit_builtin/api/routes.py`。所有路由需登录鉴权。

### GET /api/plugins/bilibili-toolkit-builtin/subscriptions

列出当前用户的所有订阅源。

- **响应**：`List[SubscriptionResponse]`，每条含 id / type / source_id / name / path /
  enabled / latest_row_at 等字段。

### POST /api/plugins/bilibili-toolkit-builtin/subscriptions

添加新的订阅源。

- **请求体**：`SubscriptionCreate`，含 type / source_id / name / path / filter_option（可选）。
- **响应**：`SubscriptionResponse`，含新建订阅的完整信息。
- **错误**：type 非法、source_id 为空返回 422；订阅已存在返回 409。

### DELETE /api/plugins/bilibili-toolkit-builtin/subscriptions/{id}

删除指定订阅源。

- **路径参数**：`id` 订阅 ID。
- **响应**：204 No Content。
- **错误**：订阅不存在返回 404；订阅不属于当前用户返回 403。

### GET /api/plugins/bilibili-toolkit-builtin/videos

查询已下载视频列表与下载状态。

- **查询参数**：`subscription_id`（可选，按订阅过滤）、`status`（可选，按状态过滤）、
  `page` / `page_size`（分页）。
- **响应**：`List[VideoResponse]`，每条含 bvid / title / upper / pages_count /
  download_status / 子任务状态详情。

### POST /api/plugins/bilibili-toolkit-builtin/trigger/{id}

手动触发指定订阅的下载任务（不等调度器）。

- **路径参数**：`id` 订阅 ID。
- **响应**：`TriggerResponse`，含 task_id 与触发的视频数。
- **错误**：订阅不存在或已禁用返回 404。

### GET /api/plugins/bilibili-toolkit-builtin/tasks

查询下载任务状态。

- **查询参数**：`subscription_id`（可选）、`video_id`（可选）、`status`（可选）、
  `page` / `page_size`（分页）。
- **响应**：`List[TaskResponse]`，每条含 video_id / page_id / subtask / status /
  retry_count / error。

### GET /api/plugins/bilibili-toolkit-builtin/config

获取当前插件配置（含视频下载相关配置项）。

- **响应**：`Dict[str, Any]`，含 schema.json 中所有配置项的当前值。
- **敏感字段**：cookie 等敏感字段返回掩码（如 `***sessdata***`）。

### PUT /api/plugins/bilibili-toolkit-builtin/config

更新插件配置（热更新，无需重启）。

- **请求体**：`Dict[str, Any]`，待更新的配置项。
- **响应**：更新后的完整配置（敏感字段掩码）。
- **副作用**：`trigger` 变更时调度器自动重建 Job；`filter_option` / `danmaku_option` 等
  变更通过 VersionedConfig 立即传播到进行中的下载任务。

## Agent 工具

视频下载能力向 Agent 暴露 5 个工具，定义在 `backend/plugins/bilibili_toolkit_builtin/tools.py`，
通过 `plugin.py:get_tools()` 注册。Agent 可通过这些工具自动化管理 B 站视频订阅与下载。

### bilibili_add_subscription

添加 B 站视频订阅源，触发立即扫描。

- **参数**：
  - `type` (string, required)：订阅类型，枚举 `favorite` / `collection` / `submission` / `watchlater`
  - `source_id` (string, required)：订阅源 ID（media_id / season_id / series_id / upper_mid）
  - `name` (string, optional)：订阅名称，留空则用 source_id
  - `path` (string, optional)：下载根路径，留空则用全局默认
  - `filter_option` (object, optional)：流筛选选项覆盖
- **返回**：`{subscription_id, scanned_videos, first_batch_videos}`，含新建订阅 ID 与首批扫描到的视频列表。

### bilibili_list_subscriptions

列出当前用户的所有 B 站视频订阅。

- **参数**：无
- **返回**：`List[{id, type, source_id, name, path, enabled, latest_row_at}]`。

### bilibili_trigger_download

手动触发指定订阅的下载任务。

- **参数**：
  - `subscription_id` (integer, required)：订阅 ID
- **返回**：`{task_id, triggered_videos, estimated_time}`，含任务 ID 与触发的视频数。
  可配合 `bilibili_get_download_status` 查询下载进度。

### bilibili_get_download_status

查询指定视频或订阅的下载状态。

- **参数**：
  - `video_id` (integer, optional)：视频 ID
  - `subscription_id` (integer, optional)：订阅 ID
  - 至少提供一个，同时提供则取交集
- **返回**：`{video_id, bvid, title, download_status, subtasks: [{name, status, retry_count, error}]}`，
  含子任务进度与失败原因。

### bilibili_list_videos

列出已下载或待下载的 B 站视频。

- **参数**：
  - `subscription_id` (integer, optional)：按订阅过滤
  - `status` (string, optional)：按下载状态过滤
  - `limit` (integer, optional)：返回数量上限，默认 50
- **返回**：`List[{video_id, bvid, title, upper_name, pages_count, download_status, updated_at}]`。

## 配置项参考

以下为 `schema.json` 中视频下载相关配置项的完整清单与默认值。所有配置项均支持 WebUI
热更新，无需重启后端。

### filter_option（流筛选选项）

控制 playurl 解析后的视频/音频流选择范围与编码偏好。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| video_max_quality | string | `8k` | 视频最高清晰度（360p/480p/720p/720p60/1080p/1080p_plus/1080p60/1080p_hdr/1440p/1440p_hfr/1440p_hdr/4k/6k/8k/dolby_vision/hdr） |
| video_min_quality | string | `360p` | 视频最低清晰度（同上枚举） |
| video_codecs | array | `["avc","hevc","av1"]` | 视频编码偏好顺序（avc > hevc > av1） |
| audio_max_quality | string | `hires` | 音频最高清晰度（dolby/hires/high） |
| audio_min_quality | string | `high` | 音频最低清晰度（同上枚举） |
| audio_codecs | array | `["mp4a","ec3"]` | 音频编码偏好顺序 |
| no_dolby_video | boolean | `false` | 过滤杜比视界视频流 |
| no_dolby_audio | boolean | `false` | 过滤杜比全景声音频流 |
| no_hdr | boolean | `false` | 过滤 HDR 视频流 |
| no_hires | boolean | `false` | 过滤 HiRes 音频流 |

### danmaku_option（弹幕渲染选项）

控制 ASS 弹幕字幕的渲染参数。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| font | string | `sans-serif` | ASS 字体名称（需系统已安装） |
| font_size | number | `1.0` | 字号缩放系数（1.0 = 25px） |
| alpha | number | `0.7` | 不透明度 0-1 |
| stroke | number | `1.5` | 描边宽度（像素） |
| lane_size | number | `32` | 轨道高度（像素） |
| duration | number | `15.0` | 滚动弹幕时长（秒） |
| width_ratio | number | `1.2` | 弹幕宽度比例 |
| horizontal_gap | number | `20.0` | 最小水平间距（像素） |
| float_percentage | number | `0.5` | 滚动弹幕高度百分比 |
| bottom_percentage | number | `0.3` | 底部弹幕高度百分比 |
| bold | boolean | `true` | 是否加粗 |
| time_offset | number | `0.0` | 时间轴偏移（秒） |

### skip_option（跳过子任务选项）

控制是否跳过特定子任务的下载与生成，跳过的子任务标记为 Skipped。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| no_poster | boolean | `false` | 跳过封面下载 |
| no_video_nfo | boolean | `false` | 跳过视频 NFO 生成 |
| no_upper | boolean | `false` | 跳过 UP 主 NFO 与头像 |
| no_danmaku | boolean | `false` | 跳过弹幕下载与 ASS 渲染 |
| no_subtitle | boolean | `false` | 跳过字幕下载与 SRT 转换 |

### concurrent_limit（并发与限流配置）

下载流程的并发数与速率限制。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| video | integer | `3` | 视频级并发数（同时处理的视频数） |
| page | integer | `2` | 分 P 并发数（单视频并发分 P 数） |
| rate_limit | number | `2.0` | B 站 API 每秒最大请求数 |
| download.concurrency | integer | `4` | 单文件并发分块数 |
| download.threshold | integer | `20971520` | 启用并发分块的文件大小阈值（字节，默认 20MB） |

### trigger（调度触发器）

下载任务的调度触发器配置，变更后调度器自动重建 Job。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| type | string | `interval` | 触发器类型（interval / cron） |
| seconds | integer | `1200` | interval 间隔秒数（仅 type=interval 生效，默认 20 分钟） |
| expr | string | `0 0 * * *` | cron 表达式（仅 type=cron 生效，5 字段：分 时 日 月 周） |

### 路径模板与辅助配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| video_name | string | `{{title}}` | 视频目录名 Jinja2 模板（变量：bvid / title / upper_name / upper_mid / pubtime / fav_time） |
| page_name | string | `{{bvid}}` | 分 P 文件名 Jinja2 模板（在 video 变量基础上追加 ptitle / pid） |
| video_default_path | string | `videos/{{title}}` | 视频默认根目录模板（无 video_name 时回退） |
| page_default_path | string | `{{bvid}}` | 分 P 默认文件名模板（无 page_name 时回退） |
| upper_path | string | `upers` | UP 主 NFO 与头像存储根目录名 |
| nfo_time_type | string | `fav` | NFO 时间字段类型（fav=收藏时间 / pub=发布时间） |
| time_format | string | `%Y-%m-%d %H:%M:%S` | 时间变量渲染的 strftime 格式 |
| cdn_sorting | boolean | `true` | 启用 CDN 智能排序（upos- > cn- > mcdn > 其他） |

## 命令示例

```bash
# 安装依赖（含视频下载新增的 protobuf / jinja2）
pip install -r backend/plugins/bilibili_toolkit_builtin/requirements.txt

# 检测 ffmpeg 是否可用
ffmpeg -version

# 启动后端（自动 seed bilibili-toolkit-builtin 插件记录）
cd backend
python main.py

# 查询当前订阅列表
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/plugins/bilibili-toolkit-builtin/subscriptions

# 添加收藏夹订阅
curl -X POST -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"type":"favorite","source_id":"12345678","name":"我的收藏夹"}' \
  http://localhost:8000/api/plugins/bilibili-toolkit-builtin/subscriptions

# 手动触发订阅下载
curl -X POST -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/plugins/bilibili-toolkit-builtin/trigger/1

# 查询下载任务状态
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/plugins/bilibili-toolkit-builtin/tasks

# 获取当前配置
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/plugins/bilibili-toolkit-builtin/config

# 更新配置（热更新）
curl -X PUT -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"trigger":{"type":"interval","seconds":600}}' \
  http://localhost:8000/api/plugins/bilibili-toolkit-builtin/config
```
