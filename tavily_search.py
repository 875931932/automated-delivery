from __future__ import annotations

import requests


class TavilyRoleResearcher:
    """Fetch role-market context for candidate profile interviews."""

    endpoint = "https://api.tavily.com/search"

    def __init__(
        self,
        enabled: bool,
        api_key: str,
        timeout: int = 12,
        max_results: int = 5,
    ):
        self.enabled = bool(enabled)
        self.api_key = str(api_key or "").strip()
        self.timeout = max(1, int(timeout))
        self.max_results = min(5, max(1, int(max_results)))

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.api_key)

    def search(self, direction: str, role_families: list[str]) -> list[dict[str, str]]:
        if not self.ready:
            return []
        direction = str(direction or "").strip()
        if not direction:
            return []

        roles = [str(role).strip() for role in role_families if str(role).strip()]
        role_text = "、".join(roles[:5])
        query = f"{direction} 岗位 常见工作职责 技能要求 能力要求"
        if role_text:
            query = f"{role_text} {query}"
        response = requests.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "topic": "general",
                "search_depth": "basic",
                "max_results": self.max_results,
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        results = []
        for item in payload.get("results", [])[:self.max_results]:
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            results.append({
                "title": title[:200],
                "url": url[:1000],
                "content": content[:1200],
            })
        return results
