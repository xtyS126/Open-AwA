"""
工作流管理路由，提供定义保存、更新、执行与状态查询接口。
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.schemas import (
    WorkflowCreate,
    WorkflowExecutionRequest,
    WorkflowExecutionResponse,
    WorkflowResponse,
    WorkflowUpdate,
)
from db.models import Workflow, WorkflowExecution, get_db
from workflow.engine import WorkflowEngine


router = APIRouter(prefix="/workflows", tags=["Workflow"])


def get_workflow_engine(db: Session = Depends(get_db)) -> WorkflowEngine:
    return WorkflowEngine(db_session=db)


@router.get("", response_model=List[WorkflowResponse])
async def list_workflows(
    engine: WorkflowEngine = Depends(get_workflow_engine),
    current_user=Depends(get_current_user),
):
    return (
        engine.db_session.query(Workflow)
        .filter(Workflow.user_id == str(current_user.id))
        .order_by(Workflow.updated_at.desc())
        .all()
    )


@router.post("", response_model=WorkflowResponse)
async def create_workflow(
    request: WorkflowCreate,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    current_user=Depends(get_current_user),
):
    parsed = engine.parser.parse_definition(request.definition, format_hint=request.format)
    workflow = Workflow(
        user_id=str(current_user.id),
        name=request.name,
        description=request.description or parsed.get("description", ""),
        format=request.format,
        definition=parsed,
        enabled=request.enabled,
    )
    engine.db_session.add(workflow)
    engine.db_session.commit()
    engine.db_session.refresh(workflow)
    engine.sync_workflow_steps(workflow.id, parsed.get("steps", []))
    return workflow


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: int,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    current_user=Depends(get_current_user),
):
    workflow = (
        engine.db_session.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.user_id == str(current_user.id))
        .first()
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: int,
    request: WorkflowUpdate,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    current_user=Depends(get_current_user),
):
    workflow = (
        engine.db_session.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.user_id == str(current_user.id))
        .first()
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if request.definition is not None:
        parsed = engine.parser.parse_definition(request.definition, format_hint=request.format or workflow.format)
        workflow.definition = parsed
        workflow.format = request.format or workflow.format
        engine.sync_workflow_steps(workflow.id, parsed.get("steps", []))

    if request.name is not None:
        workflow.name = request.name
    if request.description is not None:
        workflow.description = request.description
    if request.enabled is not None:
        workflow.enabled = request.enabled

    engine.db_session.commit()
    engine.db_session.refresh(workflow)
    return workflow


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: int,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    current_user=Depends(get_current_user),
):
    workflow = (
        engine.db_session.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.user_id == str(current_user.id))
        .first()
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    engine.db_session.delete(workflow)
    engine.db_session.commit()
    return {"message": "Workflow deleted successfully"}


@router.post("/execute", response_model=WorkflowExecutionResponse)
async def execute_workflow(
    request: WorkflowExecutionRequest,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    current_user=Depends(get_current_user),
):
    workflow = None
    definition = request.definition
    workflow_name = request.workflow_name

    if request.workflow_id is not None:
        workflow = (
            engine.db_session.query(Workflow)
            .filter(Workflow.id == request.workflow_id, Workflow.user_id == str(current_user.id))
            .first()
        )
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        definition = workflow.definition
        workflow_name = workflow.name

    if definition is None:
        raise HTTPException(status_code=400, detail="Workflow definition is required")

    result = await engine.execute_definition(
        definition,
        workflow_id=workflow.id if workflow else request.workflow_id,
        workflow_name=workflow_name,
        user_id=str(current_user.id),
        input_context=request.input_context,
        format_hint=request.format,
    )
    execution_id = result.get("execution_id")
    if execution_id is None:
        raise HTTPException(status_code=500, detail="Workflow execution did not create a record")

    execution = engine.db_session.query(WorkflowExecution).filter(WorkflowExecution.id == execution_id).first()
    if execution is None:
        raise HTTPException(status_code=404, detail="Workflow execution not found")
    return execution


@router.get("/executions/{execution_id}", response_model=WorkflowExecutionResponse)
async def get_workflow_execution(
    execution_id: int,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    current_user=Depends(get_current_user),
):
    execution = (
        engine.db_session.query(WorkflowExecution)
        .filter(WorkflowExecution.id == execution_id, WorkflowExecution.user_id == str(current_user.id))
        .first()
    )
    if execution is None:
        raise HTTPException(status_code=404, detail="Workflow execution not found")
    return execution