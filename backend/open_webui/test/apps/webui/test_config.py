import os
import pytest

from open_webui.config import (
    OAuthConfig,
    WebUIConfig,
)


def test_oauth_config_post_init():
    """
    Ensure that the OAUTH_PROVIDERS dict is built correctly post-init.
    """
    os.environ["OAUTH_CLIENT_ID"] = "test_client_id"
    os.environ["OAUTH_CLIENT_SECRET"] = "test_client_secret"  # pragma: allowlist secret
    os.environ["OPENID_PROVIDER_URL"] = (
        "https://example.com/.well-known/openid-configuration"
    )
    os.environ["OAUTH_PROVIDER_NAME"] = "Test Provider"
    os.environ["OAUTH_SCOPES"] = "openid email profile"
    os.environ["OPENID_REDIRECT_URI"] = "https://example.com/callback"

    config = OAuthConfig()

    assert config.OAUTH_PROVIDERS["oidc"]["client_id"] == "test_client_id"
    assert (
        config.OAUTH_PROVIDERS["oidc"]["client_secret"]
        == "test_client_secret"  # pragma: allowlist secret
    )
    assert (
        config.OAUTH_PROVIDERS["oidc"]["server_metadata_url"]
        == "https://example.com/.well-known/openid-configuration"
    )
    assert config.OAUTH_PROVIDERS["oidc"]["name"] == "Test Provider"
    assert config.OAUTH_PROVIDERS["oidc"]["scope"] == "openid email profile"
    assert (
        config.OAUTH_PROVIDERS["oidc"]["redirect_uri"] == "https://example.com/callback"
    )


def test_webui_config_cors_env():
    """
    Ensure that the CORS_ALLOW_ORIGIN value is properly parsed from the environment.
    """
    os.environ["CORS_ALLOW_ORIGIN"] = '["http://localhost:3000","http://example.com"]'

    config = WebUIConfig()

    assert config.CORS_ALLOW_ORIGIN == ["http://localhost:3000", "http://example.com"]


def test_webui_config_cors_validation():
    """
    Ensure that the CORS_ALLOW_ORIGIN value is properly validated.
    """
    with pytest.raises(ValueError):
        WebUIConfig(CORS_ALLOW_ORIGIN=["grcp://localhost"])

    with pytest.raises(ValueError):
        WebUIConfig(CORS_ALLOW_ORIGIN=["http://"])

    with pytest.raises(ValueError):
        WebUIConfig(CORS_ALLOW_ORIGIN=["localhost"])
