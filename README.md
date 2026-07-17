# Audit Radar

AI 行业情报自动监控系统：每日从 27 个信源采集候选，经 LLM 四级加工（粗筛 → 去重 → 共振 → 精排）生成 HTML 日报，通过 SMTP 邮件推送；每周六从深度池生成周报。运行于阿里云函数计算（FC），SQLite 持久化在 NAS。

## 两条流水线

**日报（`index.py`，每日定时触发）**

```
采集 Fetcher → URL 跨天去重 → 论文入库/富化 → LLM 粗筛 Selector
→ Jaccard 内容去重（灰区可选 AI）→ 多源共振 ResonanceDetector
→ LLM 精排 Ranker（Top 8）→ LLM 生成 Generator（8 选 3-5，HTML）
→ 记录已报道 URL → SMTP 发送 Sender（当日防重）
```

**周报（`weekly.py`，每周六触发）**

```
读取本周 deep_dive_queue（播客/长文候选）→ [音频转录：占位，未启用]
→ WeeklyGenerator 生成 HTML → 标记 processed → 发送邮件（当周防重）
```

## 目录结构

| 路径 | 说明 |
|------|------|
| `index.py` / `weekly.py` | 日报 / 周报入口（FC handler + 本地 `python index.py`） |
| `config.py` | 全部配置，均从环境变量读取 |
| `sources.json` | 27 个信源：21 RSS + 3 API（NVD/HF/HN）+ 3 NewsNow；播客源走 weekly 周期 |
| `core/` | 采集 `fetcher`、粗筛 `selector`、去重 `dedup`、共振 `resonance`、精排 `ranker`、生成 `generator` / `weekly_generator`、发送 `sender`、存储 `storage/sqlite_backend`、LLM 客户端 `llm_client`、Skill 加载 `skill_loader` |
| `skills/<name>/SKILL.md` | 4 个 LLM Skill 的 system prompt：`rss-audit-screener` → `cross-source-resonance` → `audit-news-ranker` → `report-generator`（周报 prompt 内嵌于 `weekly_generator.py`） |
| `build.py` | 打包部署 zip（依赖装到根目录）；`.github/workflows/deploy.yml.disabled` 为停用的 CI 部署 |
| `FLOW.md` / `DEPLOY.md` | 详细流程文档 / 阿里云 FC + NAS 部署清单 |

## 关键机制

- **两级去重**：URL 精确匹配（采集后）+ Jaccard bigram 内容相似度（粗筛后），均对比 `reported_urls` 近 7 天；Jaccard 0.2~0.8 灰区默认保守过滤，`DEDUP_USE_AI=true` 时交 LLM 判断。
- **共振验证**：标题关键词聚类成事件簇，多源簇且 `RESONANCE_USE_AI=true` 时用 LLM 做一致性校验与加权共振分，否则本地规则打分。
- **模型路由**：统一走 `core.llm_client.chat_completion()`，支持 DeepSeek / Moonshot / 百炼 / GLM；`MODEL_SCREEN` / `MODEL_RANK` / `MODEL_GENERATE` / `MODEL_DEDUP` 可按任务覆盖，格式 `provider:model` 或模型名简写自动推断。
- **防重发**：`push_records` 表按日期/周次 + 渠道判重，已推送则 SKIP。

## 存储（SQLite，`AUDIT_DB_PATH`，默认 `data/audit.db`，FC 上为 NAS 路径）

`candidates`（原始池）、`papers`（论文库）、`repo_history`（GitHub 新增判断）、`reported_urls`（跨天去重）、`screened`、`deep_dive_queue`（周报素材）、`clusters`、`reports` / `weekly_reports`（存档）、`push_records`（推送状态）、`source_status`（信源健康）。

## 运行

```bash
pip install -r requirements.txt   # requests pyyaml
python index.py                   # 本地跑日报
python weekly.py                  # 本地跑周报
python build.py                   # 打 FC 部署包
```

必需环境变量：`*_API_KEY`（按所用供应商）、`MAIL_HOST` / `MAIL_PORT` / `MAIL_USER` / `MAIL_PASS` / `MAIL_TO_LIST`；详见 `DEPLOY.md`。

## 已知限制

- 播客音频转录为占位实现，周报仅基于标题/摘要。
- 邮件是唯一交付通道（内部 IM 无 API），当前使用阿里云 DirectMail SMTP。
