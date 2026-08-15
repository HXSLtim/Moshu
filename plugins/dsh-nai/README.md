# dsh-nai

把 [Nai](https://github.com/your-org/nai) 的能力暴露给 DeepSeek Harness 的 Cordis 组合包。

## 安装

```bash
dsh plugin --profile demo add ./plugins/dsh-nai
dsh --profile demo --dump-config
dsh --profile demo web
```

或安装到默认 profile：

```bash
dsh plugin add ./plugins/dsh-nai
dsh web
```

## 配置

在 profile 的 `cordis.patch.yml` 中覆盖：

```yaml
- insert:
    - id: nai
      name: dsh-nai
      config:
        apiBase: http://127.0.0.1:8000/api
        token: <Nai JWT access token>
        timeoutMs: 60000
```

- `apiBase`：Nai 后端基址，默认 `http://127.0.0.1:8000/api`。
- `token`：登录 Nai 后拿到的 JWT；不填只能调用健康检查。
- `timeoutMs`：HTTP 超时，默认 60 秒。

## 工具清单

| 工具 | 用途 |
|---|---|
| `nai_health` | 检查 Nai 服务是否在线 |
| `nai_story_facts_list` | 列出 Story Bible 事实账本 |
| `nai_story_events_list` | 列出剧情事件 |
| `nai_story_fact_create` | 创建已确认事实 |
| `nai_story_fact_update` | 更新/退役事实 |
| `nai_story_event_create` | 创建剧情事件与伏笔 |
| `nai_chapters_list` | 分页读取章节摘要 |
| `nai_generation_generate` | 生成候选正文，并返回实际读取的 Story Bible 上下文 |

## 测试

```bash
cd plugins/dsh-nai
npm install
npm test
```

## 边界

- 插件只做 HTTP 桥接；Nai 后端需要单独启动。
- `nai_generation_generate` 可能耗时较长，生成结果不会自动写入章节，符合 Nai“AI 只提供候选内容”的原则。
