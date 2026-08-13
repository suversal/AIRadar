# AI 调用降本：从 DeepSeek 切到百炼 qwen

2026-08-13。起点是每天约 6 元 API 费用，系统尚未对外推出，这个量级不合理。
分两步做完，全部已上线。

## 结论速查

| | 改动 | 实测效果 |
|---|---|---|
| 第一步 | 关闭思考模式 | 省 46% |
| 第二步 | 全量切 qwen3.7-flash | 每次调用再省 66% |
| 观测 | `ai_usage_stats` 埋点 + 报表脚本 | 之前完全不知道钱花在哪 |

单轮真实账单：DeepSeek ¥0.1094 → qwen ¥0.0276。

查看方式：

```bash
python scripts/ai_usage_report.py            # 最近 7 天
python scripts/ai_usage_report.py --by-run   # 按刷新轮次拆开
```

或 `GET /api/admin/ai-usage?days=7`，返回里的 `current_provider` 是**当前进程
实际生效**的 provider（改完 `.env` 不重启不会生效，这个字段用来确认）。

## 第一步：关闭思考模式

DeepSeek 默认 `thinking=enabled` + `reasoning_effort=high`，而思考产生的
`reasoning_tokens` **全部按输出价计费**——输出价是缓存未命中输入价的 2 倍、
缓存命中价的 100 倍。代码里从来没传过这两个参数，等于一直跑在最贵档。

真正需要推理的调用几乎没有：预筛只要一个布尔值，同事件校验是二选一，翻译
更不需要"想一想"。所以现在只有打分和周月报综述会思考：

- `prefilter` / `verify_same_event` / `translate_paragraphs` → 思考关闭
- `score_article` → 受 `QWEN_THINKING_BUDGET`（qwen）或
  `DEEPSEEK_SCORING_REASONING_EFFORT`（DeepSeek）控制
- `summarize_period` → 保留完整思考，它每周/每月才跑一次，且是唯一真正需要
  跨几十条事件做综合的任务

## 第二步：切到百炼 qwen3.7-flash

### 为什么是它

按输出价排序（元/百万 token，成本 90% 以上在输出）：

| 平台 / 模型 | 输入 | 缓存命中 | 输出 |
|---|---|---|---|
| 智谱 GLM-4.7-Flash | 免费 | 免费 | 免费 |
| **阿里 qwen3.7-flash** | 0.2 | 0.02 | **0.8** |
| 硅基流动托管 DeepSeek-V4-Flash | 0.5 | 免费 | 1.0 |
| 火山 doubao-seed-1.6-flash | 0.15 | 0.03 | 1.5 |
| DeepSeek v4-flash（原用） | 1 | 0.02 | 2 |

GLM-4.7-Flash 免费但速率限制没查到文档，流水线是 20 并发、每天约 700 次调用，
风险未知；qwen 是付费选项里最划算的，且有 100 万 token 免费额度可先试。

### 三个踩过的坑

**1. `reasoning_effort` 对 qwen3.7 静默忽略。** 它只对 glm-5.x / deepseek-v4 /
kimi-k3 生效。照搬 DeepSeek 的参数不会报错，但模型跑在满思考强度上——第一次
测出来比 DeepSeek 还贵 53%。qwen 要用 `enable_thinking` + `thinking_budget`。
`QwenProvider` 里有测试锁住"绝不发送 DeepSeek 形状的思考字段"。

**2. 百炼的缓存不是自动的。** 隐式缓存实测 0 命中（文档自己也说"命中率不
确定"），必须在 system message 上打 `cache_control: {"type": "ephemeral"}`
显式标记，且前缀要 ≥1024 token 才建得起缓存块。打上之后输入缓存命中率
达到 67%（理论上限，剩下的是每篇不同的正文）。

预筛的 system prompt 只有 278 token，够不到门槛，所以它在 qwen 上享受不到
缓存——这是预筛换过去省不到钱的原因，不是 qwen 差。

**3. `max_tokens` 语义相反。** 阿里的 `max_tokens` **不含**思维链，DeepSeek 的
**包含**。同名反义，会导致截断行为不一致。

### 为什么用 OpenAI 兼容端点而不是 DashScope 原生

