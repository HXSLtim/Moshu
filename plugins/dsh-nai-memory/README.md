# dsh-nai-memory

把 [TencentDB Agent Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory) 的四层记忆系统接入 DeepSeek Harness。

底层实现为社区移植包 [dsh-tdai-memory](https://www.npmjs.com/package/dsh-tdai-memory)，本包提供 DSH bundle 包装与 Nai 默认配置：

- **L0 对话捕获**：每轮对话原文写入 `~/.memory-tencentdb/memory-tdai`（JSONL + SQLite + FTS + 向量）。
- **L1 结构化记忆**：后台 LLM 提取事实、偏好、事件。
- **L2 场景 / L3 画像**：管线自动生成场景块与用户画像。
- **自动召回注入**：每轮按当前消息检索 L1 记忆与 L3 画像，注入系统上下文。
- **工具**：`tdai_memory_search`（查 L1 结构化记忆）、`tdai_conversation_search`（查 L0 原文）。

## 安装

从 Nai 仓库根目录执行：

```bash
node plugins/dsh-nai-memory/scripts/install-profile.mjs
```

脚本依次安装 bundle 和 profile 根目录的底层插件依赖，任何一步失败都会返回非零退出码。若 pnpm 要求审核依赖构建脚本，按其提示配置后重新运行；本脚本不会覆盖已有构建策略。可用 `DSH_HOME` 和 `DSH_PROFILE` 指定安装位置，默认 profile 为 `web`。

## 配置

默认配置面向 Nai 的 LM Studio 基线：

```yaml
llm:
  baseUrl: http://127.0.0.1:1234/v1
  apiKey: lm-studio
  model: google/gemma-4-26b-a4b-qat
embedding:
  baseUrl: http://127.0.0.1:1234/v1
  apiKey: lm-studio
  model: text-embedding-nomic-embed-text-v1.5
```

记忆提取是后台任务，不阻塞对话；LM Studio 未启动时只影响 L1/L2/L3 生成与召回，L0 原文捕获仍会继续。也可以在 DSH Web 的「设置 → 记忆」里改成 DeepSeek 或其他 OpenAI 兼容模型。

## 数据位置与复用

- 数据目录默认 `~/.memory-tencentdb/memory-tdai`。
- 如果你之前已经用过腾讯官方 OpenClaw 版本，同一目录会被直接复用，是否兼容需结合底层包版本验证，复用前应备份原目录。

## 验证范围

本仓库测试安装脚本的成功与失败行为，不实现底层记忆算法。L0-L3、模型调用和历史数据兼容性需要安装底层包并配置模型后验收，不能仅凭包装层测试通过认定全部可用。

```bash
cd plugins/dsh-nai-memory
npm test
```
