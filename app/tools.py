from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
import trafilatura
from bs4 import BeautifulSoup
from langchain.tools import tool
from readability import Document

from app.config import Settings
from app.schemas import Category, RunCreateRequest
from app.scoring import score_tradeoff


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
            if not settings.tavily_api_key:
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
                        "max_results": 3,
                    },
                    timeout=12.0,
                )
                response.raise_for_status()
                data = response.json()
                return {
                    "status": "ok",
                    "query": query,
                    "results": [
                        {
                            "title": item.get("title"),
                            "url": item.get("url"),
                            "content": item.get("content"),
                        }
                        for item in data.get("results", [])
                    ],
                }
            except httpx.HTTPError as exc:
                return {
                    "status": "error",
                    "query": query,
                    "reason": f"web search unavailable: {exc}",
                    "results": [],
                }

        @tool
        def fetch_url_content(url: str) -> dict[str, Any]:
            """Fetch and extract the main readable text from a URL."""
            try:
                response = httpx.get(
                    url,
                    timeout=12.0,
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

                return {
                    "status": "ok",
                    "url": url,
                    "title": Document(html).short_title(),
                    "content": (extracted or "")[:5000],
                }
            except httpx.HTTPStatusError as exc:
                return {
                    "status": "blocked",
                    "url": url,
                    "title": None,
                    "content": "",
                    "reason": f"remote site returned HTTP {exc.response.status_code}",
                }
            except httpx.HTTPError as exc:
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
            try:
                response = httpx.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": name, "count": 3, "language": "zh", "format": "json"},
                    timeout=8.0,
                )
                response.raise_for_status()
                data = response.json()
                results = data.get("results", [])
                if not results:
                    return {"status": "not_found", "query": name}
                first = results[0]
                return {
                    "status": "ok",
                    "name": first.get("name"),
                    "country": first.get("country"),
                    "timezone": first.get("timezone"),
                    "latitude": first.get("latitude"),
                    "longitude": first.get("longitude"),
                }
            except httpx.HTTPError as exc:
                return {"status": "error", "query": name, "reason": f"geocoding unavailable: {exc}"}

        @tool
        def get_weather(latitude: float, longitude: float, start_date: str = "", end_date: str = "") -> dict[str, Any]:
            """Get a small daily weather forecast for travel decisions."""
            if not start_date:
                start_date = date.today().isoformat()
            if not end_date:
                end_date = start_date
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
                    timeout=8.0,
                )
                response.raise_for_status()
                data = response.json()
                return {
                    "status": "ok",
                    "latitude": latitude,
                    "longitude": longitude,
                    "daily": data.get("daily", {}),
                    "timezone": data.get("timezone"),
                }
            except httpx.HTTPError as exc:
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
            return score_tradeoff(category, payload)

        return [search_web, fetch_url_content, geocode_location, get_weather, score_tradeoff_tool]
