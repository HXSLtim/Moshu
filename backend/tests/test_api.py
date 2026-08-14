"""
API端到端测试
测试FastAPI路由和完整的请求响应流程
"""
import pytest
from fastapi.testclient import TestClient


class TestHealthAPI:
    """健康检查API测试"""

    def test_health_check(self, client: TestClient):
        """测试健康检查接口"""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "app_name" in data
        assert "version" in data

    def test_ping(self, client: TestClient):
        """测试ping接口"""
        response = client.get("/api/ping")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "pong"


class TestGenerationAPI:
    """内容生成API测试"""

    def test_generate_content_missing_fields(self, client: TestClient):
        """测试生成接口 - 缺少必填字段"""
        response = client.post(
            "/api/generation/generate",
            json={}
        )

        # 生成接口受保护，未认证请求应在进入模型和正文校验前被拒绝。
        assert response.status_code == 403

    def test_generate_content_invalid_data(self, client: TestClient):
        """测试生成接口 - 无效数据"""
        response = client.post(
            "/api/generation/generate",
            json={
                "novel_id": "invalid",  # 应该是int
                "prompt": "测试",
                "chapter": 1
            }
        )

        assert response.status_code == 403

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_generate_content_success(self, integration_client: TestClient):
        """测试生成接口 - 成功（需要真实API）"""
        response = integration_client.post(
            "/api/generation/generate",
            json={
                "novel_id": 1,
                "prompt": "主角在森林中遇到了一只神秘的魔兽",
                "chapter": 1,
                "current_day": 1,
                "target_length": 300
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "final_content" in data
        assert "agent_outputs" in data
        assert len(data["agent_outputs"]) == 3
        assert data["novel_id"] == 1
        assert data["chapter"] == 1

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_generation_test_endpoint(self, integration_client: TestClient):
        """测试生成测试接口"""
        response = integration_client.get("/api/generation/test")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "测试成功"
        assert "final_content" in data
        assert "length" in data
        assert isinstance(data["length"], int)
