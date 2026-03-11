# do or not 测试流程

这份文档对应当前版本的 `do or not`：

- 运行骨架已经切到官方 `Deep Agents`
- 主流程由单主 Deep Agent 驱动，不再是应用层手搓 `researcher / skeptic / decider`
- 支持流式输出、来源可见、超时收手、用户主动停止
- 本地开发环境使用 `uv`

## 1. 环境准备

### 1.1 安装 Python

项目当前使用 Python `3.12.6`：

```bash
uv python install 3.12.6
```

### 1.2 安装依赖

```bash
uv sync --extra dev
```

### 1.3 配置环境变量

```powershell
Copy-Item .env.example .env
```

至少填写：

- `DASHSCOPE_API_KEY`

建议填写：

- `TAVILY_API_KEY`

可选调整：

- `MODEL_TIMEOUT_SECONDS`
- `RUN_TIMEOUT_SECONDS`

## 2. 自动化测试

### 2.1 单元测试

```bash
uv run pytest -q
```

当前预期：

- 全部通过
- 基线结果为 `11 passed`

### 2.2 FastAPI 导入测试

```bash
uv run python -c "from app.main import app; print(app.title)"
```

预期输出：

```text
do or not
```

### 2.3 健康检查

先启动服务：

```bash
uv run uvicorn app.main:app --reload
```

然后另开一个终端执行：

```bash
uv run python -c "import httpx; print(httpx.get('http://127.0.0.1:8000/healthz').json())"
```

预期输出：

```text
{'ok': True}
```

浏览器打开：

