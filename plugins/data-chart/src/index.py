from typing import Any, Dict, List, Optional
from loguru import logger
from backend.plugins.base_plugin import BasePlugin

SUPPORTED_CHART_TYPES = {"line", "bar", "pie"}
SUPPORTED_INTERVALS = {"1h", "6h", "24h", "7d", "30d"}


class DataChartPlugin(BasePlugin):
    name: str = "data-chart"
    version: str = "1.0.0"
    description: str = "演示API拦截与权限申请的数据图表插件"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._api_base_url: str = self.config.get("api_base_url", "")
        self._api_key: str = self.config.get("api_key", "")
        self._default_chart_type: str = self.config.get("default_chart_type", "line")
        self._max_data_points: int = int(self.config.get("max_data_points", 500))
        self._intercepted_requests: int = 0

    def initialize(self) -> bool:
        logger.info(f"[{self.name}] 初始化数据图表插件")
        if not self._api_base_url:
            logger.warning(f"[{self.name}] 未配置 api_base_url，将使用模拟数据模式")
        if not self._api_key:
            logger.warning(f"[{self.name}] 未配置 api_key，部分接口可能无法访问")
        logger.info(
            f"[{self.name}] 初始化完成，默认图表类型：{self._default_chart_type}，"
            f"最大数据点数：{self._max_data_points}"
        )
        self._initialized = True
        return True

    def execute(self, *args, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "fetch_chart_data")
        logger.debug(f"[{self.name}] 执行动作：{action}")

        if action == "fetch_chart_data":
            return self._fetch_chart_data(
                chart_type=kwargs.get("chart_type", self._default_chart_type),
                metric=kwargs.get("metric", "requests"),
                interval=kwargs.get("interval", "24h"),
            )
        if action == "api_intercept_middleware":
            return self._intercept_api_request(
                path=kwargs.get("path", ""),
                headers=kwargs.get("headers", {}),
            )
        if action == "chart_data_provider":
            return self._provide_chart_data(
                chart_type=kwargs.get("chart_type", self._default_chart_type),
                dataset_id=kwargs.get("dataset_id", ""),
            )

        logger.warning(f"[{self.name}] 未知动作：{action}")
        return {"status": "error", "message": f"未知动作：{action}"}

    def _fetch_chart_data(
        self, chart_type: str, metric: str, interval: str
    ) -> Dict[str, Any]:
        if chart_type not in SUPPORTED_CHART_TYPES:
            return {
                "status": "error",
                "message": f"不支持的图表类型：{chart_type}，支持：{sorted(SUPPORTED_CHART_TYPES)}"
            }
        if interval not in SUPPORTED_INTERVALS:
            return {
                "status": "error",
                "message": f"不支持的时间间隔：{interval}，支持：{sorted(SUPPORTED_INTERVALS)}"
            }

        logger.info(
            f"[{self.name}] 拉取图表数据，类型：{chart_type}，指标：{metric}，周期：{interval}"
        )

        if self._api_base_url and self._api_key:
            return self._real_fetch(chart_type, metric, interval)
        return self._mock_data(chart_type, metric, interval)

    def _real_fetch(self, chart_type: str, metric: str, interval: str) -> Dict[str, Any]:
        import httpx
        url = f"{self._api_base_url}/metrics/{metric}?interval={interval}"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        logger.debug(f"[{self.name}] 发起 HTTP 请求：{url}")
        try:
            response = httpx.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            raw = response.json()
            points = raw.get("data", [])[:self._max_data_points]
            return {
                "status": "success",
                "chart_type": chart_type,
                "metric": metric,
                "interval": interval,
                "data_points": points,
                "source": "remote",
            }
        except Exception as e:
            logger.error(f"[{self.name}] HTTP 请求失败：{e}")
            return {"status": "error", "message": f"数据拉取失败：{e}"}

    def _mock_data(self, chart_type: str, metric: str, interval: str) -> Dict[str, Any]:
        logger.info(f"[{self.name}] 使用模拟数据（未配置 api_base_url）")
        intervals_map = {"1h": 12, "6h": 24, "24h": 48, "7d": 56, "30d": 60}
        count = min(intervals_map.get(interval, 24), self._max_data_points)
        data_points = [
            {"index": i, "value": (i * 7 + 13) % 100, "label": f"t{i}"}
            for i in range(count)
        ]
        return {
            "status": "success",
            "chart_type": chart_type,
            "metric": metric,
            "interval": interval,
            "data_points": data_points,
            "source": "mock",
        }

    def _intercept_api_request(
        self, path: str, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        self._intercepted_requests += 1
        logger.debug(
            f"[{self.name}] 拦截请求 #{self._intercepted_requests}：{path}"
        )
        modified_headers = dict(headers)
        if self._api_key:
            modified_headers["X-Chart-Token"] = self._api_key
        modified_headers["X-Plugin-Version"] = self.version
        return {
            "status": "success",
            "action": "continue",
            "modified_headers": modified_headers,
            "intercepted_count": self._intercepted_requests,
        }

    def _provide_chart_data(
        self, chart_type: str, dataset_id: str
    ) -> Dict[str, Any]:
        logger.info(
            f"[{self.name}] 提供图表数据，类型：{chart_type}，数据集：{dataset_id or '默认'}"
        )
        return {
            "status": "success",
            "chart_type": chart_type,
            "dataset_id": dataset_id or "default",
            "schema": {
                "x_axis": {"type": "string", "label": "时间"},
                "y_axis": {"type": "number", "label": "数值"},
            },
            "data": self._mock_data(chart_type, dataset_id or "default", "24h")["data_points"],
        }

    def validate(self) -> bool:
        default_chart = self.config.get("default_chart_type", "line")
        if default_chart not in SUPPORTED_CHART_TYPES:
            logger.error(
                f"[{self.name}] 配置项 'default_chart_type' 无效：{default_chart}"
            )
            return False
        max_points = self.config.get("max_data_points", 500)
        try:
            if int(max_points) <= 0:
                logger.error(f"[{self.name}] 配置项 'max_data_points' 必须大于 0")
                return False
        except (TypeError, ValueError):
            logger.error(f"[{self.name}] 配置项 'max_data_points' 必须是整数")
            return False
        return True

    def cleanup(self) -> None:
        logger.info(
            f"[{self.name}] 清理数据图表插件，共拦截请求 {self._intercepted_requests} 次"
        )
        self._intercepted_requests = 0
        super().cleanup()

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "fetch_chart_data",
                "description": "从配置的数据源拉取图表数据，支持折线图、柱状图、饼图",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chart_type": {
                            "type": "string",
                            "description": "图表类型",
                            "enum": ["line", "bar", "pie"]
                        },
                        "metric": {
                            "type": "string",
                            "description": "要查询的指标名称，如 requests、latency、error_rate"
                        },
                        "interval": {
                            "type": "string",
                            "description": "时间范围",
                            "enum": ["1h", "6h", "24h", "7d", "30d"]
                        }
                    },
                    "required": ["metric"]
                }
            }
        ]
