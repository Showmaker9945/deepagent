from __future__ import annotations

import contextvars
import json
import logging
import time
from datetime import date
from typing import Any

import httpx
import trafilatura
from bs4 import BeautifulSoup
from langchain.tools import tool
from langgraph.config import get_stream_writer
from readability import Document

from app.config import Settings
from app.schemas import Category, RunCreateRequest
from app.scoring import score_tradeoff

logger = logging.getLogger(__name__)
CURRENT_TOOL_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "do_or_not_tool_context",
    default={},
)


def set_tool_context(context: dict[str, Any]) -> contextvars.Token:
    return CURRENT_TOOL_CONTEXT.set(context)


def reset_tool_context(token: contextvars.Token) -> None:
    CURRENT_TOOL_CONTEXT.reset(token)


def get_tool_context() -> dict[str, Any]:
    return CURRENT_TOOL_CONTEXT.get({})


def emit_runtime_event(event_type: str, payload: dict[str, Any]) -> None:
    try:
        writer = get_stream_writer()
    except (RuntimeError, KeyError):
        return
    try:
        writer({"event_type": event_type, "payload": payload})
    except Exception:
        return


def emit_tool_started(tool_name: str, summary: str) -> None:
    context = get_tool_context()
    logger.info(
        "Tool started",
        extra={
            "run_id": context.get("run_id"),
            "category": context.get("category"),
            "tool_name": tool_name,
            "status": "started",
        },
    )
    emit_runtime_event(
        "tool_started",
        {
            "tool_name": tool_name,
            "summary": summary,
        },
    )


def emit_tool_finished(tool_name: str, status: str, summary: str, **extra: Any) -> None:
    payload = {
        "tool_name": tool_name,
        "status": status,
        "summary": summary,
    }
    payload.update(extra)

    context = get_tool_context()
    level = logging.INFO
    if status == "error":
        level = logging.ERROR
    elif status in {"blocked", "skipped", "unavailable", "not_found"}:
        level = logging.WARNING

    logger.log(
        level,
        "Tool finished",
        extra={
            "run_id": context.get("run_id"),
            "category": context.get("category"),
            "tool_name": tool_name,
            "status": status,
            "duration_ms": extra.get("duration_ms"),
        },
    )
    emit_runtime_event("tool_finished", payload)


def emit_source(
    source_type: str,
    *,
    title: str | None = None,
    url: str | None = None,
    snippet: str | None = None,
    source_meta: dict[str, Any] | None = None,
) -> None:
    emit_runtime_event(
        "source_captured",
        {
            "source_type": source_type,
            "title": title,
            "url": url,
            "snippet": snippet,
            "source_meta": source_meta or {},
        },
    )


def elapsed_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


