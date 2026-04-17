"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Body
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional
from pathlib import Path as PathLib
from db.models import get_db, Plugin
from api.dependencies import get_current_user, get_current_admin_user
from api.schemas import PluginCreate, PluginImportUrlRequest, PluginResponse, PluginUpdate, PluginExecute, PluginPermissionStatus, PluginPermissionUpdateRequest, PluginPermissionUpdateResponse, PluginToolsResponse, PluginValidationResult, PluginValidationRequest, PluginDiscoveryResult, PluginLogsResponse, PluginLogLevelUpdate, PluginLogLevelResponse, PluginLogEntry, HotUpdateRequest, HotUpdateResponse, RollbackRequest, RollbackResponse
from plugins.plugin_manager import PluginManager
from plugins.plugin_logger import LogManager
from loguru import logger
import uuid
import zipfile
import io
import os
import shutil
import tempfile
import json


router = APIRouter(prefix="/plugins", tags=["Plugins"])
plugin_manager = PluginManager()


def _read_json_file(path: str) -> Optional[Dict[str, Any]]:
    """
    读取 JSON 文件并返回字典结构，异常时返回 None。
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            return payload
        return None
    except Exception:
        return None


def _write_json_file(path: str, payload: Dict[str, Any]) -> None:
    """
    将字典按 JSON 形式写入文件，确保目录存在。
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _resolve_plugin_root_dir(plugin_name: str) -> Optional[str]:
    """
    根据插件名解析插件根目录，优先使用扫描元数据，其次回退到目录与 manifest 查找。
    所有路径均验证不溢出插件根目录，防止路径遍历攻击。
    """
    plugins_base = PathLib(plugin_manager.plugins_dir).resolve()

    _ensure_plugin_discovered(plugin_name)
    metadata = plugin_manager.plugin_metadata.get(plugin_name, {})
    metadata_path = metadata.get("path")
    if isinstance(metadata_path, str) and metadata_path:
        # 约定插件入口通常为 <plugin_root>/src/index.py
        root_candidate = PathLib(metadata_path).resolve().parent.parent
        if root_candidate.is_dir() and root_candidate.is_relative_to(plugins_base):
            return str(root_candidate)

    direct_candidate = plugins_base / plugin_name
    if direct_candidate.resolve().is_relative_to(plugins_base) and direct_candidate.is_dir():
        return str(direct_candidate)

    if not plugins_base.is_dir():
        return None

    for child in os.listdir(str(plugins_base)):
        child_dir = plugins_base / child
        if not child_dir.is_dir():
            continue
        manifest_path = child_dir / "manifest.json"
        manifest = _read_json_file(str(manifest_path))
        if manifest and str(manifest.get("name", "")).strip() == plugin_name:
            return str(child_dir)
    return None


def _default_schema_for_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    当插件未提供 schema.json 时，根据当前配置生成最小可用的动态表单 schema。
    """
    properties: Dict[str, Any] = {}
    for key, value in config.items():
        if isinstance(value, bool):
            properties[key] = {
                "type": "boolean",
                "title": key,
                "default": value,
                "x-component": "switch",
            }
        elif isinstance(value, int) and not isinstance(value, bool):
            properties[key] = {"type": "integer", "title": key, "default": value}
        elif isinstance(value, float):
            properties[key] = {"type": "number", "title": key, "default": value}
        else:
            properties[key] = {"type": "string", "title": key, "default": "" if value is None else str(value)}
    return {
        "type": "object",
        "title": "插件配置",
        "properties": properties,
        "required": [],
    }


def _extract_default_config(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 JSON Schema 中提取默认配置，仅处理对象根与一层属性默认值。
    """
    defaults: Dict[str, Any] = {}
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return defaults
    for key, prop in properties.items():
        if isinstance(prop, dict) and "default" in prop:
            defaults[key] = prop.get("default")
    return defaults


