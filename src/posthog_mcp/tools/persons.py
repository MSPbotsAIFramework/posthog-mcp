"""Person tools (PRD-21316 AC7, AC8)."""

from posthog_mcp.client import PostHogClient
from posthog_mcp.tools._shared import execute, list_query, list_result


def _shape_person(raw: dict) -> dict:
    return {
        "id": raw.get("id"),
        "distinct_ids": raw.get("distinct_ids"),
        "properties": raw.get("properties"),
        "created_at": raw.get("created_at"),
        "is_identified": raw.get("is_identified"),
    }


def register(mcp) -> None:
    @mcp.tool(
        description="Search persons by email, name, or distinct id fragment.",
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    async def posthog_list_persons(
        search: str | None = None,
        email: str | None = None,
        distinct_id: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> str:
        async def _run(client: PostHogClient) -> dict:
            params, eff_limit, eff_offset = list_query(
                limit, offset, search=search, email=email, distinct_id=distinct_id
            )
            data = await client.request(
                "GET", client.project_path("/persons/"), params=params
            )
            persons = [_shape_person(p) for p in data.get("results", [])]
            return list_result(persons, eff_limit, eff_offset, data.get("next"))

        return await execute(_run)

    @mcp.tool(
        description="Get a single person's profile by id.",
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    async def posthog_get_person(id: str) -> str:
        async def _run(client: PostHogClient) -> dict:
            data = await client.request(
                "GET", client.project_path("/persons/%s/" % id)
            )
            return _shape_person(data)

        return await execute(_run)
