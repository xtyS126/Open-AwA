from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from db.models import get_db, Plugin
from api.dependencies import get_current_user
from api.schemas import PluginCreate, PluginResponse, PluginUpdate, PluginExecute, PluginPermissionStatus, PluginPermissionUpdateRequest, PluginPermissionUpdateResponse, PluginToolsResponse, PluginValidationResult, PluginValidationRequest, PluginDiscoveryResult, PluginLogsResponse, PluginLogLevelUpdate, PluginLogLevelResponse, PluginLogEntry, HotUpdateRequest, HotUpdateResponse, RollbackRequest, RollbackResponse
from plugins.plugin_manager import PluginManager
from plugins.plugin_validator import PluginValidator
from plugins.plugin_logger import LogManager
from loguru import logger
import uuid
import zipfile
import io


router = APIRouter(prefix="/plugins", tags=["Plugins"])
plugin_manager = PluginManager()


def _ensure_plugin_discovered(plugin_name: str) -> None:
    if plugin_name in plugin_manager.plugin_metadata:
        return
    plugin_manager.discover_plugins()


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


@router.put("/{plugin_id}", response_model=PluginResponse)
async def update_plugin(
    plugin_id: str,
    plugin_update: PluginUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    if plugin_update.name is not None:
        plugin.name = plugin_update.name
    if plugin_update.version is not None:
        plugin.version = plugin_update.version
    if plugin_update.config is not None:
        plugin.config = plugin_update.config
    if plugin_update.enabled is not None:
        plugin.enabled = plugin_update.enabled

    db.commit()
    db.refresh(plugin)

    logger.info(f"Plugin '{plugin_id}' updated by user '{current_user.username}'")

    return plugin


@router.post("/{plugin_id}/permissions/authorize", response_model=PluginPermissionUpdateResponse)
async def authorize_plugin_permissions(
    plugin_id: str,
    payload: PluginPermissionUpdateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    _ensure_plugin_discovered(plugin.name)
    try:
        status = plugin_manager.authorize_plugin_permissions(plugin.name, payload.permissions)
        return PluginPermissionUpdateResponse(
            plugin_id=plugin_id,
            plugin_name=status["plugin_name"],
            requested_permissions=status["requested_permissions"],
            granted_permissions=status["granted_permissions"],
            missing_permissions=status["missing_permissions"],
            message="权限授权成功",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{plugin_id}/permissions/revoke", response_model=PluginPermissionUpdateResponse)
async def revoke_plugin_permissions(
    plugin_id: str,
    payload: PluginPermissionUpdateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    _ensure_plugin_discovered(plugin.name)
    try:
        status = plugin_manager.revoke_plugin_permissions(plugin.name, payload.permissions)
        return PluginPermissionUpdateResponse(
            plugin_id=plugin_id,
            plugin_name=status["plugin_name"],
            requested_permissions=status["requested_permissions"],
            granted_permissions=status["granted_permissions"],
            missing_permissions=status["missing_permissions"],
            message="权限撤销成功",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{plugin_id}/permissions", response_model=PluginPermissionStatus)
async def get_plugin_permissions(
    plugin_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    _ensure_plugin_discovered(plugin.name)
    try:
        status = plugin_manager.get_plugin_permission_status(plugin.name)
        return PluginPermissionStatus(
            plugin_id=plugin_id,
            plugin_name=status["plugin_name"],
            requested_permissions=status["requested_permissions"],
            granted_permissions=status["granted_permissions"],
            missing_permissions=status["missing_permissions"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{plugin_id}/execute")
async def execute_plugin(
    plugin_id: str,
    execution_data: PluginExecute,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    if not plugin.enabled:
        raise HTTPException(status_code=400, detail="Plugin is disabled")

    try:
        _ensure_plugin_discovered(plugin.name)

        if plugin.name not in plugin_manager.loaded_plugins:
            load_success = plugin_manager.load_plugin(plugin.name)
            if not load_success:
                raise HTTPException(status_code=500, detail="Failed to load plugin")

        result = await plugin_manager.execute_plugin_async(
            plugin_name=plugin.name,
            method=execution_data.method,
            **execution_data.params
        )

        logger.info(f"Plugin '{plugin.name}' method '{execution_data.method}' executed by user '{current_user.username}'")

        return {
            "status": result.get("status", "error"),
            "plugin_id": plugin_id,
            "plugin_name": plugin.name,
            "method": execution_data.method,
            "result": result
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing plugin '{plugin.name}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Plugin execution failed: {str(e)}")


@router.get("/{plugin_id}/tools", response_model=PluginToolsResponse)
async def get_plugin_tools(
    plugin_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    try:
        _ensure_plugin_discovered(plugin.name)

        if plugin.name not in plugin_manager.loaded_plugins:
            load_success = plugin_manager.load_plugin(plugin.name)
            if not load_success:
                raise HTTPException(status_code=500, detail="Failed to load plugin")

        tools = plugin_manager.get_plugin_tools(plugin.name)

        return PluginToolsResponse(
            plugin_id=plugin_id,
            plugin_name=plugin.name,
            tools=tools
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tools for plugin '{plugin.name}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get plugin tools: {str(e)}")


@router.post("/validate", response_model=PluginValidationResult)
async def validate_plugin(
    validation_request: PluginValidationRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    try:
        config_data = validation_request.yaml_content.strip()

        if config_data.startswith('{'):
            import json
            try:
                config = json.loads(config_data)
            except json.JSONDecodeError:
                return PluginValidationResult(
                    valid=False,
                    errors=["Invalid JSON format"],
                    warnings=[]
                )
        else:
            try:
                import yaml
                config = yaml.safe_load(config_data)
            except yaml.YAMLError as e:
                logger.error(f"YAML parsing error in plugin validation: {str(e)}")
                return PluginValidationResult(
                    valid=False,
                    errors=["Invalid YAML format"],
                    warnings=[]
                )
            except Exception as e:
                logger.error(f"Unexpected error parsing plugin config: {str(e)}")
                return PluginValidationResult(
                    valid=False,
                    errors=[f"Configuration parsing error: {str(e)}"],
                    warnings=[]
                )

        if not isinstance(config, dict):
            return PluginValidationResult(
                valid=False,
                errors=["Configuration must be a dictionary"],
                warnings=[]
            )

        validator = PluginValidator()
        required_fields = ["name", "version"]
        missing_fields = [f for f in required_fields if f not in config]

        if missing_fields:
            return PluginValidationResult(
                valid=False,
                errors=[f"Missing required fields: {', '.join(missing_fields)}"],
                warnings=[]
            )

        return PluginValidationResult(
            valid=True,
            errors=[],
            warnings=["Plugin validation requires plugin code to be fully validated"]
        )

    except Exception as e:
        logger.error(f"Error validating plugin configuration: {str(e)}")
        return PluginValidationResult(
            valid=False,
            errors=[f"Validation error: {str(e)}"],
            warnings=[]
        )


@router.get("/discover", response_model=PluginDiscoveryResult)
async def discover_plugins(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    try:
        plugin_manager = PluginManager()
        discovered = plugin_manager.discover_plugins()

        logger.info(f"Plugin discovery completed by user '{current_user.username}', found {len(discovered)} plugins")

        return PluginDiscoveryResult(
            discovered=discovered,
            total_count=len(discovered)
        )

    except Exception as e:
        logger.error(f"Error discovering plugins: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Plugin discovery failed: {str(e)}")

@router.post("/upload")
async def upload_plugin(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Only .zip files are supported")
        
    content = await file.read()
    
    try:
        plugin_manager = PluginManager()
        plugins_dir = plugin_manager.plugins_dir
        
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for member in z.namelist():
                if member.startswith('/') or '..' in member:
                    raise HTTPException(status_code=400, detail="Invalid zip file structure")
            
            z.extractall(plugins_dir)
            
        # After extracting, discover and install to DB
        discovered = plugin_manager.discover_plugins()
        installed_count = 0
        
        for plugin_info in discovered:
            name = plugin_info.get('name')
            version = plugin_info.get('version', '1.0.0')
            description = plugin_info.get('description', '')
            
            existing_plugin = db.query(Plugin).filter(Plugin.name == name).first()
            if not existing_plugin:
                new_plugin = Plugin(
                    id=str(uuid.uuid4()),
                    name=name,
                    version=version,
                    config=f'{{"description": "{description}"}}',
                    enabled=True
                )
                db.add(new_plugin)
                installed_count += 1
                
        db.commit()
            
        return {"message": f"Plugin uploaded and extracted successfully. Installed {installed_count} new plugins."}
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip file")
    except Exception as e:
        logger.error(f"Error extracting plugin: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to extract plugin: {str(e)}")


@router.post("/{plugin_id}/hot-update", response_model=HotUpdateResponse)
async def hot_update_plugin(
    plugin_id: str,
    payload: HotUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    _ensure_plugin_discovered(plugin.name)

    rollout_dict = payload.rollout_config.model_dump() if payload.rollout_config else None

    try:
        result = plugin_manager.hot_update_plugin(
            plugin_name=plugin.name,
            rollout_policy=rollout_dict,
            strategy=payload.strategy,
        )
        hot_status = plugin_manager.hot_update_manager.get_status(plugin.name)
        return HotUpdateResponse(
            success=result.get("success", False),
            plugin_name=plugin.name,
            strategy=payload.strategy,
            new_version=hot_status.get("standby", {}).get("version") if hot_status.get("standby") else hot_status.get("active", {}).get("version"),
            standby_ready=hot_status.get("standby") is not None,
            rollout_config=hot_status.get("rollout_config"),
            active_release_id=result.get("active_release_id"),
            standby_release_id=result.get("standby_release_id"),
            rolled_back=result.get("rolled_back", False),
            error=result.get("error"),
            hot_update_status=hot_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"Hot update failed for plugin '{plugin.name}': {exc}")
        raise HTTPException(status_code=500, detail=f"Hot update failed: {str(exc)}")


@router.post("/{plugin_id}/rollback", response_model=RollbackResponse)
async def rollback_plugin(
    plugin_id: str,
    payload: RollbackRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    _ensure_plugin_discovered(plugin.name)

    try:
        result = plugin_manager.rollback_plugin(
            plugin_name=plugin.name,
            snapshot_id=payload.snapshot_id,
        )
        return RollbackResponse(
            success=True,
            plugin_name=plugin.name,
            rolled_back_to=result.get("rolled_back_to"),
            snapshot_id=result.get("snapshot_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"Rollback failed for plugin '{plugin.name}': {exc}")
        raise HTTPException(status_code=500, detail=f"Rollback failed: {str(exc)}")


_log_manager = LogManager()


@router.get("/{plugin_id}/logs", response_model=PluginLogsResponse)
async def get_plugin_logs(
    plugin_id: str,
    level: Optional[str] = Query(None, description="按级别过滤: DEBUG/INFO/WARNING/ERROR/CRITICAL"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    plugin_logger = _log_manager.get_logger(plugin_id)
    entries = plugin_logger.get_entries(level=level, limit=limit, offset=offset)

    return PluginLogsResponse(
        plugin_id=plugin_id,
        plugin_name=plugin.name,
        level_filter=level,
        total=len(entries),
        entries=[PluginLogEntry(**e) for e in entries],
    )


@router.put("/{plugin_id}/log-level", response_model=PluginLogLevelResponse)
async def update_plugin_log_level(
    plugin_id: str,
    payload: PluginLogLevelUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    level_upper = payload.level.upper()
    if level_upper not in valid_levels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid log level '{payload.level}'. Must be one of: {', '.join(sorted(valid_levels))}",
        )

    plugin_logger = _log_manager.get_logger(plugin_id)
    plugin_logger.level = level_upper

    logger.info(f"Plugin '{plugin.name}' log level set to {level_upper} by user '{current_user.username}'")

    return PluginLogLevelResponse(
        plugin_id=plugin_id,
        plugin_name=plugin.name,
        level=level_upper,
    )
