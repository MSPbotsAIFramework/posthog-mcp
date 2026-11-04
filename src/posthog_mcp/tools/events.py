"""Event tools (PRD-21316 AC6).

`limit` is capped the same as every other list tool (`_shared.MAX_LIMIT`):
the vendor's own default page for this endpoint is large, and events in
particular can carry sizeable `properties` payloads, so the general cap
keeps a single call token-cheap (tech design "Key params" note).
"""

from posthog_mcp.client import PostHogClient
from posthog_mcp.tools._shared import execute, list_query, list_result


def _shape_event(raw: dict) -> dict:
    return {
        "id": raw.get("id"),
        "event": raw.get("event"),
        "distinct_id": raw.get("distinct_id"),
        "person_id": raw.get("person", {}).get("id") if isinstance(raw.get("person"), dict) else None,
        "timestamp": raw.get("timestamp"),
        "properties": raw.get("properties"),
    }


def register(mcp) -> None:
    @mcp.tool(
        description="Search raw events by name, distinct_id, or time range, newest first.",
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    async def posthog_list_events(
        event: str | None = None,
        distinct_id: str | None = None,
        person_id: str | None = None,
        after: str | None = None,
        before: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> str:
        async def _run(client: PostHogClient) -> dict:
            params, eff_limit, eff_offset = list_query(
                limit,
                offset,
                event=event,
                distinct_id=distinct_id,
                person_id=person_id,
                after=after,
                before=before,
            )
            data = await client.request(
                "GET", client.project_path("/events/"), params=params
            )
            events = [_shape_event(e) for e in data.get("results", [])]
            return list_result(events, eff_limit, eff_offset, data.get("next"))

        return await execute(_run)