def _merge_with_schema_defaults(schema: Dict[str, Any], raw_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    将入参配置与 schema 默认值合并，保证缺省字段可用。
    """
    merged = _extract_default_config(schema)
    merged.update(raw_config)
    return merged


def _persist_plugin_config(
    db: Session,
    plugin: Plugin,
    next_config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    统一处理插件配置落库、写入 config.json 与运行时刷新。
    """
    plugin_root = _resolve_plugin_root_dir(plugin.name)
    if not plugin_root:
        raise HTTPException(status_code=404, detail=f"未找到插件目录: {plugin.name}")

    schema_path = os.path.join(plugin_root, "schema.json")
    schema_payload = _read_json_file(schema_path) or _default_schema_for_config(next_config)
    normalized_config = _merge_with_schema_defaults(schema_payload, next_config)

    plugin.config = normalized_config
    db.commit()
    db.refresh(plugin)

    config_json_path = os.path.join(plugin_root, "config.json")
    _write_json_file(config_json_path, normalized_config)

    if plugin.name in plugin_manager.loaded_plugins:
        try:
            # 通过重载让配置在当前会话实时生效
            plugin_manager.reload_plugin(plugin.name)
        except Exception as exc:
            logger.warning(f"Plugin '{plugin.name}' reloaded with warning after config update: {exc}")

    return {
        "plugin_id": plugin.id,
        "plugin_name": plugin.name,
        "config": normalized_config,
        "config_file_path": config_json_path,
    }


def _ensure_plugin_discovered(plugin_name: str) -> None:
    """
    处理ensure、plugin、discovered相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    if plugin_name in plugin_manager.plugin_metadata:
        return
    plugin_manager.discover_plugins()


@router.get(
    "",
    response_model=List[PluginResponse],
    summary="获取插件列表",
    description="返回数据库中已登记的插件记录列表。"
)
async def get_plugins(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取plugins相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    plugins = db.query(Plugin).all()
    return plugins


@router.get(
    "/{plugin_id}",
    response_model=PluginResponse,
    summary="获取插件详情",
    description="根据插件 ID 返回对应插件的详细信息。"
)
async def get_plugin(
    plugin_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取plugin相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return plugin


@router.post("", response_model=PluginResponse)
async def install_plugin(
    plugin: PluginCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin_user)
):
    """
    处理install、plugin相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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
    current_user = Depends(get_current_admin_user)
):
    """
    处理uninstall、plugin相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    
    db.delete(plugin)
    db.commit()
    
    return {"message": "Plugin uninstalled successfully"}


@router.put(
    "/{plugin_id}/toggle",
    summary="切换插件启用状态",
    description="将指定插件在启用和禁用状态之间切换。"
)
async def toggle_plugin(
    plugin_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin_user)
):
    """
    处理toggle、plugin相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    
    plugin.enabled = not plugin.enabled
    db.commit()

    return {"message": f"Plugin {'enabled' if plugin.enabled else 'disabled'}"}


@router.put(
    "/{plugin_id}",
    response_model=PluginResponse,
    summary="更新插件",
    description="更新插件名称、版本、配置或启用状态。"
)
async def update_plugin(
    plugin_id: str,
    plugin_update: PluginUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin_user)
):
    """
    更新plugin相关数据、配置或状态。
    阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
    """
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


@router.get(
    "/{plugin_id}/config/schema",
    summary="获取插件配置 schema",
    description="读取插件目录中的 schema.json、config.json 与数据库配置，返回动态表单所需数据。",
)
async def get_plugin_config_schema(
    plugin_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    plugin_root = _resolve_plugin_root_dir(plugin.name)
    if not plugin_root:
        raise HTTPException(status_code=404, detail=f"未找到插件目录: {plugin.name}")

    schema_path = os.path.join(plugin_root, "schema.json")
    config_path = os.path.join(plugin_root, "config.json")
    schema_payload = _read_json_file(schema_path)

    db_config = plugin.config if isinstance(plugin.config, dict) else {}
    file_config = _read_json_file(config_path) or {}
    if not schema_payload:
        schema_payload = _default_schema_for_config({**db_config, **file_config})

    default_config = _extract_default_config(schema_payload)
    current_config = default_config.copy()
    current_config.update(db_config)
    current_config.update(file_config)

    return {
        "plugin_id": plugin.id,
        "plugin_name": plugin.name,
        "schema": schema_payload,
        "default_config": default_config,
        "current_config": current_config,
        "config_file_exists": os.path.exists(config_path),
    }


@router.put(
    "/{plugin_id}/config",
    summary="保存插件配置",
    description="保存插件配置到数据库并持久化到插件目录 config.json。",
)
async def save_plugin_config(
    plugin_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin_user),
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="配置体必须是 JSON 对象")
    return _persist_plugin_config(db=db, plugin=plugin, next_config=payload)


