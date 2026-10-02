"""
RAG系统测试脚本
测试Chroma + HuggingFace Embedding
"""
import asyncio
from app.services.rag import rag_service
from app.models.schemas import RAGQuery


async def test_rag():
    """测试RAG系统基本功能"""
    print("=" * 60)
    print("RAG系统测试")
    print("=" * 60)

    # 检查RAG服务是否可用
    if not rag_service.available:
        print("[FAIL] RAG服务不可用")
        return

    print("[OK] RAG服务已初始化\n")

    # 1. 索引测试内容
    print("【步骤1】索引测试内容...")
    test_content = """
    李明是一位年轻的修仙者，来自青云宗。他性格沉稳，天赋异禀，
    修炼了家族传承的《玄天诀》。在一次秘境探险中，他发现了
    一枚古老的玉佩，从此踏上了不平凡的修仙之路。
    """

    success = await rag_service.index_content(
        novel_id=1,
        chapter=1,
        content=test_content,
        metadata={"chapter_title": "第一章 初入修仙界"}
    )

    if success:
        print("[OK] 内容索引成功\n")
    else:
        print("[FAIL] 内容索引失败\n")
        return

    # 2. 测试检索
    print("【步骤2】测试向量检索...")

    # 测试查询1：角色相关
    print("\n查询1: '李明的性格'")
    query1 = RAGQuery(
        novel_id=1,
        query="李明的性格",
        top_k=2
    )
    response1 = await rag_service.hybrid_search(query1)

    print(f"检索到 {len(response1.results)} 条结果:")
    for i, result in enumerate(response1.results, 1):
        print(f"\n结果 {i}:")
        print(f"  内容: {result.content[:100]}...")
        print(f"  章节: {result.metadata.get('chapter')}")
        print(f"  评分: {result.score:.4f}")

    # 测试查询2：物品相关
    print("\n查询2: '玉佩的来历'")
    query2 = RAGQuery(
        novel_id=1,
        query="玉佩的来历",
        top_k=2
    )
    response2 = await rag_service.hybrid_search(query2)

    print(f"检索到 {len(response2.results)} 条结果:")
    for i, result in enumerate(response2.results, 1):
        print(f"\n结果 {i}:")
        print(f"  内容: {result.content[:100]}...")
        print(f"  章节: {result.metadata.get('chapter')}")
        print(f"  评分: {result.score:.4f}")

    # 3. 测试辅助方法
    print("\n【步骤3】测试辅助检索方法...")

    # 测试角色信息检索
    print("\n检索角色信息: '李明'")
    character_info = await rag_service.retrieve_character_info(
        novel_id=1,
        character_name="李明"
    )
    print(f"检索到 {len(character_info)} 条角色相关内容")
    for i, content in enumerate(character_info, 1):
        print(f"  {i}. {content[:80]}...")

    # 测试世界观检索
    print("\n检索世界观: '青云宗'")
    worldview = await rag_service.retrieve_worldview(
        novel_id=1,
        query="青云宗的背景"
    )
    print(f"检索到 {len(worldview)} 条世界观相关内容")
    for i, content in enumerate(worldview, 1):
        print(f"  {i}. {content[:80]}...")

    print("\n" + "=" * 60)
    print("[SUCCESS] RAG系统测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_rag())
