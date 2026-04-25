# Analyzer: AI 分析标注

## What to build

完善 Analyzer Agent，读取 Collector 产出的 raw JSON，通过 LLM(DeepSeek) 对每条内容进行中文摘要、亮点提炼、质量评分和标签建议。包括 LLM 错误处理、成本控制、输入校验。

## Acceptance criteria

- [ ] 从 `knowledge/raw/github-trending-YYYY-MM-DD.json` 读取最新数据
- [ ] 每条生成 100-200 字中文摘要，概括核心技术与价值
- [ ] 提炼 1-3 个具体亮点/关键突破
- [ ] 按 1-10 评分标准打分（9-10 改变格局 / 7-8 直接帮助 / 5-6 值得了解 / 1-4 可略过）
- [ ] 建议 3-5 个标签（避免 `ai`、`tech` 等宽泛标签）
- [ ] 输出结构化 JSON 数组到 stdout，字段继承 Collector 并新增 summary/highlights/score/tags
- [ ] LLM API 错误自动重试最多 3 次，超出后跳过该条目并记录
- [ ] 单日 token 消耗不超过 $0.5 预算
- [ ] 输入数据为空或格式错误时优雅报错，不崩溃

## References

- Agent 定义: `.opencode/agents/analyzer.md`
- 依赖 Collector 输出: `knowledge/raw/github-trending-YYYY-MM-DD.json`

## Blocked by

- Blocked by #1 Collector: GitHub Trending 原始数据采集