原生接口功能更全，但我们需要的三件事——关思考、显式缓存、JSON 输出——兼容
模式全部实测生效，`thinking_budget` 也精确可控（设 50 就正好烧 50 个思考
token）。原生多出来的只是两个用不上的 usage 字段（`cache_type`、
`ephemeral_5m_input_tokens`）。

而代价是实打实的：响应 content 是 list 而非字符串、usage 字段名不同
（`input_tokens` vs `prompt_tokens`）、请求体两层嵌套、路径按模态分
（qwen3.7-flash 走 `multimodal-generation`，qwen-plus 走 `text-generation`）、
和现有三个 OpenAI 格式的 provider 割裂、且绑死阿里。

结论：兼容模式。将来真要用阿里独有能力（联网搜索、代码解释器）时再单独接。

## 代码结构

`_OpenAICompatibleProvider` 基类持有全部流水线逻辑，两家只声明各自方言：

- `_apply_thinking(payload, mode)` —— 思考控制字段（三档：off / scoring / full）
- `_prepare_messages(messages)` —— 缓存标记（只有 qwen 需要）
- `_vendor_payload()` —— 厂商特有字段（DeepSeek 的 `user_id`）

DeepSeek 配置完整保留，`AI_PROVIDER=deepseek` 即可回滚。

## ai_focus 判定的调整

`tangential` 在分类层就直接淘汰（不进入打分），所以这一个字段的影响比后面
三个维度加起来还大。原 rubric 的自检法是"把 AI 字眼去掉后文章能否独立成立"，
它对拦截车企 OTA 通稿很有效，但对 **AI 工具链的使用与排障**类内容会误伤：
"codex 首包卡死排查"去掉 AI 之后根本不存在，却被判成了 tangential。

补了一条豁免：讨论对象**本身就是** AI 产品/工具（Codex、Claude、Cursor、
某模型 API）且内容是使用、配置、排障、实测时，判 primary/contributing；
但如果主体是通用工程实践（代码审查流程、分支管理），AI 只是触发它的背景
原因，仍判 tangential。后半句是刻意留的闸门，否则"因为 AI 生成代码太大所以
要拆 PR"这类也会被放进来。

改后 qwen 的 tangential 从 9/64 降到 3/64，与 DeepSeek 持平，三个定性用例
各跑两次全部稳定通过。

## 验证方法上的两个教训

**质量对比必须先测噪声基线。** 同一配置、同一批文章跑两遍，结果并不相同：
DeepSeek 的 category 自比只有 77–84%，`ai_focus` 自比 84%。不测这个基线，
就会把随机抖动当成质量退化——跨平台 category 一致率 64% 看着吓人，但正确的
判据是"与库内历史标签的一致率"，DeepSeek 83%、qwen 80%，只差 2 篇。而 qwen
自比 90%，稳定性反而更好。

**测缓存成本必须每个配置各跑两轮，只取第二轮。** 生产一直用旧配置，它的
前缀缓存是热的；新配置第一次跑全部 cache miss。不控制这一点，第一次测出来
只省 4.4%，实际稳态是 55%。

另外，压测数字不等于生产数字：DeepSeek 预筛的缓存命中率在压测里是 88%，
真实生产只有 19%（一轮刷新里这些调用是分散的，缓存来不及热就过期了）。这
直接推翻了"预筛留在 DeepSeek 更划算"的判断——真实场景下换过去能省 63%。

## 相关配置

见 README「Optional」一节：`ALI_API_KEY`、`ALI_BASE_URL`、`QWEN_MODEL`、
`QWEN_MAX_TOKENS`、`QWEN_THINKING_BUDGET`。

业务空间专属域名（`https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/...`）
比公共 dashscope 域名稳定性更好，官方推荐迁移。

## 尚未做

- **本地零成本预筛**：IT之家和 36氪 占抓取量 77%，其中 85% 是非 AI 内容，
  每天约 330 次预筛纯属白烧。项目里已有本地 bge-small-zh 模型可做零成本粗筛。
  单次调用变便宜后这件事收益变小，但量还在。
- **避峰调度**：DeepSeek 2026-08-16 起改峰谷计价（北京 9-12、14-18 为高峰）。
  已不用 DeepSeek，此项作废，仅在回滚时需要考虑。
