# Gemini 同供应商备用模型

## 行为与请求预算

主模型仍为 `gemini-3.6-flash`。新增单个可选备用模型 `AI_FALLBACK_MODEL`，推荐 `gemini-3.5-flash-lite`。**默认留空，不自动开启**，避免尚未核实项目权限或计费时增加模型使用。

启用不同于主模型的备用模型后：

1. 主模型请求一次；遇到限流、连接/超时或服务端错误，等待 60 秒重试一次。
2. 第二次仍为上述瞬时故障，立即切换备用模型。
3. 备用模型最多请求两次，中间等待 60 秒。仍失败则向上抛出最后的错误，错误链保留主模型失败，运行按现有流程发送一次失败通知。

总预算为 **最多 4 次请求**，不是每个模型各重试 4 次；SDK 内部重试保持关闭。默认 180 秒请求超时下名义预算 `4 × 180 + 2 × 60 = 840` 秒（14 分钟），仍受工作流 60 分钟硬超时限制。HTTP 超时按网络阶段/读取无活动时间计时，14 分钟不是严格墙钟上限。

未设置、空白或与主模型相同的备用模型继续使用原有 4 次主模型请求及 60/300/900 秒等待，见[延迟恢复说明](delayed-ai-recovery.md)。相同模型不会被当作第二个独立重试预算。

## 安全边界

- 只切换模型名，复用同一个 Google OpenAI 兼容端点、密钥、客户端、新闻、上期概要、日期、提示词和最大输出 token 限制；不启用 OpenRouter 或其他供应商。
- 启用备用时要求端点为 `https://generativelanguage.googleapis.com/v1beta/openai/`，主备都为单个 Gemini 模型 ID；错误配置在创建客户端前失败。
- 400/401/403/404 等参数、身份或权限错误不重试、不切换备用。无 choices、空内容或无效正文也直接失败，不通过切换模型绕过内容拦截。
- Notion 发布及 Server酱推送不在模型重试循环内；生成成功后只进入一次发布，全部失败则不发布。发布失败也不会重新生成或再次发布。
- 保留现有工作流串行锁、自动运行当日守卫及 Notion 当日页面检查。没有改变既有 Notion 写入响应丢失或部分页面写入失败的边界。
- 日志记录尝试的主/备模型与错误类型，便于区分恢复路径；不记录密钥。没有增加搜索 grounding、新凭据、计费设置或付费服务。

## 启用前核验

1. 在 [Google AI Studio](https://aistudio.google.com/) 确认 GitHub Actions 所用密钥所属项目。只需要项目名称/ID、项目层级和模型额度，不要把密钥贴入日志、issue 或 PR。
2. 在该项目的 Rate limits 页面确认 `Gemini 3.5 Flash Lite` 可用、额度非零，以及项目是 Free 还是 Paid tier。公开定价表列出免费层，不代表任意现有密钥都免计费；同账户不同项目也可能使用不同层级。
3. 如果是付费项目或需要启用计费，先确认预算和费用，再启用。没有核验时保持 `AI_FALLBACK_MODEL` 为空。
4. 经确认后，在仓库 Settings → Secrets and variables → Actions → Variables 设置非敏感变量 `AI_FALLBACK_MODEL=gemini-3.5-flash-lite`；本地在 `.env` 设置同名变量。现有 API key 不需要改变。
5. 合并与生产验证另行授权。单元测试不会实际调用模型、写 Notion 或发送推送；通过测试不代表已验证真实模型输出质量。首次获准生产验证时检查实际使用模型、生成内容和单次发布结果。

回滚时清空或删除 `AI_FALLBACK_MODEL`，即可恢复原有单模型延迟重试；无需更换凭据。

## 模型与费用依据（2026-10-16 核验）

- [Gemini 3.5 Flash-Lite 模型页](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)：稳定文本模型 ID 为 `gemini-3.5-flash-lite`。[弃用说明](https://ai.google.dev/gemini-api/docs/deprecations/)目前未公布该模型关闭日期。
- [Google OpenAI 兼容接口](https://ai.google.dev/gemini-api/docs/openai)：沿用现有 Chat Completions 集成。模型公开能力与兼容文档支持此选择，具体项目权限仍须单独确认。
- [官方定价](https://ai.google.dev/gemini-api/docs/pricing)：标准付费层输入 $0.30 / 百万 token、输出（含 thinking）$2.50 / 百万 token；免费层公开列为免费。实际收费取决于密钥所属项目的层级，本文不把公开免费层当作账户费用承诺。
- [迁移说明](https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.6)：`gemini-3.6-flash` 和 `gemini-3.5-flash-lite` 已弃用并忽略 temperature/top_p/top_k。此补丁仅对这两个官方端点模型省略已有 temperature 参数，其他模型仍保留配置。这不是此前 503 高负载错误的根因。
- [限额说明](https://ai.google.dev/gemini-api/docs/rate-limits)：不同模型/项目/层级配额不同；备用模型可帮助模型级高负载，不能保证解决项目级或全服务故障。
