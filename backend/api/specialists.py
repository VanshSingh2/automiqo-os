"""Specialist API — test any specialist directly."""
from fastapi import APIRouter
from pydantic import BaseModel
from agents.shared.specialist_caller import SpecialistCaller, SPECIALIST_REGISTRY

router = APIRouter()


class ConsultRequest(BaseModel):
    specialist: str
    task: str
    context: dict = {}


@router.get("/specialists")
async def list_specialists():
    caller = SpecialistCaller()
    available = []
    for key, info in SPECIALIST_REGISTRY.items():
        from pathlib import Path
        available.append({
            "key": key,
            "use_when": info["use_when"],
            "loaded": (Path("specialist_library") / info["file"]).exists(),
        })
    loaded = sum(1 for s in available if s["loaded"])
    return {"specialists": available, "total": len(available), "loaded": loaded}


@router.post("/specialists/consult")
async def consult_specialist(req: ConsultRequest):
    caller = SpecialistCaller()
    result = await caller.consult(req.specialist, req.task, req.context)
    return {"specialist": req.specialist, "advice": result}
