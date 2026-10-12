# 桌面壳四期方案(含 P1 spike 定义)——出稿待用户看板

- 作者:pm;状态:**初稿,候用户看稿后喊开工**(用户裁定:先看稿后动工,已撤先行令);依据:decision-form-factor.md v2.1 §七/§八+backend/frontend 两注记
- 定案:壳轴 GO——Tauri v2 壳+embedded Python sidecar,单机形态优先,分发对标 DeepWrite Releases

## 总览

| 期 | 内容 | 量级 | 出口判据 |
|---|---|---|---|
| P1 | 壳 MVP spike(六件验证) | 1 周小步窗口 | 六件全过进 P2;静态导出撞墙→双 sidecar 备胎(+2-3 人日);spawn/端口不可行→回桌重评 |
| P2 | 数据目录迁移+首启引导(含 key) | 3-5 人日 | 老书数据无损迁移+新装首启可写 |
| P3 | 更新通道+CI 签名公证 | 4-7 人日 | 双平台安装包+自动更新+签名过验 |
| P4 | .md 文件关联+导入管线 | 1.5-2 人日 | 候真源单向导出节奏,止步对话框+预览层 |

单机全案 16-25 人日(backend 8-13+frontend 8-12);混合形态(壳只包前端连云端)为远期备选,frontend 侧届时 5-8 人日。

## P1 spike 定义(先行验证,一周小步)

目标:用最小工程验证 B 档技术底座,任一硬墙立即回桌。六件:

1. **静态导出实证**:`output:'export'`+`/novels/[id]`×2 迁 workspace 既有 query 模式+全路由构建走查(0.5-1 人日出结果,先做)。
2. **Tauri 壳初始化**:窗口/菜单/深链最小集;**http 资产服务形态**(http://localhost:<port>,避免 tauri:// origin 跨域坑)。
3. **壳 spawn embedded Python**:python-build-standalone 解释器+venv 随包,壳拉起 `python -m uvicorn`。
4. **动态端口**:端口由壳分配传入 sidecar(固定 8000 必撞)。
5. **运行时基址覆盖**:`window.__NAI_API_BASE__` 或 mutator 运行时覆盖点(解构建期 env vs 动态端口错配)。
6. **健康检查**:/api/health 轮询+崩溃重启+退出清理/孤儿进程。

## P2 数据目录迁移+首启引导

- DATABASE_URL/Chroma persist 相对路径→用户目录(AppData/Application Support)+.env 双路径改造+首次迁移引导(backend 1-2 人日)。
- key 桌面分发电产品配置面:key 不内置;最小=首启引导写 env(1 人日);完整=设置 UI+连通校验(1-2 人日);SECRET_KEY 本机生成一次;桌面 key 存钥匙串为安全边界决策点(backend 1-3 人日合计)。

## P3 更新通道+CI 签名公证

- 壳侧 tauri-plugin-updater+minisign 签名+静态清单(GitHub Releases 可挂)1-2 人日。
- CI 打包 dmg/exe+签名公证:macOS notarization、Windows 代码签名证书(**年费流程成本**,与 backend 分发工程合并排)3-5 人日。
- **backend sidecar 随版本走**(Python 环境+SQLite 迁移+数据面)方案由 backend 补报后再定价。

## P4 .md 关联+导入管线(缓)

Tauri 声明式配置半天+导入管线 1-2 人日;**与真源文件化安全机制强耦合,候单向导出落地节奏,止步对话框+预览层**。

## 风险 top5(两注记汇总)

动态路由导出不可枚举→query 化/构建期 env vs 动态端口→运行时基址/tauri:// origin CORS→http 资产形态/.md 导入与真源机制耦合顺序/Win 签名+notarization 流程成本。备胎:双 sidecar(壳内 next start)+2-3 人日,仅静态导出撞墙启用。
