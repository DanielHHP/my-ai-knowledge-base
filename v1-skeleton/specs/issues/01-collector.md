# Collector: GitHub Trending 原始数据采集

## What to build

完善 Collector Agent，从 GitHub Trending 抓取 Top 50 项目、过滤 AI/LLM/Agent 领域条目、写入 `knowledge/raw/`。包括采集超时控制、重试机制、输出格式规范。

## Acceptance criteria

- [ ] 通过 WebFetch 抓取 GitHub Trending 总榜 Top 50（或当日实际可见数量）
- [ ] 根据 topics/name/description 过滤出 AI/LLM/Agent 相关项目
- [ ] 每条提取：title, url, source("github"), popularity(stars), summary(50-100字中文), metadata(语言/作者/主题)
- [ ] 按热度降序排序
- [ ] 写入 `knowledge/raw/github-trending-YYYY-MM-DD.json`，JSON 合法且字段完整
- [ ] 条目数量 >= 15
- [ ] 网络请求设置 30 秒超时，连接超时类错误自动重试最多 3 次
- [ ] 所有数据来自真实抓取，不 AI 幻觉补充

## References

- Agent 定义: `.opencode/agents/collector.md`
- 输出路径: `knowledge/raw/github-trending-YYYY-MM-DD.json`
- 示例数据: `knowledge/raw/github-trending-2026-04-24.json`

## Blocked by

None - can start immediately
