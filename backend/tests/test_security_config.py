"""认证密钥配置的安全回归测试。"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_secret_key_is_required(monkeypatch):
    """没有显式密钥时必须拒绝启动，不能回退到仓库内已知值。"""

    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "secret_key",
    [
        "change_this_in_production",
        "your_secret_key_here_change_in_production",
        "too-short",
    ],
)
def test_known_or_short_secret_key_is_rejected(secret_key):
    """示例占位值和短密钥都不能成为真实 JWT 签名密钥。"""

    with pytest.raises(ValidationError):
        Settings(SECRET_KEY=secret_key, _env_file=None)


def test_explicit_long_secret_key_is_accepted():
    """测试和部署仍可通过环境显式注入足够长的随机密钥。"""

    settings = Settings(
        SECRET_KEY="test-only-random-secret-key-with-at-least-32-characters",
        _env_file=None,
    )

    assert len(settings.SECRET_KEY) >= 32
