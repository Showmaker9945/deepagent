# do or not

`do or not` 是一个本地优先的决策副驾驶。你只要输入一句“这事我要不要做”，它会先分类，再让：

- `researcher` 去找事实和上下文
- `skeptic` 负责唱反调、找隐藏成本和后悔点
- `main decider` 最后给出结构化 verdict

目前支持的决策分类：

- `spending`
- `travel`
- `work_learning`
- `social`
- `unsupported`

项目技术栈：

- FastAPI
- SQLite
- LangChain
- LangGraph runtime
- 官方 Deep Agents SDK（`create_deep_agent`）
- Qwen `qwen3-max`（通过 DashScope / 百炼 OpenAI 兼容接口）

## 需要准备什么

- 必需：`DASHSCOPE_API_KEY`
- 推荐：`TAVILY_API_KEY`
- 不需要申请：Open-Meteo（天气 + 地理编码）

## 用 uv 管理环境

推荐直接使用 `uv`，不用再手动 `venv + pip install`。

### 1. 固定 Python 版本

项目当前按 Python `3.12.6` 开发。

如果你本机还没装对应版本：

```bash
uv python install 3.12.6
```

### 2. 创建并同步环境

第一次进入项目目录后执行：

```bash
uv sync --extra dev
```

这一步会：

- 创建 `.venv`
- 安装运行依赖
- 安装开发依赖（目前主要是 `pytest`）

如果你只想装运行依赖，也可以：

```bash
uv sync
```

### 3. 配置环境变量

复制一份环境变量模板：

```bash
Copy-Item .env.example .env
```

然后填写：

- `DASHSCOPE_API_KEY`
- `TAVILY_API_KEY`（可选）

如果你暂时没填 `TAVILY_API_KEY`，项目依然能跑，只是网页搜索工具会自动降级。

### 4. 启动项目

```bash
uv run uvicorn app.main:app --reload
```

打开：

[http://127.0.0.1:8000](http://127.0.0.1:8000)

## API 概览

- `POST /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/stream`
- `POST /api/runs/{run_id}/clarifications`
- `POST /api/runs/{run_id}/feedback`

## 测试文档

更完整的测试流程见：

- [docs/TESTING.md](/C:/Users/Tang/Desktop/学习/agent_tool/docs/TESTING.md)

## 详细测试流程

下面这套流程建议你第一次拉起项目时完整跑一遍。

### A. 基础环境测试

确认 `uv` 可用：

```bash
uv --version
```

确认依赖已经同步：

```bash
uv sync --extra dev
```

### B. 单元测试

运行项目当前测试：

```bash
uv run pytest -q
```

当前测试覆盖：

- `score_tradeoff` 的基础打分逻辑
- `POST /api/runs` 到 `GET /api/runs/{id}` 的基本流程
- 反馈接口
- 需要补充信息时的澄清分支
- 自然语言问题里的链接自动提取
- 自由输入场景下不依赖额外表单字段也能完成分析

如果这里没过，先别急着怀疑人生，通常是某个依赖环境或本地改动出了偏差。

### C. 应用导入测试

确认 FastAPI 应用能正常导入：

```bash
uv run python -c "from app.main import app; print(app.title)"
```

预期输出：

```text
do or not
```

### D. 健康检查测试

启动服务：

```bash
uv run uvicorn app.main:app --reload
```

另开一个终端，请求健康检查：

```bash
uv run python -c "import httpx; print(httpx.get('http://127.0.0.1:8000/healthz').json())"
```

预期返回：

```json
{"ok": true}
```

### E. 无 Key 情况下的行为测试

如果你还没填 `DASHSCOPE_API_KEY`，页面依然可以打开。

这时可以测试：

1. 提交一个普通问题
2. 查看是否先进入分类 / 澄清流程
3. 当流程需要真正调用模型时，是否能得到可理解的错误提示，而不是直接 500 爆炸

目前项目会在真正进入 agent 运行时提示缺少 `DASHSCOPE_API_KEY`。

### F. 有 Key 之后的端到端测试

填好 `.env` 后，建议至少手工测这 5 类：

1. `spending`
示例：`这个 899 的键盘我要不要买？`
观察点：
- 是否分类为 `spending`
- 是否会用预算和链接信息
- 是否给出替代方案

2. `travel`
示例：`这周六我要不要去上海看演出？`
观察点：
- 是否分类为 `travel`
- 如果填了地点和时间，是否会走地理编码 / 天气工具
- 是否会给出延期或替代方案

3. `work_learning`
示例：`我这周要不要开始做一个 LangGraph 小项目？`
观察点：
- 是否给出开始做 / 暂缓做的理由
- 是否会说明机会成本
- 是否给出最小下一步动作

4. `social`
示例：`要不要和前同事见面吃饭？`
观察点：
- 是否分类为 `social`
- 默认不要主动公网搜索八卦
- 是否强调边界感、情绪成本、关系价值

5. `unsupported`
示例：`我这个症状要不要自己买药处理？`
观察点：
- 是否分类为 `unsupported`
- 是否收起幽默语气
- 是否明确提醒找专业人士

### G. SSE 时间线测试

在浏览器里提问时，重点看右侧时间线是否按顺序出现：

- `classified`
- `clarification_needed`（如果缺信息）
- `research_started`
- `skeptic_started`
- `verdict_ready`

如果中途刷新页面，建议再检查一次：

- 已完成事件是否还能重新读取
- 最终 verdict 是否还在

### H. 反馈记忆测试

完成一次 run 后，在页面底部填写反馈：

- `actual_action`
- `satisfaction_score`
- `regret_score`
- `note`

然后再提一个相似问题，观察：

- 是否更早提到你过去的后悔模式
- 是否在 `recommended_next_step` 或 `top_risks` 里体现偏好变化

## 常用 uv 命令

同步依赖：

```bash
uv sync --extra dev
```

运行测试：

```bash
uv run pytest -q
```

启动服务：

```bash
uv run uvicorn app.main:app --reload
```

运行任意 Python 命令：

```bash
uv run python -c "from app.main import app; print(app.title)"
```

## 当前已验证

我已经本地跑过：

- `uv sync --extra dev`
- `uv run pytest -q`
- FastAPI 导入测试
- `/healthz` 健康检查测试

## 补充说明

- 如果 `TAVILY_API_KEY` 缺失，网页搜索会自动降级，不会阻止项目启动。
- 如果 `DASHSCOPE_API_KEY` 缺失，真正进入 agent 决策阶段时会报配置错误，这是预期行为。
- 当前环境里 `requests` 会提示一个已有的依赖警告：`urllib3/chardet/charset_normalizer` 版本组合不理想。这个不是项目本身逻辑错误，但如果你想把环境收拾得更干净，可以后面单独整理。
