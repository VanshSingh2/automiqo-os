import json
import asyncio
from uuid import UUID
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from shared.schemas import ChatRequest

router = APIRouter()


@router.post("/chat")
async def chat(req: ChatRequest):
    async def event_stream():
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
