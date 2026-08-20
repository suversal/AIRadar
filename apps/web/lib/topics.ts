// Mirrors apps/api/app/services/topics.py 的注册表(id → 中文名)。
// 只镜像 id 与名字:描述、计数等展示数据由 API 返回,这里只服务不便
// 请求 API 的场合——/all 的筛选 chip、sitemap、metadata 兜底。
// 新增/改名主题时与后端注册表同步改。

export const TOPIC_NAMES: Record<string, string> = {
  // entities · 公司与模型
  openai: "OpenAI / GPT",
  anthropic: "Anthropic / Claude",
  google: "Google / Gemini",
  deepseek: "DeepSeek",
  qwen: "通义 Qwen / 阿里",
  kimi: "Kimi / 月之暗面",
  zhipu: "智谱 GLM",
  minimax: "MiniMax",
  bytedance: "字节 / 豆包",
  tencent: "腾讯 / 混元",
  baidu: "百度 / 文心",
  xai: "xAI / Grok",
  meta: "Meta / Llama",
  microsoft: "Microsoft / Copilot",
  nvidia: "NVIDIA 英伟达",
  huggingface: "Hugging Face",
  cursor: "Cursor",
  amazon: "Amazon / AWS",
  apple: "Apple 苹果",
  huawei: "华为 / 昇腾",
  openrouter: "OpenRouter",
  perplexity: "Perplexity",
  mistral: "Mistral",
  iflytek: "讯飞 星火",
  stepfun: "阶跃星辰",
  midjourney: "Midjourney",
  // directions · 技术方向
  agents: "Agent 智能体",
  coding: "AI 编码",
  reasoning: "推理能力",
  multimodal: "多模态",
  voice: "语音与音频",
  embodied: "机器人具身",
  opensource: "开源生态",
  safety: "安全对齐",
};

// 旧版(四组时代)的主题 id → 新 id,与后端 _LEGACY_ALIASES 一致。
// 旧链接的 chip 文案和详情页跳转都靠它兜底。
const LEGACY_ALIASES: Record<string, string> = {
  gpt: "openai",
  chatgpt: "openai",
  sora: "openai",
  claude: "anthropic",
  claude_code: "anthropic",
  gemini: "google",
  llama: "meta",
  grok: "xai",
  copilot: "microsoft",
  alibaba: "qwen",
  robotics: "embodied",
};

export const TOPIC_SLUGS = Object.keys(TOPIC_NAMES);

export function resolveTopicId(id: string): string {
  return LEGACY_ALIASES[id] ?? id;
}

/** 筛选 chip 等处的展示名。未知 id 原样返回——比空字符串诚实。 */
export function topicLabel(id: string): string {
  return TOPIC_NAMES[resolveTopicId(id)] ?? id;
}
