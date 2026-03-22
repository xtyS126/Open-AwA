from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from db.models import get_db, Plugin
from api.dependencies import get_current_user, get_current_admin_user
from api.schemas import PluginCreate, PluginResponse, PluginUpdate, PluginExecute, PluginToolsResponse, PluginValidationResult, PluginValidationRequest, PluginDiscoveryResult
from plugins.plugin_manager import PluginManager
from plugins.plugin_validator import PluginValidator
from loguru import logger
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
        plugin_manager = PluginManager()

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
        plugin_manager = PluginManager()

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
