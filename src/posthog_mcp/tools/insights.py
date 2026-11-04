"""Insight tools (PRD-21316 AC4, AC5).

`posthog_list_insights` always queries with `basic=true` so the (potentially
large) `result` chart-data payload never enters a list response -- AC4. Full
data for one insight is an opt-in, separate call (`posthog_get_insight`,
`include_result=true`), truncated per the token-economy rule if it is large
(AC5, "Decisions made by DEV01").
"""

from posthog_mcp.client import PostHogClient
from posthog_mcp.tools._shared import execute, list_query, list_result, truncate_large_field


def _shape_insight_meta(raw: dict) -> dict:
    return {
        "id": raw.get("id"),
        "short_id": raw.get("short_id"),
        "name": raw.get("name"),
        "description": raw.get("description"),
        "filters": raw.get("filters"),
        "saved": raw.get("saved"),
        "favorited": raw.get("favorited"),
        "tags": raw.get("tags"),
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
    }


def register(mcp) -> None:
    @mcp.tool(
        description="List saved insights (metadata only, no chart data) in the project.",
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    async def posthog_list_insights(
        search: str | None = None,
        saved: bool | None = None,
        favorited: bool | None = None,
        tags: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> str:
        async def _run(client: PostHogClient) -> dict:
            params, eff_limit, eff_offset = list_query(
                limit, offset, search=search, saved=saved, favorited=favorited
            )
            params["basic"] = "true"
            if tags:
                params["tags"] = tags
            data = await client.request(
                "GET", client.project_path("/insights/"), params=params
            )
            insights = [_shape_insight_meta(i) for i in data.get("results", [])]
            return list_result(insights, eff_limit, eff_offset, data.get("next"))

        return await execute(_run)

    @mcp.tool(
        description="Get one insight's metadata; pass include_result=true to also fetch its chart data.",
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    async def posthog_get_insight(id: int, include_result: bool = False) -> str:
        async def _run(client: PostHogClient) -> dict:
            params = {} if include_result else {"basic": "true"}
            data = await client.request(
                "GET", client.project_path("/insights/%s/" % id), params=params
            )
            shaped = _shape_insight_meta(data)
            if include_result:
                shaped["result"] = data.get("result")
                shaped = truncate_large_field(shaped, "result")
            return shaped

        return await execute(_run)