@router.post(
    "/{plugin_id}/config/reset",
    summary="重置插件配置为默认值",
    description="按 schema 默认值重置配置并写入 config.json。",
)
async def reset_plugin_config(
    plugin_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin_user),
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    plugin_root = _resolve_plugin_root_dir(plugin.name)
    if not plugin_root:
        raise HTTPException(status_code=404, detail=f"未找到插件目录: {plugin.name}")
    schema_payload = _read_json_file(os.path.join(plugin_root, "schema.json")) or _default_schema_for_config({})
    next_config = _extract_default_config(schema_payload)
    return _persist_plugin_config(db=db, plugin=plugin, next_config=next_config)


@router.get(
    "/{plugin_id}/config/export",
    summary="导出插件配置",
    description="返回当前生效配置，供前端导出为 JSON 文件。",
)
async def export_plugin_config(
    plugin_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    plugin_root = _resolve_plugin_root_dir(plugin.name)
    if not plugin_root:
        raise HTTPException(status_code=404, detail=f"未找到插件目录: {plugin.name}")
    config_path = os.path.join(plugin_root, "config.json")
    file_config = _read_json_file(config_path) or {}
    db_config = plugin.config if isinstance(plugin.config, dict) else {}
    merged = db_config.copy()
    merged.update(file_config)
    return {
        "plugin_id": plugin.id,
        "plugin_name": plugin.name,
        "config": merged,
    }


@router.post("/{plugin_id}/permissions/authorize", response_model=PluginPermissionUpdateResponse)
async def authorize_plugin_permissions(
    plugin_id: str,
    payload: PluginPermissionUpdateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin_user)
):
    """
    为plugin、permissions相关操作授予所需权限。
    授权结果不仅影响当前操作，也会改变后续可用能力的边界。
    """
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


@router.post(
    "/{plugin_id}/permissions/revoke",
    response_model=PluginPermissionUpdateResponse,
    summary="撤销插件权限",
    description="撤销指定插件的部分或全部已授予权限。"
)
async def revoke_plugin_permissions(
    plugin_id: str,
    payload: PluginPermissionUpdateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin_user)
):
    """
    撤销plugin、permissions相关操作已授予的权限或访问能力。
    此类逻辑主要用于收缩权限面，以确保运行时行为符合安全约束。
    """
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
    """
    获取plugin、permissions相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
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


@router.post(
    "/{plugin_id}/execute",
    summary="执行插件方法",
    description="调用指定插件的方法并返回执行结果。"
)
async def execute_plugin(
    plugin_id: str,
    execution_data: PluginExecute,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    处理execute、plugin相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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
    """
    获取plugin、tools相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
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
    """
    校验plugin相关输入、规则或结构是否合法。
    返回结果通常用于阻止非法输入继续流入后续链路。
    """
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


