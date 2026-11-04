"""Cohort tools (PRD-21316 AC9)."""

from posthog_mcp.client import PostHogClient
from posthog_mcp.tools._shared import execute, list_query, list_result


def _shape_cohort(raw: dict) -> dict:
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "description": raw.get("description"),
        "count": raw.get("count"),
        "is_static": raw.get("is_static"),
        "filters": raw.get("filters"),
        "created_at": raw.get("created_at"),
    }


def register(mcp) -> None:
    @mcp.tool(
        description="List cohorts in the project, optionally filtered by name search or static/dynamic type.",
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    async def posthog_list_cohorts(
        search: str | None = None,
        type: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> str:
        async def _run(client: PostHogClient) -> dict:
            params, eff_limit, eff_offset = list_query(limit, offset, search=search)
            data = await client.request(
                "GET", client.project_path("/cohorts/"), params=params
            )
            cohorts = [_shape_cohort(c) for c in data.get("results", [])]
            if type in ("static", "dynamic"):
                want_static = type == "static"
                cohorts = [c for c in cohorts if bool(c.get("is_static")) == want_static]
            return list_result(cohorts, eff_limit, eff_offset, data.get("next"))

        return await execute(_run)
