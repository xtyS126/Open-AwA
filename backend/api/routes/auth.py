"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from datetime import timedelta
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.schemas import UserCreate, UserResponse, Token
from config.security import verify_password, get_password_hash, create_access_token
from config.settings import settings
from db.models import User as UserModel, get_db


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    """
    创建新的本地用户账户。
    接口会先校验用户名是否已存在，再对密码执行哈希处理并写入数据库，成功后返回新建用户的基础资料。
    """
    db_user = db.query(UserModel).filter(UserModel.username == user.username).first()
    if db_user:
        logger.bind(
            event="auth_register_conflict",
            module="auth",
            action="register",
            status="failure",
        ).warning("username already registered")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )

    new_user = UserModel(
        id=str(uuid.uuid4()),
        username=user.username,
        password_hash=get_password_hash(user.password),
        role="user"
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.bind(
            event="auth_register_conflict_race",
            module="auth",
            action="register",
            status="failure",
        ).warning("concurrent registration conflict for username")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already registered"
        )
    db.refresh(new_user)

    logger.bind(
        event="auth_register_success",
        module="auth",
        action="register",
        status="success",
        user_id=new_user.id,
    ).info("user registered")

    return new_user


@router.post(
    "/login",
    response_model=Token,
    summary="用户登录",
    description="使用 OAuth2PasswordRequestForm 提交用户名和密码，成功后返回访问令牌。"
)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    处理login相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    user = db.query(UserModel).filter(UserModel.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        logger.bind(
            event="auth_login_failed",
            module="auth",
            action="login",
            status="failure",
            username=form_data.username,
        ).warning("login failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    logger.bind(
        event="auth_login_success",
        module="auth",
        action="login",
        status="success",
        user_id=user.id,
        username=user.username,
    ).info("login succeeded")

    return {"access_token": access_token, "token_type": "bearer"}


@router.get(
    "/me",
    response_model=UserResponse,
    summary="获取当前用户信息",
    description="返回当前访问令牌对应的用户资料。"
)
async def get_me(current_user: UserModel = Depends(get_current_user)):
    """
    获取me相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    logger.bind(
        event="auth_me",
        module="auth",
        action="me",
        status="success",
        user_id=current_user.id,
        username=current_user.username,
    ).info("fetched current user")
    return current_user
