import pytest

from plugins.plugin_marketplace_service import PluginMarketplaceService


def test_parse_scoped_npm_source_builds_registry_tarball_url() -> None:
    result = PluginMarketplaceService().parse_npm_source("npm:@openawa/sample-plugin@1.2.3")

    assert result["package_name"] == "@openawa/sample-plugin"
    assert result["version"] == "1.2.3"
    assert result["tarball_url"] == (
        "https://registry.npmjs.org/@openawa%2fsample-plugin/-/sample-plugin-1.2.3.tgz"
    )


def test_validate_remote_url_uses_allowlist_and_resolver() -> None:
    service = PluginMarketplaceService({"github.com"})
    resolved = service.validate_remote_url(
        "https://github.com/openawa/plugin.zip",
        lambda hostname: ["140.82.112.3"] if hostname == "github.com" else [],
    )

    assert resolved == ["140.82.112.3"]
    with pytest.raises(ValueError, match="白名单"):
        service.validate_remote_url("https://example.com/plugin.zip", lambda _: [])
    with pytest.raises(ValueError, match="Invalid remote plugin URL"):
        service.validate_remote_url("ftp://github.com/plugin.zip", lambda _: [])


@pytest.mark.parametrize(
    ("status_code", "headers", "content"),
    [
        (302, {}, b"zip"),
        (404, {}, b"zip"),
        (200, {}, b""),
        (200, {"content-type": "text/html"}, b"zip"),
    ],
)
def test_validate_remote_response_rejects_invalid_payloads(
    status_code: int,
    headers: dict[str, str],
    content: bytes,
) -> None:
    with pytest.raises(ValueError):
        PluginMarketplaceService({"github.com"}).validate_remote_response(
            status_code,
            headers,
            content,
        )


@pytest.mark.parametrize(
    "source",
    ["sample-plugin", "npm:@openawa/sample-plugin", "npm:sample-plugin@latest", "npm:UPPER@1.2.3"],
)
def test_parse_npm_source_rejects_ambiguous_or_unpinned_coordinates(source: str) -> None:
    with pytest.raises(ValueError):
        PluginMarketplaceService().parse_npm_source(source)
