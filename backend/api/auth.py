from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from backend.auth.jwt import create_access_token, hash_password, verify_password, decode_token

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

_owners: dict[str, dict] = {}


class RegisterRequest(BaseModel):
    email: str
    password: str
    business_id: str


@router.post("/auth/register")
async def register(req: RegisterRequest):
    if req.email in _owners:
        raise HTTPException(status_code=400, detail="Email already registered")
    _owners[req.email] = {"hashed": hash_password(req.password), "business_id": req.business_id}
    token = create_access_token({"sub": req.email, "business_id": req.business_id})
    return {"access_token": token, "token_type": "bearer"}


@router.post("/auth/token")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    owner = _owners.get(form.username)
    if not owner or not verify_password(form.password, owner["hashed"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": form.username, "business_id": owner.get("business_id", "")})
    return {"access_token": token, "token_type": "bearer"}


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        return decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
