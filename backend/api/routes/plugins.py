from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from db.models import get_db, Plugin
from api.dependencies import get_current_user, get_current_admin_user
from api.schemas import PluginCreate, PluginResponse
import uuid


router = APIRouter(prefix="/plugins", tags=["Plugins"])


@router.get("", response_model=List[PluginResponse])
async def get_plugins(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    plugins = db.query(Plugin).all()
    return plugins


@router.get("/{plugin_id}", response_model=PluginResponse)
async def get_plugin(
    plugin_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return plugin


@router.post("", response_model=PluginResponse)
async def install_plugin(
    plugin: PluginCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    new_plugin = Plugin(
        id=str(uuid.uuid4()),
        name=plugin.name,
        version=plugin.version,
        config=plugin.config,
        enabled=True
    )
    
    db.add(new_plugin)
    db.commit()
    db.refresh(new_plugin)
    
    return new_plugin


@router.delete("/{plugin_id}")
async def uninstall_plugin(
    plugin_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    
    db.delete(plugin)
    db.commit()
    
    return {"message": "Plugin uninstalled successfully"}


@router.put("/{plugin_id}/toggle")
async def toggle_plugin(
    plugin_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    
    plugin.enabled = not plugin.enabled
    db.commit()
    
    return {"message": f"Plugin {'enabled' if plugin.enabled else 'disabled'}"}
