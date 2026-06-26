import asyncio
import httpx


async def retry_with_backoff(url: str, payload: dict, max_retries: int = 3) -> dict:
    last_error = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json={
                    "business_id": payload["business_id"],
                    "task_id": payload["task_id"],
                    "parameters": payload.get("parameters", {}),
                })
                resp.raise_for_status()
                result = resp.json()

                from backend.memory.supabase_client import get_supabase
                get_supabase().table("tasks").update({
                    "status": "completed",
                    "result": result,
                    "retries": attempt,
                }).eq("id", payload["task_id"]).execute()

                return result

        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)

    raise RuntimeError(f"Failed after {max_retries} retries: {last_error}")
