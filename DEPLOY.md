# Audit Radar 上云部署清单

## 阿里云 FC 前置条件

- [ ] 已开通函数计算 FC 3.0
- [ ] 已创建服务 `audit-radar`
- [ ] 已创建 NAS 挂载点并挂载到 `/mnt/audit-radar`（用于 SQLite 持久化）
- [ ] 已配置 VPC 访问公网（或 NAT 网关），确保能访问 NewsNow / NVD / RSS 源

## GitHub Secrets 配置

在仓库 Settings > Secrets and variables > Actions 中配置：

| Secret | 说明 |
|--------|------|
| `ALICLOUD_ACCESS_KEY_ID` | 阿里云 AccessKey ID |
| `ALICLOUD_ACCESS_KEY_SECRET` | 阿里云 AccessKey Secret |
| `ALICLOUD_REGION` | 地域，默认 `cn-hangzhou` |
| `DASHSCOPE_API_KEY` | 百炼 API Key |
| `MODEL_NAME` | 可选，默认 `deepseek-v4-flash` |
| `MAIL_HOST` | SMTP 服务器 |
| `MAIL_PORT` | SMTP 端口，默认 587 |
| `MAIL_USER` | SMTP 用户名 |
| `MAIL_PASS` | SMTP 密码 |
| `MAIL_TO_LIST` | 收件人列表，逗号分隔 |
| `MAIL_FROM` | 可选，默认与 MAIL_USER 一致 |
| `AUDIT_DB_PATH` | 可选，默认 `/mnt/audit-radar/data/audit.db` |

## FC 函数配置

### daily-job

- Runtime: `python3.11`
- Handler: `index.handler`
- Memory: 512 MB
- Timeout: 300 秒
- 触发器：定时触发，Cron 表达式 `0 8 * * *`（每天 8:00）

### weekly-job

- Runtime: `python3.11`
- Handler: `weekly.handler`
- Memory: 512 MB
- Timeout: 300 秒
- 触发器：定时触发，Cron 表达式 `0 9 * * 6`（每周六 9:00）

## 首次部署后检查

1. 触发一次日报函数，检查日志是否有 `[OK] Audit Radar 完成`
2. 检查邮件是否收到日报
3. 检查 NAS 路径下是否生成 `/mnt/audit-radar/data/audit.db`
4. 运行 1~2 天后检查 `source_status` 表，确认各信源抓取正常
5. 周六检查周报是否正确生成

## 已知限制

- 播客音频转录当前为占位实现，周报仅使用标题和摘要生成
- arXiv RSS 在周末/节假日可能返回 0 条
- 部分海外源（如 HuggingFace Papers raw feed）因大陆网络环境已禁用
