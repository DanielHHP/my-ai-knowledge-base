# Organizer: 整理归档 + 流水线编排

## What to build

完善 Organizer Agent，接收 Analyzer 的标注结果，执行去重、分类、格式化写入 `knowledge/articles/`。同时负责整体流水线的串行编排、调度触发、配置管理、incident 报告和进度追踪。

## Acceptance criteria

### 整理归档
- [ ] 读取 Analyzer 输出的结构化 JSON（summary/highlights/score/tags）
- [ ] URL 完全匹配 + 标题相似度双重去重，重复条目标记 `duplicate` 并跳过
- [ ] 格式化为标准知识条目 JSON（id, title, source, source_url, summary, highlights, tags, category, score, status, metadata, created_at, updated_at）
- [ ] 自动分类（模型发布 / 工具库 / 论文 / 行业动态 / 教程最佳实践 / 其他）
- [ ] 写入 `knowledge/articles/{date}-{source}-{slug}.json`，命名规范，所有必填字段非空
- [ ] 时间戳使用 UTC ISO 8601，状态限 `draft/published/archived/duplicate`

### 流水线编排
- [ ] 实现 Collector → Analyzer → Organizer 串行执行：前一步成功才运行下一步
- [ ] 创建 `config.yaml`（数据路径、触发时间、日志级别等）
- [ ] 创建 `requirements.txt`（声明 Python 依赖）
- [ ] 单条命令可跑通完整流水线（如 `bash run-pipeline.sh`）

### 错误处理与监控
- [ ] Collector 失败时跳过 Analyzer/Organizer，写 incident 到 `knowledge/incidents/YYYY-MM-DD.md`
- [ ] incident 报告包含：失败阶段、错误信息、时间戳
- [ ] 结构化日志记录每个阶段开始/完成/失败时间
- [ ] 每日执行耗时控制在 < 10 分钟


## References

- Agent 定义: `.opencode/agents/organizer.md`
- 依赖 Analyzer 输出
- 项目愿景: `specs/project-vision.md`（UTC 0:00 触发、$0.5/天、incident 路径）

## Blocked by

- Blocked by #2 Analyzer: AI 分析标注
