# do or not 测试手册

这份文档是给项目开发和验收时直接照着跑的。

当前项目已经接入官方 Deep Agents SDK，核心验证目标不只是“能不能出结果”，还包括：

- 主运行时是否真的是 `create_deep_agent`
- `researcher / skeptic` 是否按 Deep Agents 子代理思路工作
- 自然语言输入是否够顺手
- SSE 时间线是否稳定
- 工具失败时是否还能给最终 verdict
- 记忆是否能被正确 seed 进本轮运行

## 1. 环境准备

### 1.1 安装 Python

项目当前使用 Python `3.12.6`。

```bash
uv python install 3.12.6
```

### 1.2 安装依赖

```bash
uv sync --extra dev
```

### 1.3 配置环境变量

```bash
Copy-Item .env.example .env
```

然后填写：

- `DASHSCOPE_API_KEY`
- `TAVILY_API_KEY`，可选

## 2. 快速自检

### 2.1 单元测试

```bash
uv run pytest -q
```

预期：

- 全部通过
- 当前基线结果为 `8 passed`

### 2.2 FastAPI 导入测试

```bash
uv run python -c "from app.main import app; print(app.title)"
```

预期输出：

```text
do or not
```

### 2.3 Deep Agents 运行时烟雾测试

这个测试用于确认项目不是停留在 `create_agent`，而是真正能实例化官方 Deep Agent graph。

```bash
@'
from app.agents import DecisionAgentRuntime
from app.config import Settings
from app.schemas import ClassificationResult

runtime = DecisionAgentRuntime(Settings(DASHSCOPE_API_KEY="test-key"))
classification = ClassificationResult(category="work_learning", reason="smoke")
agent = runtime._get_decider_agent(classification)
print(type(agent).__name__)
'@ | uv run python -
```

预期输出包含：

```text
CompiledStateGraph
```

## 3. 启动服务

```bash
uv run uvicorn app.main:app --reload
```

浏览器打开：

[http://127.0.0.1:8000](http://127.0.0.1:8000)

## 4. 前端交互测试

### 4.1 单输入框自然语言测试

在左侧输入框直接粘一整段：

```text
这周六我想去杭州看展，来回预算 400 左右，活动页 https://example.com/event ，但我最近有点累，周一还得上班，这趟到底值不值？
```

观察点：

- 不需要再额外填写预算、地点、时间字段
- 链接能被自动识别
- 最终能产出结构化 verdict

### 4.2 极简问题补问测试

输入：

```text
要不要去
```

观察点：

- 系统可以补问
- 补问最多 2 次
- 补一句之后能继续完成，而不是卡死

### 4.3 中文输出测试

输入任意正常问题，观察：

- 时间线是中文
- 研究摘要、反方意见、最终 verdict 都是中文
- `unsupported` 场景不抖机灵

## 5. Deep Agents 行为测试

### 5.1 研究代理测试

输入一个带链接或需要公开事实的问题：

```text
这个显示器我要不要买？商品页是 https://example.com/item，我主要拿来写代码和剪点轻视频。
```

观察点：

- 时间线出现 `research_started`
- `researcher` 能基于链接或工具结果整理依据
- 工具结果体现在“查到的依据”里

### 5.2 反方代理测试

输入一个容易被“热血上头”的问题：

```text
我这周要不要立刻开一个新副项目？我已经有主线工作了，但这个点子让我很兴奋。
```

观察点：

- 时间线出现 `skeptic_started`
- 输出里有隐藏成本、机会成本、范围失控等提醒
- 不是只有“支持”没有“反证”

### 5.3 克制调用子代理测试

目标不是证明它一定会调 `task`，而是确认它不会乱调。

输入一个信息已经很充分的问题：

```text
我最近已经有两把键盘了，但又看上一把新的机械键盘，主要是手感和颜值让我心动，这笔钱花得值不值？
```

观察点：

- 可以直接给出 verdict
- 不会明显陷入超长推理或不必要的额外动作

## 6. 工具与异常测试

### 6.1 403 链接容错测试

输入一个可能返回 `403` 的真实网页链接。

观察点：

- 不会整轮分析失败
- 最终仍然能给 verdict
- 把握度可能下降，但不会直接崩掉

### 6.2 无 Tavily Key 测试

临时去掉 `.env` 里的 `TAVILY_API_KEY` 后重启服务。

输入一个需要联网信息的问题。

观察点：

- 系统仍可运行
- 搜索能力降级，但不会直接 500

### 6.3 无 DashScope Key 测试

临时去掉 `.env` 里的 `DASHSCOPE_API_KEY` 后重启服务。

观察点：

- 页面仍然能打开
- 真正进入 agent 分析时，会返回可理解的配置错误

## 7. SSE 时间线测试

正常提问后，观察右侧时间线。

预期顺序通常是：

- `classified`
- `clarification_needed`，如果缺信息
- `research_started`
- `skeptic_started`
- `verdict_ready`

重点检查：

- 不会无限重复增长
- 刷新页面后，已完成事件还能回读
- 完成后不会反复重连刷旧事件

## 8. 记忆测试

先完成一轮 run，然后填写反馈：

- `actual_action`
- `satisfaction_score`
- `regret_score`
- `note`

再提交一个相似问题，观察：

- `recommended_next_step` 是否更贴近你过去的偏好
- `top_risks` 是否更早提到你的后悔模式

## 9. 回归测试建议

每次较大改动后，至少重新跑下面这些：

```bash
uv run pytest -q
uv run python -c "from app.main import app; print(app.title)"
```

然后手工测这 4 类：

1. 一个带链接的 `spending`
2. 一个带时间地点的 `travel`
3. 一个容易上头的 `work_learning`
4. 一个需要谨慎输出的 `unsupported`

## 10. 官方文档对照点

如果你想确认项目当前设计是否仍然贴近官方 Deep Agents 思路，可以对照这些官方文档：

- Deep Agents Overview
  [https://docs.langchain.com/oss/python/deepagents/overview](https://docs.langchain.com/oss/python/deepagents/overview)
- Deep Agents Customization
  [https://docs.langchain.com/oss/python/deepagents/customization](https://docs.langchain.com/oss/python/deepagents/customization)

你重点对照：

- 是否使用 `create_deep_agent`
- 是否有 subagents
- 是否使用 backend
- 是否保留结构化输出
