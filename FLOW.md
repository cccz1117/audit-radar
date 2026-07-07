# Audit Radar 流程图

## 1. 日报流程 (index.handler)

```mermaid
flowchart TD
    Start([定时触发 / 手动调用]) --> Fetch[1. Fetcher 采集信源]
    Fetch --> SavePapers[1.1 论文入库 papers 表]
    SavePapers --> SaveCandidates[1.2 保存原始候选 candidates 表]
    SaveCandidates --> UrlDedup[1.3 URL 跨天去重]
    UrlDedup --> MarkRepos[1.4 标记 GitHub repo 新增性]
    MarkRepos --> EnrichPapers[1.5 论文摘要富化]
    EnrichPapers --> Screen[2. Selector 大模型粗筛]
    Screen --> SaveScreened[保存 screened 表]
    Screen --> SaveDeepDive[保存 deep_dive_queue]
    SaveScreened --> ContentDedup[2.5 内容相似度去重]
    ContentDedup --> Resonance[3. ResonanceDetector 多源共振]
    Resonance --> SaveClusters[保存 clusters 表]
    SaveClusters --> Rank[4. Ranker 大模型精排 Top3/Top8]
    Rank --> Generate[5. Generator 生成 HTML 日报]
    Generate --> SaveReport[保存 reports 表]
    SaveReport --> RecordUrls[5.5 记录已报道 URL]
    RecordUrls --> SendMail[6. Sender 发送邮件]
    SendMail --> End([返回 JSON 结果])
```

## 2. 周报流程 (weekly.handler)

```mermaid
flowchart TD
    Start([每周六定时触发]) --> ReadQueue[1. 读取 deep_dive_queue 本周候选]
    ReadQueue --> Audio[2. 音频转录占位]
    Audio --> Generate[3. WeeklyGenerator 生成周报 HTML]
    Generate --> SaveReport[保存 weekly_reports 表]
    SaveReport --> MarkProcessed[4. 标记已处理]
    MarkProcessed --> SendMail[5. Sender 发送邮件]
    SendMail --> End([返回 JSON 结果])
```

## 3. 数据表关系

```mermaid
erDiagram
    candidates ||--o{ screened : "进入粗筛"
    candidates ||--o{ papers : "论文识别"
    screened ||--o{ clusters : "共振聚类"
    clusters ||--o{ reports : "生成日报"
    screened ||--o{ deep_dive_queue : "深度候选"
    deep_dive_queue ||--o{ weekly_reports : "生成周报"
    candidates ||--o{ source_status : "状态记录"
    reports ||--o{ push_records : "推送记录"
```

## 4. 去重分层

1. **URL 去重**：MD5(link) 与 `reported_urls` 比对，7 天窗口
2. **Jaccard 去重**：summary 分词相似度 >= 0.85 视为重复
3. **AI 批量去重**：`DEDUP_USE_AI=true` 时启用，处理 0.3~0.85 模糊区间

## 5. 环境变量控制

| 变量 | 作用 |
|------|------|
| `DASHSCOPE_API_KEY` | 百炼 API 密钥 |
| `MODEL_NAME` | 默认 `deepseek-v4-flash` |
| `AUDIT_DB_PATH` | 本地 `data/audit.db`，FC 生产 `/mnt/audit-radar/data/audit.db` |
| `DEDUP_USE_AI` | 是否启用 AI 批量去重 |
| `RESONANCE_USE_AI` | 是否启用 LLM 共振评分 |
| `MAIL_*` | 邮件发送配置 |
