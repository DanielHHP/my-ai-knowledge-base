---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

## 使用场景

- 需要获取 GitHub Trending 上的热门开源项目
- 需要从热门项目中筛选出 AI/LLM/Agent 领域的技术动态
- 需要将采集结果结构化存储为知识条目

## 执行步骤

### 1. 搜索热门仓库

调用 GitHub API `https://api.github.com/search/repositories` 或 WebFetch GitHub Trending 页面，获取当日热门仓库列表。使用 `stars:>100 pushed:>2024-01-01 sort:stars` 等查询参数。

### 2. 提取信息

从每个仓库的 API 响应或页面中提取：`name`（全名如 `openai/whisper`）、`url`、`description`、`stars`、`language`、`topics`。

### 3. 过滤

- **纳入**: 与 AI、LLM、Agent、机器学习、深度学习、大模型、RAG、多模态、向量数据库、Prompt Engineering 等相关的项目
- **排除**: Awesome 列表类仓库（检测 topics 含 `awesome` 或 description 以 `Awesome`/`awesome` 开头）、非技术类项目、 Stars < 50 的项目

### 4. 去重

- 基于 `name`（owner/repo）去重，确保同一仓库不重复出现
- 如果运行时已有同日的输出文件，先读取历史列表合并去重

### 5. 撰写中文摘要

每个条目撰写 80-150 字的中文摘要，公式为：

> **项目名 + 做什么 + 为什么值得关注**

示例：
> **openai/whisper**: OpenAI 开源的通用语音识别模型，支持多语种转写和翻译，准确率接近人类水平，极大地降低了语音应用开发门槛。

### 6. 排序取 Top 15

按 `stars` 降序排列，取前 15 个条目。

### 7. 输出 JSON

将结果写入 `knowledge/raw/github-trending-YYYY-MM-DD.json`（以采集日 UTC 日期命名）。

## 注意事项

- 遵循 GitHub API Rate Limit（未认证 60 req/h，认证后 5000 req/h）
- 若使用 WebFetch 爬取页面，需设置 `User-Agent` 避免 403
- 每日 UTC 00:00 后执行，确保获取最新 Trending
- 摘要必须为中文，禁止机器直接翻译英文描述
- 确保输出目录 `knowledge/raw/` 存在，不存在则自动创建

## 输出格式

```json
{
  "source": "github",
  "skill": "github-trending",
  "collected_at": "2025-04-17T00:00:00Z",
  "items": [
    {
      "name": "openai/whisper",
      "url": "https://github.com/openai/whisper",
      "summary": "OpenAI 开源的通用语音识别模型，支持多语种转写和翻译，准确率接近人类水平，极大地降低了语音应用开发门槛。",
      "stars": 75000,
      "language": "Python",
      "topics": ["speech-recognition", "deep-learning", "openai"]
    }
  ]
}
```
