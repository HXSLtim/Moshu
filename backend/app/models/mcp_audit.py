"""MCP 操作审计数据模型。"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text

from app.db.base import Base


class MCPAuditLog(Base):
    """记录 MCP 操作、结果与耗时，供当前用户查看自己的历史。"""

    __tablename__ = "mcp_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    novel_id = Column(Integer, nullable=True, index=True)
    target_type = Column(String(50), nullable=False, index=True)
    action = Column(String(50), nullable=False, index=True)
    target_id = Column(Integer, nullable=True)

    parameters = Column(JSON, default=dict)
    context = Column(Text, nullable=True)
    ai_instructions = Column(Text, nullable=True)

    success = Column(Boolean, nullable=False)
    result_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    ai_reasoning = Column(Text, nullable=True)

    execution_time_ms = Column(Integer, nullable=True)
    ai_tokens_used = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<MCPAuditLog {self.target_type}.{self.action} by user {self.user_id}>"