[http://127.0.0.1:8000](http://127.0.0.1:8000)

## 4. 手工验证主流程

### 4.1 自然语言单输入框

在左侧输入框直接粘贴：

```text
这周六我想去杭州看展，来回预算 400 左右，活动页 https://example.com/event，但我最近有点累，周一还得上班，这趟到底值不值？
```

确认点：

- 不需要额外填写预算/地点/时间表单
- 链接会被自动识别
- 右侧会先出现“实时输出”，再出现最终 verdict
- 来源卡片会展示网页或搜索依据

### 4.2 极简问题补问

输入：

```text
要不要去
```

确认点：

- 系统会进入 `needs_clarification`
- 页面出现补充输入框
- 只追问高价值信息，不会连环审讯

补一句：

```text
这周六去苏州看朋友，来回高铁大概 300，我周一要上班。
```

确认点：

- 系统会继续跑，不会卡死在补充阶段
- 最终能拿到完整 verdict

### 4.3 链接补充恢复

先输入：

```text
要不要买这款显示器
```

等它追问后，补：

```text
商品链接在这：https://example.com/item，主要拿来写代码和轻剪视频。
```

确认点：

- 链接会被写回本轮输入
- 运行会恢复
- 最终结果页能看到来源卡片

## 5. 流式体验测试

### 5.1 实时输出

输入一个稍复杂的问题，例如：

```text
我现在主线工作已经挺满了，但又想立刻开一个副项目，感觉做出来很酷，也许还能放作品集，这周末要不要马上开干？
```

确认点：

- “实时输出”区域会边跑边冒字
- 时间线只显示关键阶段，不会被 token 撑爆
- 页面右侧不会无限往下延展

### 5.2 来源可见

输入带链接或需要联网事实的问题：

```text
这个活动我要不要去？活动页 https://example.com/event
```

确认点：

- 出现“依据出处”区域
- 每条来源至少能看到类型、标题/链接、摘要
- 如果是搜索结果，能看到查询痕迹或摘要

### 5.3 本地预分析可见

输入任意正常问题，例如：

```text
我已经有两把键盘了，但又看上一把新的机械键盘，这笔钱花得值不值？
```

确认点：

- “依据出处”里会先出现一条 `本地预分析`
- 这条来源会带本地权衡分，不需要先联网就能开工
- 主 Agent 后续是否联网，取决于信息是否真的不足

## 6. 停止与超时测试

### 6.1 用户主动停止

提一个需要联网或略复杂的问题，等右侧开始流式更新后，点击“停止分析”。

确认点：

- 页面会出现“收到停止请求”
- 最终状态会变成 `已停止`
- SSE 不会一直挂着不收口

### 6.2 补充阶段停止

输入会触发补问的问题，例如：

```text
要不要去
```

在它等待补充时点击“停止分析”。

确认点：

- 不需要后台继续跑
- 状态会直接变成 `已停止`

### 6.3 超时收手

如果你想强行验证超时，可以临时把 `.env` 里的 `RUN_TIMEOUT_SECONDS` 调得很小，比如：

```text
RUN_TIMEOUT_SECONDS=1
```

然后重启服务，提交一个需要联网的稍复杂问题。

确认点：

- 时间线里能看到超时事件
- 结果页依然能拿到一个保守 verdict
- 页面不会一直转圈

### 6.4 兜底 verdict

这条主要验证“主 Agent 没稳住时，系统是否还能给出保守结论”。

最简单的做法有两种：

1. 临时把 `RUN_TIMEOUT_SECONDS` 设成很小，例如 `1`
2. 或者故意给一个更复杂、联网概率更高的问题

确认点：

- 时间线里会出现 `timeout` 或错误提示
- 最终结果页依然能看到 verdict
- “依据出处”里会出现 `本地保守兜底`
- 这说明系统已经从主 Agent 切到了本地 fallback，而不是直接躺平

## 7. 分类与边界测试

### 7.1 `spending`

```text
我已经有两把键盘了，但又看上一把新的机械键盘，主要是手感和颜值让我心动，这笔钱花得值不值？
```

确认点：

- 分类为 `消费判断`
- 结论会讨论必要性、替代方案和后悔概率

### 7.2 `travel`

```text
这周六我要不要去南京看展？我从上海出发，预算 500 左右，当天来回。
```

确认点：

- 分类为 `出行活动`
- 如果工具被调用，能看到地点/天气类来源

### 7.3 `work_learning`

```text
我这周末要不要开始做一个新的 AI 小工具？我主线工作已经很满，但这个点子我很心动。
```

确认点：

- 分类为 `工作学习`
- 输出包含机会成本和最小下一步

### 7.4 `social`

```text
我这周要不要约这个朋友出来聊聊？最近联系不算多，但感觉关系有点淡了。
```

确认点：

- 分类为 `社交关系`
- 默认不做公开网页搜索
- 语气不会过度确定地揣测对方心理

### 7.5 `unsupported`

```text
我这个症状到底是不是某种病，要不要自己先吃药？
```

确认点：

- 分类为 `高风险问题`
- 不走幽默路线
- `punchline` 为空
- 建议转向专业人士

## 8. API 验证建议

### 8.1 创建 run

```bash
curl -X POST http://127.0.0.1:8000/api/runs \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"这周末要不要开始做一个小项目？\"}"
```

返回：

- `run_id`

### 8.2 读取完整结果

```bash
curl http://127.0.0.1:8000/api/runs/<RUN_ID>
```

确认返回里包含：

- `run`
- `events`
- `sources`

### 8.3 SSE 流

```bash
curl http://127.0.0.1:8000/api/runs/<RUN_ID>/stream
```

重点观察事件类型：

- `classified`
- `agent_started`
- `agent_token`
- `tool_started`
- `tool_finished`
- `source_captured`
- `verdict_ready`
- `cancelled`
- `timeout`
- `error`

### 8.4 停止 run

```bash
curl -X POST http://127.0.0.1:8000/api/runs/<RUN_ID>/cancel
```

确认点：

- 运行中时可以停止
- 已完成后再次停止会返回 `409`

### 8.5 PowerShell 版接口测试

如果你在 Windows PowerShell 里直接测接口，下面这套更省心：

创建 run：

```powershell
$body = @{
  question = "这周末要不要开始做一个新项目？"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/runs" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

读取结果：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/runs/<RUN_ID>"
```

停止运行：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/runs/<RUN_ID>/cancel" `
  -Method Post
```

## 9. 回归清单

每次你对 agent 结构、前端事件流、工具层做较大改动后，至少跑这几项：

```bash
uv run pytest -q
uv run python -c "from app.main import app; print(app.title)"
```

然后手工走这 5 条：

1. 一个带链接的 `spending`
2. 一个带地点时间的 `travel`
3. 一个容易上头的 `work_learning`
4. 一个默认不联网的 `social`
5. 一个必须克制输出的 `unsupported`

然后再额外补 3 条：

6. 一个会触发补问的问题
7. 一个会触发超时或 fallback 的问题
8. 一个手动点击“停止分析”的问题

## 10. 当前已知非阻塞项

- `requests` 依赖链会给出 `urllib3/chardet/charset_normalizer` 的版本警告
- 这条警告目前不影响项目运行和测试通过
- 如果后面要做依赖清理，可以单独升级或重锁 `uv.lock`

## 11. 真模型实跑建议

自动化测试只能保证“线通了”，不能保证“味对了”。真模型实跑时，建议你至少准备这 6 条真实问题：

1. 一个你自己真的纠结过的消费问题
2. 一个带时间地点的出行问题
3. 一个容易热血上头的副项目问题
4. 一个不该联网的社交问题
5. 一个带链接但网页可能不稳定的问题
6. 一个高风险 `unsupported` 问题

每条都看这 7 个维度：

1. 分类对不对
2. 会不会乱联网
3. 流式输出是不是自然
4. 来源是不是看得懂
5. 结论是不是明确但不过度自信
6. 下一步是不是低摩擦
7. 语气是不是中文、克制、稍微有点好笑但不油

## 12. 常见故障排查

### 12.1 页面能打开，但一提问就报错

优先检查：

- `.env` 里是否填写了 `DASHSCOPE_API_KEY`
- `DASHSCOPE_BASE_URL` 是否正确
- `MODEL_NAME` 是否还是 `qwen3-max`

### 12.2 有流式过程，但拿不到最终结果

先看：

- `/api/runs/<RUN_ID>` 里的 `run.verdict` 是否为空
- `events` 里最后一个终止事件是 `timeout`、`error` 还是 `verdict_ready`
- `sources` 里是否出现了 `本地保守兜底`

如果出现 `本地保守兜底`，说明不是彻底没结果，而是已经切 fallback 了。

### 12.3 右侧内容又开始无限变长

优先检查：

- 是否把 token 又塞回了时间线而不是“实时输出”框
- CSS 里的 `.agent-draft` 和 `.timeline` 是否还保留 `max-height` 与 `overflow: auto`

### 12.4 联网太慢

可以先试：

- 临时不配 `TAVILY_API_KEY`
- 把问题说得更完整
- 直接把你要分析的链接贴进去

这样主 Agent 更容易直接基于现有信息和预分析给结论，而不是出去到处乱逛
