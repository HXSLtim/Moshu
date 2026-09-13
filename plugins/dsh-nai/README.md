# dsh-nai

把 [Nai](https://github.com/HXSLtim/Nai) 的能力暴露给 DeepSeek Harness 的 Cordis 组合包。

## 安装

推荐配合 `dsh-nai-ui` 一起使用：工具包由 `nai-author` preset 挂载，Web 前端由 profile 全局挂载。

以下安装命令均从 Nai 仓库根目录执行。

```bash
dsh plugin --profile web add ./plugins/dsh-nai
dsh plugin --profile web add ./plugins/dsh-nai-ui

# 从 profile 的 dsh.profile.bundles 中删除 "dsh-nai"，保留 "dsh-nai-ui"，
# 工具就只出现在 nai-author preset，不会污染其他会话。
mkdir -p ~/.dsh/.agent-presets
cp -R plugins/dsh-nai-ui/presets/nai-author ~/.dsh/.agent-presets/nai-author
dsh --profile web --port 3080
```

## 配置

Web 前端 `dsh-nai-ui` 在 profile 的 `cordis.patch.yml` 中覆盖：

```yaml
- id: nai-ui
  config:
    apiBase: http://127.0.0.1:8000/api
    token: <Nai JWT access token>
    timeoutMs: 60000
```

`nai-author` preset 中的 `dsh-nai` 行在 `~/.dsh/.agent-presets/nai-author/agent.cordis.yml` 配置，仓库模板使用 `process.env.NAI_TOKEN` 占位；安装后执行：

```bash
node plugins/dsh-nai-ui/scripts/configure-local-token.mjs
```

该脚本会把 profile 里的 token 写入本地 preset 文件，不打印明文。

- `apiBase`：Nai 后端基址，默认 `http://127.0.0.1:8000/api`。
- `token`：登录 Nai 后拿到的 JWT；不填只能调用健康检查。
- `timeoutMs`：HTTP 超时，默认 60 秒。

## 工具清单

| 工具 | 用途 |
|---|---|
| `nai_health` | 检查 Nai 服务是否在线 |
| `nai_novels_list` | 列出当前作者的全部小说，取得 `novel_id` |
| `nai_novel_create` | 创建小说 |
| `nai_novel_get` | 读取小说详情与世界观设定 |
| `nai_characters_list` | 列出小说角色档案 |
| `nai_story_facts_list` | 列出 Story Bible 事实账本 |
| `nai_story_events_list` | 列出剧情事件 |
| `nai_story_fact_create` | 创建已确认事实 |
| `nai_story_fact_update` | 更新/退役事实 |
| `nai_story_event_create` | 创建剧情事件与伏笔 |
| `nai_chapters_list` | 分页读取章节摘要 |
| `nai_chapter_get` | 按需读取单章正文与版本号 |
| `nai_chapter_create_next` | 由服务端分配章号创建下一章 |
| `nai_chapter_update` | 用乐观锁保存章节标题或正文 |
| `nai_generation_generate` | 生成候选正文，并返回实际读取的 Story Bible 上下文 |

## 测试

```bash
cd plugins/dsh-nai
npm install
npm test
```

## 边界

- 插件只做 HTTP 桥接；Nai 后端需要单独启动，并确保 `init_db.py` 已执行到最新迁移。
- `nai_generation_generate` 可能耗时较长，生成结果不会自动写入章节，符合 Nai“AI 只提供候选内容”的原则；作者确认后再用 `nai_chapter_update` 或 `nai_chapter_create_next` 落库。
- `nai_chapter_update` 遵守后端乐观锁与生命周期栅栏：必须先读取作品/章节拿到 `version` 和两个 `rag_lifecycle_id`，冲突时后端返回 409，需重新读取并向作者说明。
