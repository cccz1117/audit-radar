# Audit Radar 上云部署清单

## 阿里云 FC 前置条件

- [ ] 已开通函数计算 FC 3.0
- [ ] 已创建服务 `audit-radar`
- [ ] 已创建 NAS 文件系统并挂载到 FC 函数的 `/mnt/audit-radar`（用于 SQLite 持久化）
- [ ] 已配置 VPC 访问公网（或 NAT 网关），确保能访问 NewsNow / NVD / RSS 源

---

## 一、NAS 配置（SQLite 持久化）

**为什么需要 NAS**：FC 函数实例是无状态的，实例回收后本地数据丢失。SQLite 数据库必须存放在持久化存储上，才能保留跨天去重记录、历史日报和 repo 历史。

### 1.1 创建 NAS 文件系统

**控制台路径**：阿里云控制台 → 文件存储 NAS → 文件系统列表 → 创建文件系统

| 配置项 | 建议值 |
|--------|--------|
| 区域 | 与 FC 函数同一区域（如 `cn-hangzhou`） |
| 协议类型 | NFS（兼容 FC 挂载） |
| 存储类型 | **通用型 NAS**（性价比高，有免费额度）或 **极速型 NAS**（按量付费，延迟更低） |
| 可用区 | 与 FC 函数同一可用区 |

> **免费额度提示**：阿里云通用型 NAS 通常提供 **500GB 容量免费额度**（3 个月或按活动期）。创建时选择按量付费，实际用量极小（每天几十条记录，数据库文件 < 50MB）。

### 1.2 创建挂载点

在 NAS 文件系统详情页 → 挂载点 → 添加挂载点：
- 专有网络：选择 FC 函数所在的 VPC（如果 FC 还没配 VPC，先创建或选一个已有 VPC）
- 交换机：选择同一可用区的交换机
- 权限组：默认权限组即可（允许 FC 读写）

### 1.3 在 FC 函数中挂载 NAS

**控制台路径**：FC 函数详情 → 函数配置 → 存储配置 → NAS 文件系统

| 配置项 | 建议值 |
|--------|--------|
| 开启 NAS 文件系统 | 是 |
| NAS 文件系统 | 选择刚才创建的 NAS |
| 用户组 ID | 0（root） |
| 用户 ID | 0（root） |
| 挂载路径 | `/mnt/audit-radar` |

> **重要**：`mount_path` 必须是 `/mnt/audit-radar`，因为代码默认数据库路径是 `/mnt/audit-radar/data/audit.db`。如果改了挂载路径，记得同步改环境变量 `AUDIT_DB_PATH`。

### 1.4 验证 NAS 挂载

首次部署后，在 FC 函数里触发一次运行，然后检查日志中是否有数据库路径输出：

```
[OK] 数据库初始化: /mnt/audit-radar/data/audit.db
```

如果没有报错，说明 NAS 挂载成功。你也可以通过 NAS 控制台 → 文件系统 → 数据管理 → 浏览文件，查看 `/data/audit.db` 是否生成。

---

## 二、FC 环境变量配置

**控制台路径**：FC 函数详情 → 函数配置 → 环境变量

| 环境变量 | 建议值 | 说明 |
|----------|--------|------|
| `AUDIT_DB_PATH` | `/mnt/audit-radar/data/audit.db` | 数据库路径，默认就是 NAS 路径 |
| `LLM_PROVIDER` | `deepseek` | 默认使用 DeepSeek 官方 API |
| `MODEL_NAME` | `ds-v4-flash` | 默认模型 |
| `DEEPSEEK_API_KEY` | `sk-...` | DeepSeek 官方 API Key |
| `MOONSHOT_API_KEY` | `sk-...` | Moonshot API Key（可选） |
| `MAIL_HOST` | `smtpdm.aliyun.com` | 阿里云 DirectMail SMTP |
| `MAIL_PORT` | `25` | SMTP 端口 |
| `MAIL_USER` | `audit@mail.news-briefing.xyz` | 发件地址 |
| `MAIL_PASS` | `...` | SMTP 密码 |
| `MAIL_TO_LIST` | `your@email.com` | 收件人，逗号分隔 |
| `MAIL_FROM` | `audit@mail.news-briefing.xyz` | 发件人显示名 |
| `REQUEST_TIMEOUT` | `30` | HTTP 请求超时 |
| `RSS_MAX_ITEMS` | `20` | 每个 RSS 源最多抓取条数 |

---

## 三、GitHub Secrets 配置（用于 Actions 部署）

在仓库 Settings > Secrets and variables > Actions 中配置：

| Secret | 说明 |
|--------|------|
| `ALICLOUD_ACCESS_KEY_ID` | 阿里云 AccessKey ID |
| `ALICLOUD_ACCESS_KEY_SECRET` | 阿里云 AccessKey Secret |
| `ALICLOUD_REGION` | 地域，默认 `cn-hangzhou` |
| `DASHSCOPE_API_KEY` | 百炼 API Key（可选，用于 STT 等） |
| `DEEPSEEK_API_KEY` | DeepSeek 官方 API Key |
| `MOONSHOT_API_KEY` | Moonshot API Key（可选） |
| `MAIL_HOST` | SMTP 服务器 |
| `MAIL_PORT` | SMTP 端口，默认 25 |
| `MAIL_USER` | SMTP 用户名 |
| `MAIL_PASS` | SMTP 密码 |
| `MAIL_TO_LIST` | 收件人列表，逗号分隔 |
| `MAIL_FROM` | 可选，默认与 MAIL_USER 一致 |

---

## 四、FC 函数配置

### daily-job

- Runtime: `python3.11`
- Handler: `index.handler`
- Memory: 512 MB
- Timeout: 300 秒
- 触发器：定时触发，Cron 表达式 `0 8 * * *`

> **时区说明**：阿里云 FC 定时触发器的 Cron 默认使用 **UTC 时间**。`0 8 * * *` UTC = 北京时间 **16:00**。如果你想让日报在**北京时间 8:00** 推送，Cron 表达式应写 `0 0 * * *`（UTC 0:00）。请确认时区配置后再保存。

### weekly-job

- Runtime: `python3.11`
- Handler: `weekly.handler`
- Memory: 512 MB
- Timeout: 300 秒
- 触发器：定时触发，Cron 表达式 `0 9 * * 6`（UTC 周六 9:00 = 北京时间 17:00）

---

## 五、首次部署后检查

1. 触发一次日报函数，检查日志是否有 `[OK] Audit Radar 完成`
2. 检查邮件是否收到日报
3. 检查 NAS 路径下是否生成 `/mnt/audit-radar/data/audit.db`
4. 运行 1~2 天后检查 `source_status` 表，确认各信源抓取正常
5. 周六检查周报是否正确生成

---

## 六、已知限制

- 播客音频转录当前为占位实现，周报仅使用标题和摘要生成
- arXiv RSS 在周末/节假日可能返回 0 条
- 部分海外源（如 HuggingFace Papers raw feed）因大陆网络环境已禁用
- The Information RSS 可能受 Cloudflare 保护，如果抓取失败会记录 `failed` 状态，不影响其他信源
