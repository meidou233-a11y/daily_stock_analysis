# Actions 排程可靠性与静默失效处理

本页说明 GitHub Actions 每日任务「明明配置没问题，却不再执行」的排查与恢复流程，以及如何让这种故障在数小时内被发现，而不是数天后。

## 1. 为什么这类故障特别危险

排程被停用**不会产生任何 run**，因此：

- Actions 页面没有红色失败，没有邮件，没有通知；
- 工作流文件还在，cron 表达式看起来完全正常；
- 每日报告停止推送，但没有任何一处会告诉你。

**「没有 run」本身就是故障信号**，但默认没有任何机制会去检查它。

## 2. 先确认是不是排程没跑

```bash
REPO=owner/repo

# 各 workflow 的注册状态
gh api "repos/$REPO/actions/workflows" --jq '.workflows[] | [.state, .path] | @tsv'

# 最近一次 run 是什么时候（含任何状态）
gh run list -R "$REPO" --limit 5

# 指定日期区间内到底有没有 run
gh api "repos/$REPO/actions/runs?created=2026-10-15..2026-10-17" --jq '.total_count'
```

对照排程应执行的日期：如果 cron 是 `* * 1-5`，那么周四、周五应该有 run；`total_count` 为 `0` 就说明排程没有触发。

## 3. 三类停用原因与区分方式

`state` 字段的取值直接对应原因：

| `state` | 含义 | 处理方式 |
| --- | --- | --- |
| `active` | 已启用 | 若仍然不执行，见下方「repo 层停用」 |
| `disabled_inactivity` | public repo 闲置 60 天，GitHub 自动停用排程 | `gh workflow enable <file>`，或由 `actions-keepalive.yml` 自动恢复 |
| `disabled_manually` | 有人手动停用 | `gh workflow enable <file>` |
| `disabled_fork` | 因为 repo 是 fork 而被停用 | 见下方「fork 与 repo 层停用」 |
| `deleted` | workflow 文件已删除 | 恢复文件 |

### repo 层停用：`state` 可能仍显示 `active`

当 GitHub 把**整个 repo** 的 Actions 停用时，`workflow_dispatch` 会返回：

```
HTTP 422: Actions has been disabled for this repository.
```

此时注意：`repos/{owner}/{repo}/actions/permissions` 可能**仍然**返回 `{"enabled": true}`，`state` 也可能是 `active`。**不要只看这两个字段就判定正常** —— 实际能否触发，以 `gh workflow run` 的结果为准。

```bash
# 最可靠的探针：尝试触发一个无副作用的 workflow
gh workflow run "network-smoke.yml" -R "$REPO"
```

### fork 与 repo 层停用

GitHub 官方文档（[Disabling and enabling a workflow](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)）：

> To prevent unnecessary workflow runs, scheduled workflows may be disabled automatically. **When a public repository is forked, scheduled workflows are disabled by default.** In a public repository, scheduled workflows are automatically disabled when no repository activity has occurred in 60 days.

也就是说 **public fork 的排程本来就不可靠**，这是策略行为，会反复发生。恢复只能通过网页：

1. 打开 `https://github.com/<owner>/<repo>/actions`
2. 点击横幅 **「I understand the risks, enable workflows」**
3. 若没有横幅，检查 **Settings → Actions → General** 是否选了 "Disable actions"

> 实测：在 repo 层被停用时，`gh workflow enable` 与 `PUT /repos/{repo}/actions/permissions -F enabled=true` 都可能静默无效果，必须网页手动启用。

## 4. 检测：用死信开关让「没跑」变成告警

本仓库的每日任务会在结束时向外部监控上报心跳（`scripts/send_heartbeat.py`）。外部监控在**预期时间没收到心跳**时告警 —— 这就是把「静默」翻译成「告警」的关键。

### 配置

1. 在任意支持 cron/grace 的监控服务建立检查项（例如 healthchecks.io、Uptime Kuma、Cronitor），周期设为**每个工作日一次**，宽限期建议 ≥ 2 小时。
2. 复制该检查项的 ping URL。
3. 在仓库 **Settings → Secrets and variables → Actions** 新增 secret `HEARTBEAT_URL`（ping URL 内含密钥，因此 Secrets 优先于 Variables）。

未配置 `HEARTBEAT_URL` 时该步骤是空操作，每日任务行为完全不变。

### 上报内容

| 字段 | 说明 |
| --- | --- |
| `status` | `success` 或 `failure`（job 的真实结果） |
| `run` | 对应的 Actions run 链接 |
| `date` | 报告日期 |

因此监控不仅能发现「完全没跑」，也能发现「跑了但失败」。

### 边界

- 心跳只在 `analyze` job 实际执行后上报。若当天第二个 cron 被回执去重跳过，则不会重复上报 —— 这是预期行为，因为主跑已经上报过。
- 心跳上报失败只会输出 `::warning::`，**不会**让每日分析失败。

## 5. 恢复：定期 keepalive

`.github/workflows/actions-keepalive.yml` 每周检查一次，把 `state != active` 的 workflow 重新启用。

- 需要 Repository secret `KEEPALIVE_TOKEN`：具备 `workflow` scope 的 PAT。
- 未配置时该 workflow 仅提示并正常退出。
- 它能处理 `disabled_inactivity` / `disabled_manually`。
- **它无法处理 repo 层停用** —— 那种情况下 repo 内任何 workflow 都不会被调度，keepalive 自己也跑不起来。这正是需要第 4 节外部监控的原因。

## 6. 长期建议

public fork 的排程会被反复停用，因此不建议把关键定时任务长期放在 fork 里：

- 优先把定时任务放在**非 fork** 的仓库；
- 若必须留在 fork，务必配置第 4 节的心跳监控，并定期（每 1～2 个月）人工巡检 Actions 页面；
- 业务侧建议做成「处理自上次成功以来的全部数据」而不是「假定只在整点跑一次」，这样即使漏跑一天也能补上。
