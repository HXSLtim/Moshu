"""
角色管理MCP服务
Model Context Protocol for Character Management
"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from datetime import datetime
import json
from fastapi.encoders import jsonable_encoder

from app.crud.character import (
    create_character, get_character, get_characters_by_novel,
    update_character, delete_character, update_character_ai_analysis,
    create_character_relationship, get_character_relationships,
    get_novel_relationships, update_character_relationship,
    create_character_appearance, get_character_appearances,
    update_character_last_appearance, get_character_network,
    search_characters,
)
from app.models.character_schemas import (
    CharacterCreate, CharacterUpdate,
    CharacterRelationshipUpdate, CharacterAppearanceCreate,
    CharacterAnalysisResponse, CharacterOptimizationResponse,
    MCPCharacterAction, MCPCharacterResponse,
)
from app.services.agent_service import agent_service
from loguru import logger


class CharacterMCPService:
    """角色管理MCP服务"""
    
    def __init__(self):
        self.supported_actions = {
            "create": self._create_character,
            "update": self._update_character,
            "delete": self._delete_character,
            "analyze": self._analyze_character,
            "optimize": self._optimize_character,
            "get": self._get_character,
            "list": self._list_characters,
            "search": self._search_characters,
            "create_relationship": self._create_relationship,
            "update_relationship": self._update_relationship,
            "get_network": self._get_network,
            "track_appearance": self._track_appearance,
            "generate_character": self._generate_character,
            "batch_update": self._batch_update
        }
    
    async def execute_action(
        self, 
        db: Session, 
        action: MCPCharacterAction,
        user_id: int
    ) -> MCPCharacterResponse:
        """执行MCP角色操作"""
        try:
            if action.action not in self.supported_actions:
                return MCPCharacterResponse(
                    success=False,
                    action=action.action,
                    message=f"不支持的操作: {action.action}",
                    timestamp=datetime.utcnow()
                )
            
            handler = self.supported_actions[action.action]
            result = await handler(db, action, user_id)
            safe_result = jsonable_encoder(result)
            
            return MCPCharacterResponse(
                success=True,
                action=action.action,
                character_id=safe_result.get("character_id"),
                result=safe_result,
                message=f"操作 {action.action} 执行成功",
                timestamp=datetime.utcnow()
            )
            
        except Exception as e:
            db.rollback()
            logger.error(f"MCP角色操作失败: {action.action} - {str(e)}")
            return MCPCharacterResponse(
                success=False,
                action=action.action,
                message=f"操作失败: {str(e)}",
                timestamp=datetime.utcnow()
            )
    
    async def _create_character(
        self, 
        db: Session, 
        action: MCPCharacterAction, 
        user_id: int
    ) -> Dict[str, Any]:
        """创建角色"""
        params = action.parameters
        
        character_data = CharacterCreate(
            novel_id=params["novel_id"],
            name=params["name"],
            age=params.get("age"),
            gender=params.get("gender"),
            occupation=params.get("occupation"),
            appearance=params.get("appearance"),
            personality=params.get("personality"),
            background=params.get("background"),
            skills=params.get("skills", []),
            relationships=params.get("relationships", {}),
            character_arc=params.get("character_arc"),
            importance_level=params.get("importance_level", "secondary"),
            first_appearance_chapter=params.get("first_appearance_chapter")
        )
        
        try:
            # 可选分析与角色写入必须属于同一事务；模型失败时不能留下半成品。
            character = create_character(db, character_data, commit=False)

            if action.context:
                await self._perform_ai_analysis(db, character.id, action.context)

            db.commit()
            db.refresh(character)
        except Exception:
            db.rollback()
            raise
        
        return {
            "character_id": character.id,
            "character": character,
            "message": f"角色 {character.name} 创建成功"
        }
    
    async def _update_character(
        self, 
        db: Session, 
        action: MCPCharacterAction, 
        user_id: int
    ) -> Dict[str, Any]:
        """更新角色"""
        character_id = action.character_id
        if not character_id:
            raise ValueError("缺少角色ID")
        
        update_data = CharacterUpdate(**action.parameters)
        character = update_character(db, character_id, update_data)
        
        if not character:
            raise ValueError(f"角色 {character_id} 不存在")
        
        return {
            "character_id": character.id,
            "character": character,
            "message": f"角色 {character.name} 更新成功"
        }
    
    async def _delete_character(
        self, 
        db: Session, 
        action: MCPCharacterAction, 
        user_id: int
    ) -> Dict[str, Any]:
        """删除角色"""
        character_id = action.character_id
        if not character_id:
            raise ValueError("缺少角色ID")
        
        character = get_character(db, character_id)
        if not character:
            raise ValueError(f"角色 {character_id} 不存在")
        
        character_name = character.name
        success = delete_character(db, character_id)
        
        if not success:
            raise ValueError("删除角色失败")
        
        return {
            "character_id": character_id,
            "message": f"角色 {character_name} 删除成功"
        }
    
    async def _analyze_character(
        self, 
        db: Session, 
        action: MCPCharacterAction, 
        user_id: int
    ) -> Dict[str, Any]:
        """分析角色"""
        character_id = action.character_id
        if not character_id:
            raise ValueError("缺少角色ID")
        
        character = get_character(db, character_id)
        if not character:
            raise ValueError(f"角色 {character_id} 不存在")
        
        analysis_type = action.parameters.get("analysis_type", "comprehensive")
        include_relationships = action.parameters.get("include_relationships", True)
        include_development = action.parameters.get("include_development", True)
        
        analysis_result = await self._perform_character_analysis(
            db, character, analysis_type, include_relationships, include_development
        )
        
        # 保存分析结果
        update_character_ai_analysis(db, character_id, analysis_result)
        
        return {
            "character_id": character_id,
            "analysis": analysis_result,
            "message": f"角色 {character.name} 分析完成"
        }
    
    async def _optimize_character(
        self, 
        db: Session, 
        action: MCPCharacterAction, 
        user_id: int
    ) -> Dict[str, Any]:
        """优化角色"""
        character_id = action.character_id
        if not character_id:
            raise ValueError("缺少角色ID")
        
        character = get_character(db, character_id)
        if not character:
            raise ValueError(f"角色 {character_id} 不存在")
        
        optimization_goals = action.parameters.get("optimization_goals", [])
        preserve_traits = action.parameters.get("preserve_traits", [])
        
        optimization_result = await self._perform_character_optimization(
            db, character, optimization_goals, preserve_traits
        )
        
        return {
            "character_id": character_id,
            "optimization": optimization_result,
            "message": f"角色 {character.name} 优化建议生成完成"
        }
    
    async def _get_character(
        self, 
        db: Session, 
        action: MCPCharacterAction, 
        user_id: int
    ) -> Dict[str, Any]:
        """获取角色详情"""
        character_id = action.character_id
        if not character_id:
            raise ValueError("缺少角色ID")
        
        character = get_character(db, character_id)
        if not character:
            raise ValueError(f"角色 {character_id} 不存在")
        
        # 获取关系和出场记录
        relationships = get_character_relationships(db, character_id)
        appearances = get_character_appearances(db, character_id)
        
        return {
            "character_id": character_id,
            "character": character,
            "relationships": relationships,
            "appearances": appearances,
            "message": f"获取角色 {character.name} 详情成功"
        }
    
    async def _list_characters(
        self, 
        db: Session, 
        action: MCPCharacterAction, 
        user_id: int
    ) -> Dict[str, Any]:
        """列出角色"""
        novel_id = action.novel_id or action.parameters.get("novel_id")
        if not novel_id:
            raise ValueError("缺少小说ID")
        
        importance_level = action.parameters.get("importance_level")
        skip = action.parameters.get("skip", 0)
        limit = action.parameters.get("limit", 100)
        
        characters = get_characters_by_novel(
            db, novel_id, skip, limit, importance_level
        )
        
        return {
            "novel_id": novel_id,
            "characters": characters,
            "count": len(characters),
            "message": f"获取小说 {novel_id} 的角色列表成功"
        }
    
    async def _search_characters(
        self, 
        db: Session, 
        action: MCPCharacterAction, 
        user_id: int
    ) -> Dict[str, Any]:
        """搜索角色"""
        novel_id = action.novel_id or action.parameters.get("novel_id")
        search_term = action.parameters.get("search_term")
        
        if not novel_id or not search_term:
            raise ValueError("缺少小说ID或搜索词")
        
        search_fields = action.parameters.get("search_fields")
        characters = search_characters(db, novel_id, search_term, search_fields)
        
        return {
            "novel_id": novel_id,
            "search_term": search_term,
            "characters": characters,
            "count": len(characters),
            "message": f"搜索角色完成，找到 {len(characters)} 个结果"
        }
    
    async def _create_relationship(
        self, 
        db: Session, 
        action: MCPCharacterAction, 
        user_id: int
    ) -> Dict[str, Any]:
        """创建角色关系"""
        params = action.parameters
        
        relationship_data = {
            "novel_id": params["novel_id"],
            "character_a_id": params["character_a_id"],
            "character_b_id": params["character_b_id"],
            "relationship_type": params["relationship_type"],
            "description": params.get("description"),
            "strength": params.get("strength", 5),
            "development_stage": params.get("development_stage"),
            "established_in_chapter": params.get("established_in_chapter")
        }
        
        from app.models.character_schemas import CharacterRelationshipCreate
        relationship = create_character_relationship(
            db, CharacterRelationshipCreate(**relationship_data)
        )
        
        return {
            "relationship_id": relationship.id,
            "relationship": relationship,
            "message": "角色关系创建成功"
        }
    
    async def _update_relationship(
        self,
        db: Session,
        action: MCPCharacterAction,
        user_id: int,
    ) -> Dict[str, Any]:
        """更新角色关系
        
        parameters 约定：
        - relationship_id: int 必填
        - 其余字段参考 CharacterRelationshipUpdate，可选
        """
        params = action.parameters

        relationship_id = params.get("relationship_id") or params.get("id")
        if not relationship_id:
            raise ValueError("缺少关系ID")

        update_data = CharacterRelationshipUpdate(
            relationship_type=params.get("relationship_type"),
            description=params.get("description"),
            strength=params.get("strength"),
            development_stage=params.get("development_stage"),
        )

        relationship = update_character_relationship(db, relationship_id, update_data)
        if not relationship:
            raise ValueError(f"角色关系 {relationship_id} 不存在")

        return {
            "relationship_id": relationship.id,
            "relationship": relationship,
            "message": "角色关系更新成功",
        }

    async def _track_appearance(
        self,
        db: Session,
        action: MCPCharacterAction,
        user_id: int,
    ) -> Dict[str, Any]:
        """记录角色出场

        parameters 约定：
        - character_id: int
        - chapter_id: int
        - appearance_type / description / importance_in_chapter / status_changes 可选
        """
        params = action.parameters

        character_id = params.get("character_id")
        chapter_id = params.get("chapter_id")
        if not character_id or not chapter_id:
            raise ValueError("缺少角色ID或章节ID")

        appearance_data = CharacterAppearanceCreate(
            character_id=character_id,
            chapter_id=chapter_id,
            appearance_type=params.get("appearance_type", "supporting"),
            description=params.get("description"),
            importance_in_chapter=params.get("importance_in_chapter", 5),
            status_changes=params.get("status_changes", {}),
        )

        # 创建出场记录
        appearance = create_character_appearance(db, appearance_data)

        # 尝试更新角色最后出现章节（忽略失败）
        try:
            from app.crud import novel as novel_crud

            chapter = novel_crud.get_chapter_by_id(db, chapter_id)
            if chapter:
                update_character_last_appearance(db, character_id, chapter.chapter_number)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"更新角色最后出现章节失败: {e}")

        return {
            "appearance_id": appearance.id,
            "appearance": appearance,
            "message": "角色出场记录创建成功",
        }
    
    async def _get_network(
        self, 
        db: Session, 
        action: MCPCharacterAction, 
        user_id: int
    ) -> Dict[str, Any]:
        """获取角色关系网络"""
        novel_id = action.novel_id or action.parameters.get("novel_id")
        if not novel_id:
            raise ValueError("缺少小说ID")
        
        network = get_character_network(db, novel_id)
        
        return {
            "novel_id": novel_id,
            "network": network,
            "message": "获取角色关系网络成功"
        }
    
    async def _generate_character(
        self, 
        db: Session, 
        action: MCPCharacterAction, 
        user_id: int
    ) -> Dict[str, Any]:
        """AI生成角色"""
        params = action.parameters
        novel_id = params.get("novel_id")
        
        if not novel_id:
            raise ValueError("缺少小说ID")
        
        # 获取小说信息作为上下文
        from app.crud.novel import get_novel_by_id
        novel = get_novel_by_id(db, novel_id)
        if not novel:
            raise ValueError(f"小说 {novel_id} 不存在")
        
        # 构建生成提示
        prompt_context = {
            "novel_title": novel.title,
            "novel_genre": novel.genre,
            "worldview": novel.worldview,
            "character_requirements": params.get("requirements", ""),
            "existing_characters": [c.name for c in get_characters_by_novel(db, novel_id)]
        }
        
        # 调用Agent服务生成角色
        generated_character = await agent_service.generate_character(prompt_context)
        
        # 创建角色
        character_data = CharacterCreate(
            novel_id=novel_id,
            **generated_character
        )
        
        character = create_character(db, character_data)
        
        return {
            "character_id": character.id,
            "character": character,
            "generation_context": prompt_context,
            "message": f"AI生成角色 {character.name} 成功"
        }
    
    async def _batch_update(
        self,
        db: Session,
        action: MCPCharacterAction,
        user_id: int,
    ) -> Dict[str, Any]:
        """批量更新角色

        parameters 约定：
        - updates: List[{"character_id": int, "data": {...}}]
        """
        updates = action.parameters.get("updates") or []
        if not isinstance(updates, list) or not updates:
            raise ValueError("缺少批量更新数据")

        results: List[Dict[str, Any]] = []

        for item in updates:
            char_id = item.get("character_id")
            data = item.get("data") or {}
            if not char_id:
                results.append(
                    {
                        "character_id": None,
                        "success": False,
                        "error": "缺少角色ID",
                    }
                )
                continue

            try:
                update_schema = CharacterUpdate(**data)
                character = update_character(db, char_id, update_schema)
                if not character:
                    raise ValueError("角色不存在")

                results.append(
                    {
                        "character_id": character.id,
                        "success": True,
                        "character": character,
                    }
                )
            except Exception as e:  # noqa: BLE001
                results.append(
                    {
                        "character_id": char_id,
                        "success": False,
                        "error": str(e),
                    }
                )

        return {
            "results": results,
            "total": len(results),
            "success_count": len([r for r in results if r.get("success")]),
            "message": "批量更新角色完成",
        }
    
    async def _perform_character_analysis(
        self,
        db: Session,
        character,
        analysis_type: str,
        include_relationships: bool,
        include_development: bool
    ) -> Dict[str, Any]:
        """执行角色分析"""
        analysis_context = {
            "character": {
                "name": character.name,
                "age": character.age,
                "personality": character.personality,
                "background": character.background,
                "character_arc": character.character_arc
            },
            "analysis_type": analysis_type
        }
        
        if include_relationships:
            relationships = get_character_relationships(db, character.id)
            analysis_context["relationships"] = [
                {
                    "type": rel.relationship_type,
                    "target": rel.character_b.name if rel.character_a_id == character.id else rel.character_a.name,
                    "strength": rel.strength
                }
                for rel in relationships
            ]
        
        if include_development:
            appearances = get_character_appearances(db, character.id)
            analysis_context["appearances"] = [
                {
                    "chapter": app.chapter.chapter_number,
                    "type": app.appearance_type,
                    "importance": app.importance_in_chapter
                }
                for app in appearances
            ]
        
        # 调用Agent服务进行分析
        return await agent_service.analyze_character(analysis_context)
    
    async def _perform_character_optimization(
        self,
        db: Session,
        character,
        optimization_goals: List[str],
        preserve_traits: List[str]
    ) -> Dict[str, Any]:
        """执行角色优化"""
        optimization_context = {
            "character": {
                "name": character.name,
                "personality": character.personality,
                "background": character.background,
                "skills": character.skills,
                "character_arc": character.character_arc
            },
            "goals": optimization_goals,
            "preserve": preserve_traits
        }
        
        # 调用Agent服务进行优化
        return await agent_service.optimize_character(optimization_context)
    
    async def _perform_ai_analysis(
        self, 
        db: Session, 
        character_id: int, 
        context: str
    ) -> None:
        """执行AI分析"""
        character = get_character(db, character_id)
        if character:
            analysis = await self._perform_character_analysis(
                db, character, "contextual", True, True
            )
            update_character_ai_analysis(db, character_id, analysis, commit=False)


# 创建全局服务实例
character_mcp_service = CharacterMCPService()
