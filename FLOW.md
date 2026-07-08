# 当前 Audit Radar 处理流程

```mermaid
flowchart TD
    subgraph Phase1["📡 1. 采集层"]
        A1[采集所有启用的信源] --> A2{记录信源状态}
        A2 --> A3[论文入库]
        A3 --> A4[保存原始候选到 SQLite]
    end

    subgraph Phase2["🔬 2. 去重层"]
        B1[URL 去重<br/>查 reported_urls 表<br/>7 天内已报道则过滤] --> B2[标记 GitHub repo 新增性]
        B2 --> B3[论文摘要富化]
    end

    subgraph Phase3["🎯 3. 筛选层"]
        C1[LLM 粗筛<br/>P0 必留 + 五维评分] --> C2{日报保留 / 深度池候选}
        C2 --> C3[内容相似度去重<br/>Jaccard < 0.2 保留<br/>> 0.8 过滤<br/>0.2~0.8 AI 判断]
    end

    subgraph Phase4["⚡ 4. 聚类层"]
        D1[关键词聚类<br/>Jaccard 匹配标题] --> D2[本地规则计算共振分]
        D2 --> D3[按共振分排序]
    end

    subgraph Phase5["🏆 5. 精排层"]
        E1[LLM 精排<br/>Top 3 排序] --> E2[生成 HTML 日报]
    end

    subgraph Phase6["📬 6. 发送层"]
        F1[记录已报道 URL<br/>关键词匹配 -> 原始 link] --> F2[发送邮件]
        F2 --> F3[记录推送状态]
    end

    Phase1 --> Phase2
    Phase2 --> Phase3
    Phase3 --> Phase4
    Phase4 --> Phase5
    Phase5 --> Phase6

    style Phase1 fill:#e1f5fe
    style Phase2 fill:#fff3e0
    style Phase3 fill:#e8f5e9
    style Phase4 fill:#fce4ec
    style Phase5 fill:#f3e5f5
    style Phase6 fill:#e8eaf6
```

## 关键数据流向

```mermaid
flowchart LR
    subgraph Sources["信源"]
        RSS[RSS x 18]
        API[API x 4<br/>NVD/HF/HN]
        NewsNow[NewsNow x 5]
    end

    subgraph Storage["SQLite (NAS)"]
        Candidates[candidates 表]
        Screened[screened 表]
        Clusters[clusters 表]
        Reports[reports 表]
        ReportedUrls[reported_urls 表<br/>跨天去重用]
        RepoHistory[repo_history 表<br/>GitHub 新增判断]
        DeepDive[deep_dive_queue 表<br/>周报/月报素材]
    end

    Sources -->|Fetcher| Candidates
    Candidates -->|Selector| Screened
    Screened -->|Resonance| Clusters
    Clusters -->|Ranker| Reports
    Reports -->|Sender| Email[邮件推送]
    Reports -->|save_reported_urls| ReportedUrls
    ReportedUrls -->|dedup_pipeline| Phase2
```

## 去重 vs 记录已报道 URL

| 阶段 | 操作 | 目的 | 存储 |
|------|------|------|------|
| **采集后** | `dedup_pipeline` 查 `reported_urls` | 过滤明天会重复的内容 | 读取 |
| **精排后** | `_find_cluster_by_title` 提取原始 link | 记录今天推送了什么 | 写入 `reported_urls` |

> 两者不是同一个东西：去重是**读取**历史数据做过滤；记录已报道是**写入**今天的结果，为明天去重提供历史数据。
