# do or not

`do or not` 是一个本地优先的决策副驾驶。你只要输入一句“这事我要不要做”，系统会先做轻量分类，再交给一个主 `Deep Agent` 直接完成整轮分析。

当前版本的重点不是“多 agent 轮流演戏”，而是：

- 一个主 `Deep Agent` 负责拿结论
- 能边跑边流式输出
- 能把依据出处展示出来
- 能在用户想停的时候及时收手

目前支持的决策分类：

- `spending`
- `travel`
- `work_learning`
- `social`
- `unsupported`

## 主要特性

- 单输入框自然语言提问，不强迫用户填一堆栏位
- 官方 `Deep Agents SDK` 驱动主流程
- `Qwen3-Max` 统一作为模型
- 联网工具支持网页搜索、链接正文提取、地理编码、天气查询、本地权衡打分
- SSE 流式事件：分类、工具动作、来源记录、最终结论、取消、超时
- SQLite 持久化 `runs / run_events / run_sources / feedback`

## 技术栈

- FastAPI
- SQLite
- Jinja2 + 原生 JS
- LangChain
- LangGraph
- 官方 Deep Agents SDK（`create_deep_agent`）
- Qwen `qwen3-max`（通过 DashScope / 百炼 OpenAI 兼容接口）

## 需要准备什么

- 必需：`DASHSCOPE_API_KEY`
- 推荐：`TAVILY_API_KEY`
- 不需要申请：Open-Meteo（天气 + 地理编码）

## 用 uv 管理环境

### 1. 安装 Python

项目当前按 Python `3.12.6` 开发：

```bash
uv python install 3.12.6
```

### 2. 同步依赖

```bash
uv sync --extra dev
```

### 3. 配置环境变量

```powershell
Copy-Item .env.example .env
```

至少填写：

- `DASHSCOPE_API_KEY`

建议填写：

- `TAVILY_API_KEY`

可选：

- `MODEL_TIMEOUT_SECONDS`
- `RUN_TIMEOUT_SECONDS`

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
- `POST /api/runs/{run_id}/cancel`

`GET /api/runs/{run_id}` 当前会返回：

- `run`
- `events`
- `sources`

## 测试文档

完整测试流程见：

- [docs/TESTING.md](/C:/Users/Tang/Desktop/学习/agent_tool/docs/TESTING.md)

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

检查应用导入：

```bash
uv run python -c "from app.main import app; print(app.title)"
```

## 当前说明

- 如果 `TAVILY_API_KEY` 缺失，联网搜索会自动降级，不影响项目启动。
- 如果 `DASHSCOPE_API_KEY` 缺失，真正进入 Deep Agent 分析阶段时会给出可理解的配置错误。
- 当前环境里 `requests` 可能会提示 `urllib3/chardet/charset_normalizer` 的版本警告，这不是项目逻辑错误。