@router.get(
    "/discover",
    response_model=PluginDiscoveryResult,
    summary="发现插件",
    description="扫描插件目录并返回可发现的插件元数据。"
)
async def discover_plugins(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    处理discover、plugins相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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

@router.post(
    "/upload",
    summary="上传插件包",
    description="上传 zip 格式插件包并尝试安装到系统中。"
)
async def upload_plugin(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin_user)
):
    """
    处理upload、plugin相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Only .zip files are supported")
        
    content = await file.read()
    
    # 使用临时目录解压，校验通过后再原子移动到插件目录
    temp_dir = None
    moved_dirs = []
    try:
        plugin_manager = PluginManager()
        plugins_dir = plugin_manager.plugins_dir
        
        # 先解压到临时目录进行校验
        temp_dir = tempfile.mkdtemp(prefix="plugin_upload_")
        
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for member in z.namelist():
                if member.startswith('/') or '..' in member:
                    raise HTTPException(status_code=400, detail="Invalid zip file structure")
            
            z.extractall(temp_dir)
        
        # 在临时目录中发现插件
        discovered = plugin_manager._discover_plugins_in_directory(temp_dir)
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
        
        # 数据库提交成功后，再将文件从临时目录移动到插件目录
        db.commit()
        
        # 原子移动：将临时目录下的内容移动到插件目录
        for item in os.listdir(temp_dir):
            src_path = os.path.join(temp_dir, item)
            dst_path = os.path.join(plugins_dir, item)
            if os.path.isdir(src_path):
                if os.path.exists(dst_path):
                    shutil.rmtree(dst_path)
                shutil.move(src_path, dst_path)
                moved_dirs.append(dst_path)
            else:
                shutil.move(src_path, dst_path)
            
        return {"message": f"Plugin uploaded and extracted successfully. Installed {installed_count} new plugins."}
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip file")
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        # 回滚数据库事务
        db.rollback()
        # 清理已移动的目录
        for moved_dir in moved_dirs:
            shutil.rmtree(moved_dir, ignore_errors=True)
        logger.error(f"Error extracting plugin: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to extract plugin: {str(e)}")
    finally:
        # 清理临时目录
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


@router.post(
    "/import-url",
    summary="通过远程 URL 导入插件",
    description="从白名单域名下载 ZIP 插件包并导入系统。"
)
async def import_plugin_from_url(
    payload: PluginImportUrlRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin_user)
):
    """
    处理远程 URL 插件导入，成功后写入数据库并返回导入结果。
    """
    source_url = (payload.source_url or "").strip()
    if not source_url:
        raise HTTPException(status_code=400, detail="source_url is required")

    try:
        plugin_manager_instance = PluginManager()
        discovered = plugin_manager_instance.register_plugin_from_url(
            source_url=source_url,
            timeout=max(1, int(payload.timeout_seconds or 30)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"Error importing plugin from URL '{source_url}': {str(exc)}")
        raise HTTPException(status_code=500, detail=f"Failed to import plugin from URL: {str(exc)}")

    if not discovered:
        raise HTTPException(status_code=400, detail="No valid plugin found in remote package")

    installed_count = 0
    updated_count = 0
    imported_plugins = []

    try:
        for plugin_info in discovered:
            name = plugin_info.get("name")
            if not name:
                continue

            manifest = plugin_info.get("manifest") if isinstance(plugin_info.get("manifest"), dict) else {}
            version = str(plugin_info.get("version", "1.0.0"))
            description = str(plugin_info.get("description", ""))
            author = str(manifest.get("author", "unknown"))

            dependencies: List[str] = []
            raw_dependencies = manifest.get("dependencies")
            if isinstance(raw_dependencies, dict):
                dependencies = list(raw_dependencies.keys())
            elif isinstance(raw_dependencies, list):
                dependencies = [str(item) for item in raw_dependencies if isinstance(item, (str, int, float))]

            config_payload: Dict[str, Any] = {
                "description": description,
                "source_url": source_url,
                "manifest": manifest,
            }

            existing_plugin = db.query(Plugin).filter(Plugin.name == name).first()
            if existing_plugin:
                existing_plugin.version = version
                existing_plugin.config = config_payload
                existing_plugin.author = author
                existing_plugin.source = "remote_url"
                existing_plugin.dependencies = dependencies
                updated_count += 1
                imported_plugins.append(name)
                continue

            new_plugin = Plugin(
                id=str(uuid.uuid4()),
                name=name,
                version=version,
                enabled=True,
                config=config_payload,
                category="general",
                author=author,
                source="remote_url",
                dependencies=dependencies,
            )
            db.add(new_plugin)
            installed_count += 1
            imported_plugins.append(name)

        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(f"Error persisting imported plugins from URL '{source_url}': {str(exc)}")
        raise HTTPException(status_code=500, detail=f"Failed to persist imported plugins: {str(exc)}")

    return {
        "message": f"Imported {installed_count} plugin(s), updated {updated_count} plugin(s).",
        "source_url": source_url,
        "installed_count": installed_count,
        "updated_count": updated_count,
        "plugins": imported_plugins,
    }


@router.post("/{plugin_id}/hot-update", response_model=HotUpdateResponse)
async def hot_update_plugin(
    plugin_id: str,
    payload: HotUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin_user),
):
    """
    处理hot、update、plugin相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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


@router.post(
    "/{plugin_id}/rollback",
    response_model=RollbackResponse,
    summary="回滚插件",
    description="将指定插件回滚到之前的稳定版本。"
)
async def rollback_plugin(
    plugin_id: str,
    payload: RollbackRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin_user),
):
    """
    处理rollback、plugin相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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
    """
    获取plugin、logs相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
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


@router.put(
    "/{plugin_id}/log-level",
    response_model=PluginLogLevelResponse,
    summary="更新插件日志级别",
    description="修改指定插件的日志输出级别。"
)
async def update_plugin_log_level(
    plugin_id: str,
    payload: PluginLogLevelUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin_user),
):
    """
    更新plugin、log、level相关数据、配置或状态。
    阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
    """
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
