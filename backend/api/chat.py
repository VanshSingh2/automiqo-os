import json
import asyncio
from uuid import UUID
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from shared.schemas import ChatRequest
from backend.security.rate_limit import rate_limit
from backend.security.spend_guard import within_budget

router = APIRouter()


@router.post("/chat", dependencies=[Depends(rate_limit("chat", per_minute=20))])
async def chat(req: ChatRequest):
    async def event_stream():
        # Daily spend circuit breaker (review finding B2).
        allowed, spent, cap = await within_budget(str(req.business_id))
        if not allowed:
            note = (f"Daily AI budget reached (${spent:.2f} of ${cap:.2f}). "
                    "Pausing on-demand runs to control cost — raise DAILY_AI_SPEND_CAP_USD "
                    "or try again tomorrow.")
            yield f"data: {json.dumps({'chunk': note, 'done': True})}\n\n"
            return
        try:
            from agents.executive.ceo.agent import CEOAgent
            agent = CEOAgent(business_id=req.business_id)
            response = await agent.run(req.message)
            words = response.summary.split()
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                await asyncio.sleep(0.02)
            yield f"data: {json.dumps({'chunk': '', 'done': True, 'metrics': response.metrics, 'recommendations': response.recommendations})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
