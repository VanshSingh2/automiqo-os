from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from backend.auth.jwt import create_access_token, hash_password, verify_password, decode_token

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


class RegisterRequest(BaseModel):
    email: str
    password: str
    business_id: str


@router.post("/auth/register")
async def register(req: RegisterRequest):
    from backend.memory.supabase_client import get_supabase
    sb = get_supabase()
    existing = sb.table("owners").select("id").eq("email", req.email).limit(1).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Email already registered")
    sb.table("owners").insert({
        "email": req.email,
        "hashed_password": hash_password(req.password),
        "business_id": req.business_id,
    }).execute()
    token = create_access_token({"sub": req.email, "business_id": req.business_id})
    return {"access_token": token, "token_type": "bearer"}


@router.post("/auth/token")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    from backend.memory.supabase_client import get_supabase
    sb = get_supabase()
    result = sb.table("owners").select("*").eq("email", form.username).limit(1).execute()
    if not result.data:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    owner = result.data[0]
    if not verify_password(form.password, owner["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": owner["email"], "business_id": owner["business_id"]})
    return {"access_token": token, "token_type": "bearer"}


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    if not token:
        return {}
    try:
        return decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
