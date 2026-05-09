---
name: tech-summary
description: 当需要对采集的技术内容进行深度分析总结时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

## 使用场景

- 需要对 GitHub Trending / Hacker News 采集的原始数据进行深度分析
- 需要为每个项目生成摘要、技术亮点和评分，辅助判断是否值得关注
- 需要从批量项目中提炼技术趋势和共同主题

## 执行步骤

### 1. 读取最新采集文件

读取 `knowledge/raw/` 目录下最近一个工作日的 JSON 文件（格式如 `github-trending-YYYY-MM-DD.json`）。

使用 Glob 匹配 `knowledge/raw/github-trending-*.json` 和 `knowledge/raw/hackernews-*.json`，按文件名日期降序取最新的文件。

### 2. 逐条深度分析

对每个条目依次进行以下分析：

| 分析维度 | 要求 | 说明 |
|----------|------|------|
| **摘要** | ≤50 字 | 精炼概括核心内容，避免与原始描述重复 |
| **技术亮点** | 2-3 个 | 用事实说话，援引具体数字、架构特性、性能指标等 |
| **评分** | 1-10 | 见下方评分标准，附简短理由 |
| **标签** | 3-5 个 | 建议补充分类标签，中英文均可 |

**评分标准**：

| 分数 | 含义 | 典型特征 |
|------|------|----------|
| 9-10 | 改变格局 | 里程碑式工作，可能重塑技术范式 |
| 7-8 | 直接有帮助 | 生产可用，解决真实痛点 |
| 5-6 | 值得了解 | 有亮点但成熟度有限，值得跟踪 |
| 1-4 | 可略过 | 重复造轮子、噱头为主、维护停滞 |

### 3. 趋势发现

在所有条目分析完成后，总结当日趋势：

- **共同主题**: 当天项目集中关注的技术方向（如 Agent 框架、多模态推理、AI 编程工具等），列出 2-4 个
- **新概念**: 首次出现的技术名词或方法，简要说明
- **一句话总结**: 用一句话概括当天技术动态的整体面貌

### 4. 输出分析结果 JSON

将结果写入 `knowledge/articles/YYYY-MM-DD.json`（以分析日 UTC 日期命名）。

若输出目录 `knowledge/articles/` 不存在，自动创建。

## 注意事项

- 约束：15 个项目中 9-10 分的不得超过 2 个，保持评价的区分度
- 摘要必须为中文，不超过 50 字
- 技术亮点必须援引事实（数字、架构特点、基准测试结果），禁止空泛评价
- 评分需附理由，不得仅给出数字
- 如果原始数据不足（如描述过于简短），标注 `analysis_note` 说明局限
- 不修改原始数据，分析结果独立输出

## 输出格式

```json
{
  "source": "knowledge/raw/github-trending-2025-04-17.json",
  "skill": "tech-summary",
  "analyzed_at": "2025-04-17T02:00:00Z",
  "total_items": 15,
  "items": [
    {
      "name": "openai/whisper",
      "url": "https://github.com/openai/whisper",
      "summary": "OpenAI 开源语音识别模型，多语种高精度转写。",
      "highlights": [
        "支持 99 种语言， multilingual 能力领先",
        "Large-v3 在 Common Voice 上词错率仅 8.2%",
        "MIT 协议开源，可自由商用和二次开发"
      ],
      "score": 9,
      "score_reason": "开源语音识别事实标准，性能与可用性均达到里程碑水平，极大降低了语音应用开发门槛",
      "tags": ["speech-recognition", "openai", "multilingual", "开源模型"]
    }
  ],
  "trends": {
    "common_themes": [
      "Agent 框架持续涌现，多工具编排能力成为标配"
    ],
    "new_concepts": [
      "MCP (Model Context Protocol): 统一大模型与外部工具交互的开放协议"
    ],
    "one_liner": "Agent 框架与多模态模型仍是本周 AI 开源生态的两大主线。"
  }
}
```
