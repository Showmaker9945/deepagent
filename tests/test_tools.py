import httpx

from app.config import Settings
from app.tools import ToolFactory


def test_fetch_url_content_returns_blocked_payload_on_403(monkeypatch):
    url = "https://example.com/item"
    request = httpx.Request("GET", url)
    response = httpx.Response(403, request=request)

    def fake_get(*args, **kwargs):
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    monkeypatch.setattr(httpx, "get", fake_get)

    fetch_tool = next(tool for tool in ToolFactory(Settings()).build() if tool.name == "fetch_url_content")
    result = fetch_tool.invoke({"url": url})

    assert result["status"] == "blocked"
    assert result["url"] == url
    assert "403" in result["reason"]
