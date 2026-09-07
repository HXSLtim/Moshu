# dsh-nai-ui

为 `dsh-nai` 与 `nai-author` preset 提供 DeepSeek Harness Web 前端界面。

## 展示内容

- 会话头部「Nai 写作台」按钮：仅当当前会话使用 `nai-author` preset 时显示。
- `conversation.view` 新增「Nai 写作台」视图页：展示后端健康、小说列表、章节数与字数，并可一键让 Agent 打开小说或生成下一章候选。
- `tool.call.toolview` 工具卡片：章节列表渲染为表格，生成候选渲染为可滚动正文预览，其余 Nai 工具渲染结构化 JSON。

## 安装

以下安装命令均从 Nai 仓库根目录执行。

```bash
dsh plugin --profile web add ./plugins/dsh-nai
dsh plugin --profile web add ./plugins/dsh-nai-ui

# 从 profile 的 dsh.profile.bundles 中删除 "dsh-nai"，保留 "dsh-nai-ui"，
# 这样 Nai 工具只通过 preset 生效，不会出现在其他会话。
mkdir -p ~/.dsh/.agent-presets
cp -R plugins/dsh-nai-ui/presets/nai-author ~/.dsh/.agent-presets/nai-author
node plugins/dsh-nai-ui/scripts/configure-local-token.mjs
```

## 配置

`dsh-nai-ui` 在 profile 的 `cordis.patch.yml` 中覆盖：

```yaml
- id: nai-ui
  config:
    apiBase: http://127.0.0.1:8000/api
    token: <Nai JWT access token>
    timeoutMs: 60000
```

`dsh-nai-ui` 会把 `/nai-api/*` 同源代理到 Nai 后端，浏览器不接触 JWT，也不会受 Nai 后端 CORS 限制。

`nai-author` preset 中的 `dsh-nai` 工具行在 `~/.dsh/.agent-presets/nai-author/agent.cordis.yml` 配置。仓库模板用 `process.env.NAI_TOKEN` 占位；执行 `scripts/configure-local-token.mjs` 后，本机 preset 文件会写入与 profile 相同的 token。

之后在 DSH Web 新建会话时选择「Nai 作者」即可；该 preset 会话会自动出现「Nai 写作台」头部按钮与视图页。

## 测试

```bash
cd plugins/dsh-nai-ui
npm install
npm test
```

## 验证范围

本仓库包含宿主代理和令牌同步脚本的自动化测试；DSH Web 的实际插槽挂载与浏览器交互仍需在已配置的 profile 中验收。代理保留 Nai 后端的 401、404、409、422 等业务状态，网络错误返回 502。
