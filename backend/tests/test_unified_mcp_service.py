"""
统一MCP服务测试
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from sqlalchemy.orm import Session

from app.services.unified_mcp_service import UnifiedMCPService, unified_mcp_service
from app.models.worldview_schemas import (
    UnifiedMCPAction, UnifiedMCPResponse,
    NovelAnalysisRequest, NovelOptimizationRequest
)
from app.models.user import User
from app.models.novel import Novel


class TestUnifiedMCPService:
    """统一MCP服务测试类"""
    
    @pytest.fixture
    def mock_db(self):
        """模拟数据库会话"""
        return MagicMock(spec=Session)
    
    @pytest.fixture
    def mock_user(self):
        """模拟用户"""
        user = MagicMock(spec=User)
        user.id = 1
        user.username = "test_user"
        return user
    
    @pytest.fixture
    def mock_novel(self):
        """模拟小说"""
        novel = MagicMock(spec=Novel)
        novel.id = 1
        novel.title = "测试小说"
        novel.user_id = 1
        return novel
    
    @pytest.fixture
    def sample_mcp_action(self):
        """示例MCP操作"""
        return UnifiedMCPAction(
            target_type="character",
            action="analyze",
            novel_id=1,
            parameters={"analysis_depth": "comprehensive"},
            context="测试上下文"
        )
    
    @pytest.mark.asyncio
    async def test_execute_unified_action_success(
        self, mock_db, mock_user, mock_novel, sample_mcp_action
    ):
        """测试统一MCP操作成功执行"""
        mock_handler = AsyncMock(
            return_value={"target_id": 1, "message": "操作成功"}
        )
        # 模拟小说查询
        with (
            patch('app.services.unified_mcp_service.get_novel_by_id', return_value=mock_novel),
            patch.dict(
                unified_mcp_service.target_handlers,
                {"character": mock_handler},
            ),
        ):
            result = await unified_mcp_service.execute_unified_action(
                mock_db, sample_mcp_action, mock_user.id
            )

        # 验证结果
        assert result.success is True
        assert result.target_type == "character"
        assert result.action == "analyze"
        assert "操作成功" in result.message
        mock_handler.assert_awaited_once()
    
    @pytest.mark.asyncio
    async def test_execute_unified_action_invalid_novel(
        self, mock_db, mock_user, sample_mcp_action
    ):
        """测试无效小说ID的处理"""
        # 模拟小说不存在
        with patch('app.services.unified_mcp_service.get_novel_by_id', return_value=None):
            
            result = await unified_mcp_service.execute_unified_action(
                mock_db, sample_mcp_action, mock_user.id
            )
            
            # 验证错误处理
            assert result.success is False
            assert "小说不存在或无权访问" in result.message

    @pytest.mark.asyncio
    async def test_unauthorized_novel_is_rejected_before_operation_counting(
        self, mock_db, sample_mcp_action
    ):
        """越权请求不能先占用目标小说的并发配额。"""
        service = UnifiedMCPService()
        service.max_concurrent_operations = 0
        victim_novel = MagicMock(spec=Novel, id=1, user_id=999)

        with (
            patch(
                'app.services.unified_mcp_service.get_novel_by_id',
                return_value=victim_novel,
            ),
            patch.object(service, '_log_operation', new=AsyncMock()),
        ):
            result = await service.execute_unified_action(
                mock_db,
                sample_mcp_action,
                user_id=1,
            )

        assert result.success is False
        assert result.message == "小说不存在或无权访问"
        assert service._operation_counters == {}

    @pytest.mark.asyncio
    async def test_operation_counter_is_removed_after_failure(self):
        """操作异常退出后应删除归零计数，避免长期积累小说 ID。"""
        service = UnifiedMCPService()

        with pytest.raises(RuntimeError, match="模拟失败"):
            async with service._operation_context(7, 88, "character.list.1"):
                assert service._operation_counters[(7, 88)] == 1
                raise RuntimeError("模拟失败")

        assert (7, 88) not in service._operation_counters
    
    @pytest.mark.asyncio
    async def test_execute_unified_action_unsupported_target(
        self, mock_db, mock_user, mock_novel
    ):
        """测试不支持的目标类型"""
        # 创建无效目标类型的操作
        invalid_action = UnifiedMCPAction(
            target_type="invalid_type",
            action="analyze",
            novel_id=1
        )
        
        with patch('app.services.unified_mcp_service.get_novel_by_id', return_value=mock_novel):
            
            result = await unified_mcp_service.execute_unified_action(
                mock_db, invalid_action, mock_user.id
            )
            
            # 验证错误处理
            assert result.success is False
            assert "目标类型尚未实现" in result.message
    
    @pytest.mark.asyncio
    async def test_execute_unified_action_unsupported_action(
        self, mock_db, mock_user, mock_novel
    ):
        """测试不支持的操作类型"""
        # 创建无效操作类型的操作
        invalid_action = UnifiedMCPAction(
            target_type="character",
            action="invalid_action",
            novel_id=1
        )
        
        with patch('app.services.unified_mcp_service.get_novel_by_id', return_value=mock_novel):
            
            result = await unified_mcp_service.execute_unified_action(
                mock_db, invalid_action, mock_user.id
            )
            
            # 验证错误处理
            assert result.success is False
            assert "操作尚未实现" in result.message
    
    @pytest.mark.asyncio
    async def test_analyze_novel_comprehensive_success(
        self, mock_db, mock_user, mock_novel
    ):
        """测试全面分析小说成功"""
        analysis_request = NovelAnalysisRequest(
            novel_id=1,
            analysis_scope=["worldview", "character"],
            analysis_depth="comprehensive"
        )
        
        with pytest.raises(NotImplementedError, match="真实数据链路"):
            await unified_mcp_service.analyze_novel_comprehensive(
                mock_db, analysis_request, mock_user.id
            )
    
    @pytest.mark.asyncio
    async def test_optimize_novel_comprehensive_success(
        self, mock_db, mock_user, mock_novel
    ):
        """测试全面优化小说成功"""
        optimization_request = NovelOptimizationRequest(
            novel_id=1,
            optimization_goals=["提升质量", "增强一致性"],
            target_areas=["worldview", "character"]
        )
        
        with pytest.raises(NotImplementedError, match="真实数据链路"):
            await unified_mcp_service.optimize_novel_comprehensive(
                mock_db, optimization_request, mock_user.id
            )
    
    @pytest.mark.asyncio
    async def test_handle_character_delegation(
        self, mock_db, mock_user, sample_mcp_action
    ):
        """测试角色处理委托给角色MCP服务"""
        with patch('app.services.character_mcp_service.character_mcp_service.execute_action') as mock_execute:
            # 模拟角色MCP服务返回
            mock_response = MagicMock()
            mock_response.success = True
            mock_response.character_id = 1
            mock_response.result = {"character": "test"}
            mock_execute.return_value = mock_response
            
            result = await unified_mcp_service._handle_character(
                mock_db, sample_mcp_action, mock_user.id
            )
            
            # 验证委托调用
            mock_execute.assert_called_once()
            assert result["target_id"] == 1
            assert "角色analyze操作完成" in result["message"]
    
    @pytest.mark.asyncio
    async def test_error_handling_and_logging(
        self, mock_db, mock_user, sample_mcp_action
    ):
        """测试错误处理和日志记录"""
        with patch('app.services.unified_mcp_service.get_novel_by_id', side_effect=Exception("数据库错误")):
            with patch('loguru.logger.error') as mock_logger:
                
                result = await unified_mcp_service.execute_unified_action(
                    mock_db, sample_mcp_action, mock_user.id
                )
                
                # 验证错误处理
                assert result.success is False
                assert "操作失败" in result.message
                
                # 验证日志记录
                mock_logger.assert_called_once()
    
    def test_supported_actions_completeness(self):
        """测试支持的操作类型完整性"""
        expected_actions = {
            "analyze", "optimize", "create", "update", "delete",
            "get", "list", "search", "generate_character",
        }
        
        actual_actions = set(unified_mcp_service.supported_actions.keys())
        
        # 验证所有预期操作都被支持
        assert actual_actions == expected_actions
    
    def test_target_handlers_completeness(self):
        """测试目标处理器完整性"""
        expected_targets = {"character"}
        
        actual_targets = set(unified_mcp_service.target_handlers.keys())
        
        # 验证所有预期目标都有处理器
        assert actual_targets == expected_targets

    @pytest.mark.asyncio
    async def test_placeholder_target_returns_explicit_failure(
        self, mock_db, mock_user, mock_novel
    ):
        action = UnifiedMCPAction(
            target_type="worldview",
            action="analyze",
            novel_id=mock_novel.id,
        )

        with patch('app.services.unified_mcp_service.get_novel_by_id', return_value=mock_novel):
            result = await unified_mcp_service.execute_unified_action(
                mock_db, action, mock_user.id
            )

        assert result.success is False
        assert "尚未实现" in result.message

    @pytest.mark.asyncio
    async def test_character_child_failure_is_not_wrapped_as_success(
        self, mock_db, mock_user, mock_novel
    ):
        action = UnifiedMCPAction(
            target_type="character",
            action="list",
            novel_id=mock_novel.id,
        )
        child_result = MagicMock(
            success=False,
            message="角色服务失败",
            character_id=None,
            result=None,
        )

        with (
            patch('app.services.unified_mcp_service.get_novel_by_id', return_value=mock_novel),
            patch(
                'app.services.character_mcp_service.character_mcp_service.execute_action',
                return_value=child_result,
            ),
        ):
            result = await unified_mcp_service.execute_unified_action(
                mock_db, action, mock_user.id
            )

        assert result.success is False
        assert "角色服务失败" in result.message

    @pytest.mark.asyncio
    async def test_character_target_must_belong_to_action_novel(
        self, mock_db, mock_user, mock_novel
    ):
        action = UnifiedMCPAction(
            target_type="character",
            action="update",
            novel_id=mock_novel.id,
            target_id=99,
            parameters={"name": "新名字"},
        )
        child_execute = AsyncMock()

        with (
            patch('app.services.unified_mcp_service.get_novel_by_id', return_value=mock_novel),
            patch(
                'app.crud.character.get_character',
                return_value=MagicMock(novel_id=999),
            ),
            patch(
                'app.services.character_mcp_service.character_mcp_service.execute_action',
                child_execute,
            ),
        ):
            result = await unified_mcp_service.execute_unified_action(
                mock_db, action, mock_user.id
            )

        assert result.success is False
        assert "不属于该小说" in result.message
        child_execute.assert_not_awaited()

    def test_capabilities_only_advertise_real_matrix(self):
        capabilities = unified_mcp_service.get_capabilities()

        assert set(capabilities["target_types"]) == {"character"}
        assert "validate" not in capabilities["action_types"]
        assert "auto_fix" not in capabilities["action_types"]


class TestMCPIntegration:
    """MCP集成测试"""
    
    @pytest.mark.asyncio
    async def test_full_workflow_character_analysis(self):
        """测试完整的角色分析工作流"""
        # 这里可以添加端到端的集成测试
        # 测试从API调用到服务执行的完整流程
        pass
    
    @pytest.mark.asyncio
    async def test_concurrent_mcp_operations(self):
        """测试并发MCP操作"""
        # 测试多个MCP操作同时执行的情况
        pass
    
    @pytest.mark.asyncio
    async def test_mcp_operation_rollback(self):
        """测试MCP操作回滚"""
        # 测试操作失败时的回滚机制
        pass
