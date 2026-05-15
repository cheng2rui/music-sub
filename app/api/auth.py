"""Auth API routes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.auth import hash_password, verify_password, create_token
import app.config as cfg_module
import yaml

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_username: str = ""
    new_password: str = ""


@router.post("/login")
def login(req: LoginRequest):
    """Login and get JWT token."""
    cfg = cfg_module.config.auth
    if req.username != cfg.username:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(req.password, cfg.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_token(req.username)
    return {"ok": True, "token": token, "username": req.username}


@router.put("/password")
def change_password(req: PasswordChangeRequest):
    """Change username and/or password."""
    from app.config import CONFIG_PATH, load_config
    cfg = cfg_module.config.auth

    # Verify old password
    if not verify_password(req.old_password, cfg.password_hash):
        raise HTTPException(status_code=401, detail="当前密码错误")

    # Update
    new_username = req.new_username.strip() or cfg.username
    new_password_hash = cfg.password_hash
    if req.new_password.strip():
        new_password_hash = hash_password(req.new_password.strip())

    # Read current config, update auth section, write back
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    raw.setdefault("auth", {})
    raw["auth"]["username"] = new_username
    raw["auth"]["password_hash"] = new_password_hash

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True)

    # Reload config
    new_config = load_config(CONFIG_PATH)
    cfg_module.config = new_config

    return {"ok": True, "message": "账号信息已更新", "username": new_username}
