"""检查本地应用生成的 OpenAPI 规范，失败时返回非零退出码。"""

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def main() -> int:
    """校验 /docs 的 OpenAPI 规范完整覆盖所有已注册 API 路由。"""
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    if response.status_code != 200:
        print(f"无法获取 OpenAPI 规范: HTTP {response.status_code}", file=sys.stderr)
        print(response.text, file=sys.stderr)
        return 1

    spec = response.json()
    spec_paths = set(spec.get("paths", {}).keys())
    api_paths = {
        route.path
        for route in app.routes
        if hasattr(route, "path") and route.path.startswith("/api")
    }
    missing_paths = sorted(api_paths - spec_paths)
    story_bible_paths = sorted(path for path in spec_paths if "/api/story-bible" in path)
    story_bible_operations = sum(
        len([method for method in spec["paths"][path] if method in {"get", "post", "put", "delete"}])
        for path in story_bible_paths
    )

    print("=" * 60)
    print("OpenAPI 规范校验")
    print("=" * 60)
    print(f"已注册 /api 路由: {len(api_paths)}")
    print(f"OpenAPI 路径: {len(spec_paths)}")
    print(f"Story Bible 路径: {len(story_bible_paths)}")
    print(f"Story Bible 操作: {story_bible_operations}")

    for path in story_bible_paths:
        methods = list(spec["paths"][path].keys())
        print(f"✓ {path}: {methods}")

    if missing_paths:
        print("\n✗ OpenAPI 规范缺少以下已注册路由：")
        for path in missing_paths:
            print(f"  {path}")
        return 1

    if story_bible_operations != 10:
        print(
            f"\n✗ Story Bible 应包含 10 个操作，实际为 {story_bible_operations} 个。",
            file=sys.stderr,
        )
        return 1

    output = Path(__file__).resolve().parent / "openapi_spec.json"
    output.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ 所有 /api 路由均已进入 OpenAPI 规范，报告已保存到 {output.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