class ToolFactory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build(self) -> list:
        settings = self.settings
        browser_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        @tool
        def search_web(query: str) -> dict[str, Any]:
            """Search the public web for factual context."""
            tool_name = "search_web"
            started_at = time.monotonic()
            context = get_tool_context()
            emit_tool_started(tool_name, f"搜索公开资料：{query[:120]}")

            if context.get("category") == "social" and not context.get("links"):
                emit_tool_finished(
                    tool_name,
                    "skipped",
                    "社交类问题默认不做公开网页搜索。",
                    duration_ms=elapsed_ms(started_at),
                )
                return {
                    "status": "skipped",
                    "reason": "Social questions should avoid public web search unless the user supplied links.",
                    "results": [],
                }

            if not settings.tavily_api_key:
                emit_tool_finished(
                    tool_name,
                    "unavailable",
                    "没有配置 Tavily Key，跳过联网搜索。",
                    duration_ms=elapsed_ms(started_at),
                )
                return {
                    "status": "unavailable",
                    "reason": "TAVILY_API_KEY is not configured.",
                    "results": [],
                }

            try:
                response = httpx.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": settings.tavily_api_key,
                        "query": query,
                        "search_depth": "basic",
                        "max_results": 4,
                    },
                    timeout=8.0,
                )
                response.raise_for_status()
                data = response.json()
                results = [
                    {
                        "title": item.get("title"),
                        "url": item.get("url"),
                        "content": item.get("content"),
                    }
                    for item in data.get("results", [])
                ]
                for item in results:
                    emit_source(
                        "search_result",
                        title=item.get("title"),
                        url=item.get("url"),
                        snippet=(item.get("content") or "")[:240] or None,
                        source_meta={"query": query},
                    )
                emit_tool_finished(
                    tool_name,
                    "ok",
                    f"搜到 {len(results)} 条公开资料。",
                    count=len(results),
                    duration_ms=elapsed_ms(started_at),
                )
                return {
                    "status": "ok",
                    "query": query,
                    "results": results,
                }
            except httpx.HTTPError as exc:
                emit_tool_finished(
                    tool_name,
                    "error",
                    f"联网搜索失败：{exc}",
                    duration_ms=elapsed_ms(started_at),
                )
                return {
                    "status": "error",
                    "query": query,
                    "reason": f"web search unavailable: {exc}",
                    "results": [],
                }

        @tool
        def fetch_url_content(url: str) -> dict[str, Any]:
            """Fetch and extract the main readable text from a URL."""
            tool_name = "fetch_url_content"
            started_at = time.monotonic()
            emit_tool_started(tool_name, f"抓取链接正文：{url}")
            try:
                response = httpx.get(
                    url,
                    timeout=10.0,
                    follow_redirects=True,
                    headers=browser_headers,
                )
                response.raise_for_status()
                html = response.text

                extracted = trafilatura.extract(
                    html,
                    url=url,
                    include_comments=False,
                    include_tables=False,
                )
                if not extracted:
                    summary_html = Document(html).summary()
                    extracted = BeautifulSoup(summary_html, "html.parser").get_text("\n", strip=True)

                title = Document(html).short_title()
                content = (extracted or "")[:5000]
                emit_source(
                    "webpage",
                    title=title,
                    url=url,
                    snippet=content[:280] or None,
                    source_meta={"status": "ok"},
                )
                emit_tool_finished(
                    tool_name,
                    "ok",
                    "链接正文已提取。",
                    url=url,
                    duration_ms=elapsed_ms(started_at),
                )
                return {
                    "status": "ok",
                    "url": url,
                    "title": title,
                    "content": content,
                }
            except httpx.HTTPStatusError as exc:
                emit_tool_finished(
                    tool_name,
                    "blocked",
                    f"目标站点返回 HTTP {exc.response.status_code}。",
                    url=url,
                    duration_ms=elapsed_ms(started_at),
                )
                return {
                    "status": "blocked",
                    "url": url,
                    "title": None,
                    "content": "",
                    "reason": f"remote site returned HTTP {exc.response.status_code}",
                }
            except httpx.HTTPError as exc:
                emit_tool_finished(
                    tool_name,
                    "error",
                    f"链接抓取失败：{exc}",
                    url=url,
                    duration_ms=elapsed_ms(started_at),
                )
                return {
                    "status": "error",
                    "url": url,
                    "title": None,
                    "content": "",
                    "reason": f"failed to fetch url: {exc}",
                }

        @tool
        def geocode_location(name: str) -> dict[str, Any]:
            """Convert a place name into coordinates and timezone."""
            tool_name = "geocode_location"
            started_at = time.monotonic()
            emit_tool_started(tool_name, f"解析地点：{name}")
            try:
                response = httpx.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": name, "count": 3, "language": "zh", "format": "json"},
                    timeout=6.0,
                )
                response.raise_for_status()
                data = response.json()
                results = data.get("results", [])
                if not results:
                    emit_tool_finished(
                        tool_name,
                        "not_found",
                        "没有查到对应地点。",
                        query=name,
                        duration_ms=elapsed_ms(started_at),
                    )
                    return {"status": "not_found", "query": name}

                first = results[0]
                payload = {
                    "status": "ok",
                    "name": first.get("name"),
                    "country": first.get("country"),
                    "timezone": first.get("timezone"),
                    "latitude": first.get("latitude"),
                    "longitude": first.get("longitude"),
                }
                emit_source(
                    "location",
                    title=first.get("name"),
                    url=None,
                    snippet=f"{first.get('country') or ''} {first.get('timezone') or ''}".strip() or None,
                    source_meta={
                        "latitude": first.get("latitude"),
                        "longitude": first.get("longitude"),
                    },
                )
                emit_tool_finished(
                    tool_name,
                    "ok",
                    "地点解析完成。",
                    query=name,
                    duration_ms=elapsed_ms(started_at),
                )
                return payload
            except httpx.HTTPError as exc:
                emit_tool_finished(
                    tool_name,
                    "error",
                    f"地点解析失败：{exc}",
                    query=name,
                    duration_ms=elapsed_ms(started_at),
                )
                return {"status": "error", "query": name, "reason": f"geocoding unavailable: {exc}"}

        @tool
        def get_weather(latitude: float, longitude: float, start_date: str = "", end_date: str = "") -> dict[str, Any]:
            """Get a small daily weather forecast for travel decisions."""
            tool_name = "get_weather"
            started_at = time.monotonic()
            if not start_date:
                start_date = date.today().isoformat()
            if not end_date:
                end_date = start_date
            emit_tool_started(tool_name, f"查询天气：{start_date} 到 {end_date}")
            try:
                response = httpx.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": latitude,
                        "longitude": longitude,
                        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
                        "timezone": "auto",
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                    timeout=6.0,
                )
                response.raise_for_status()
                data = response.json()
                daily = data.get("daily", {})
                emit_source(
                    "weather",
                    title=f"天气预报 {start_date} - {end_date}",
                    url=None,
                    snippet=f"时区 {data.get('timezone') or 'unknown'}，已获取每日天气摘要。",
                    source_meta={
                        "latitude": latitude,
                        "longitude": longitude,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                )
                emit_tool_finished(
                    tool_name,
                    "ok",
                    "天气数据已获取。",
                    duration_ms=elapsed_ms(started_at),
                )
                return {
                    "status": "ok",
                    "latitude": latitude,
                    "longitude": longitude,
                    "daily": daily,
                    "timezone": data.get("timezone"),
                }
            except httpx.HTTPError as exc:
                emit_tool_finished(
                    tool_name,
                    "error",
                    f"天气查询失败：{exc}",
                    duration_ms=elapsed_ms(started_at),
                )
                return {
                    "status": "error",
                    "latitude": latitude,
                    "longitude": longitude,
                    "daily": {},
                    "reason": f"weather lookup unavailable: {exc}",
                }

        @tool
        def score_tradeoff_tool(
            category: Category,
            question: str,
            budget: str = "",
            deadline: str = "",
            location: str = "",
            notes: str = "",
            links_json: str = "[]",
        ) -> dict[str, Any]:
            """Score a decision across a few deterministic dimensions."""
            tool_name = "score_tradeoff_tool"
            started_at = time.monotonic()
            emit_tool_started(tool_name, f"做一轮本地权重打分：{category}")
            try:
                links = json.loads(links_json)
                if not isinstance(links, list):
                    links = []
            except json.JSONDecodeError:
                links = []

            payload = RunCreateRequest(
                question=question,
                budget=budget or None,
                deadline=deadline or None,
                location=location or None,
                notes=notes or None,
                links=[str(item) for item in links],
            )
            result = score_tradeoff(category, payload)
            emit_tool_finished(
                tool_name,
                "ok",
                "本地打分完成。",
                duration_ms=elapsed_ms(started_at),
            )
            return result

        return [search_web, fetch_url_content, geocode_location, get_weather, score_tradeoff_tool]
