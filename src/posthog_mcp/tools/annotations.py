"""Annotation tools (PRD-21316 AC9).

Read-only in v1 -- creating annotations was considered and deferred (PRD-21316
"Decisions made by DEV01" / "Scope split"), so there is no write tool here.
"""

from posthog_mcp.client import PostHogClient
from posthog_mcp.tools._shared import execute, list_query, list_result


def _shape_annotation(raw: dict) -> dict:
    return {
        "id": raw.get("id"),
        "content": raw.get("content"),
        "date_marker": raw.get("date_marker"),
        "scope": raw.get("scope"),
        "created_at": raw.get("created_at"),
        "created_by": (raw.get("created_by") or {}).get("email"),
    }


def register(mcp) -> None:
    @mcp.tool(
        description="List annotations (timestamped notes on charts) in the project.",
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    async def posthog_list_annotations(
        search: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> str:
        async def _run(client: PostHogClient) -> dict:
            params, eff_limit, eff_offset = list_query(limit, offset, search=search)
            data = await client.request(
                "GET", client.project_path("/annotations/"), params=params
            )
            annotations = [_shape_annotation(a) for a in data.get("results", [])]
            return list_result(annotations, eff_limit, eff_offset, data.get("next"))

        return await execute(_run)
