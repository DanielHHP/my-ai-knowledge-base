#!/usr/bin/env python3
"""5-dimension quality scoring for knowledge entry JSON files.

Usage:
    python hooks/check_quality.py <json_file> [json_file2 ...]
    python hooks/check_quality.py knowledge/articles/*.json

Exit code: 1 if any file scores grade C, 0 otherwise.
"""

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ──────────────────────── Constants ────────────────────────

SUMMARY_FULL_LENGTH = 50
SUMMARY_BASIC_LENGTH = 20

SCORE_FIELD_MIN = 1
SCORE_FIELD_MAX = 10

GRADE_A_THRESHOLD = 80
GRADE_B_THRESHOLD = 60

MAX_SUMMARY_SCORE = 25.0
MAX_DEPTH_SCORE = 25.0
MAX_FORMAT_SCORE = 20.0
MAX_TAG_SCORE = 15.0
MAX_BUZZWORD_SCORE = 15.0
MAX_TOTAL_SCORE = 100.0

VALID_STATUSES: set[str] = {"draft", "review", "published", "archived"}
URL_PATTERN: re.Pattern = re.compile(r"^https?://\S+")

STANDARD_TAGS: set[str] = {
    "ai", "artificial-intelligence", "machine-learning", "deep-learning",
    "llm", "large-language-model", "language-model", "foundation-model",
    "nlp", "natural-language-processing", "computer-vision", "multimodal",
    "reinforcement-learning", "transfer-learning", "few-shot", "zero-shot",
    "chain-of-thought", "cot", "prompt-engineering", "prompt",
    "function-calling", "tool-use", "tool-calling", "structured-output",
    "embeddings", "vector-database", "vector-search", "semantic-search",
    "fine-tuning", "lora", "qlora", "rlhf", "dpo", "ppo",
    "alignment", "safety", "evaluation", "benchmark",
    "observability", "monitoring", "tracing",
    "deployment", "mlops", "llmops", "pipeline", "orchestration",
    "automation", "workflow", "dev-tools", "cli", "api", "sdk",
    "agent", "ai-agent", "multi-agent", "coding-agent", "agent-framework",
    "rag", "retrieval-augmented-generation",
    "text-to-image", "text-to-speech", "speech-to-text", "asr", "tts",
    "image-generation", "code-generation", "code-completion", "code-review",
    "gpt", "gpt-4", "gpt-4o", "claude", "claude-3", "gemini",
    "llama", "llama-2", "llama-3", "mistral", "mixtral",
    "deepseek", "qwen", "qwen2", "phi", "falcon", "codellama", "yi",
    "openai", "anthropic", "google-ai", "meta-ai", "mistral-ai", "deepseek-ai",
    "huggingface", "replicate", "together-ai", "perplexity", "cohere",
    "langchain", "llamaindex", "haystack", "semantic-kernel",
    "transformers", "diffusers", "sentence-transformers",
    "pytorch", "tensorflow", "jax", "onnx",
    "ollama", "vllm", "tgi", "text-generation-inference",
    "fastapi", "gradio", "streamlit", "jupyter",
    "docker", "kubernetes", "mlflow", "kubeflow",
    "open-webui", "dify", "n8n", "langflow", "flowise",
    "langgraph", "langsmith", "langserve",
    "openclaw", "lobster",
    "python", "python-sdk", "typescript", "javascript", "rust", "go",
    "web-ui", "ui", "ux", "frontend", "backend", "full-stack",
    "open-source", "cross-platform", "local-deployment", "edge-computing",
    "terminal", "chatbot", "ai-assistant", "personal-assistant",
    "skills", "agent-skills", "tool-use",
    "autogpt", "superpowers", "claude-code",
    "大模型", "模型部署", "模型训练", "模型推理", "提示词",
    "个人助手", "工作流", "知识库", "搜索", "对话",
    "自动化", "智能化", "个性化", "实时", "高效",
    "智能体", "智能助手", "数据分析", "数据可视化",
}

BUZZWORDS_CN: list[str] = [
    "赋能", "抓手", "闭环", "打通", "全链路",
    "底层逻辑", "颗粒度", "对齐", "拉通", "沉淀",
    "强大的", "革命性的",
]

BUZZWORDS_EN: list[str] = [
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
]

TECH_KEYWORDS: list[str] = [
    "AI", "LLM", "GPT", "大模型", "模型", "深度学习", "机器学习",
    "神经网络", "transformer", "多模态", "multimodal",
    "agent", "Agent", "RAG", "fine-tuning", "微调",
    "推理", "inference", "embedding", "token",
    "prompt", "RLHF", "alignment",
]


# ──────────────────────── Dataclasses ────────────────────────

@dataclass
class DimensionScore:
    name: str
    score: float
    max_score: float
    reason: str


@dataclass
class QualityReport:
    file_path: str
    dimensions: list[DimensionScore] = field(default_factory=list)
    total_score: float = 0.0
    max_total: float = MAX_TOTAL_SCORE

    @property
    def grade(self) -> str:
        if self.total_score >= GRADE_A_THRESHOLD:
            return "A"
        if self.total_score >= GRADE_B_THRESHOLD:
            return "B"
        return "C"

    def add_dimension(self, name: str, score: float, max_score: float, reason: str) -> None:
        self.dimensions.append(DimensionScore(name, score, max_score, reason))
        self.total_score += score

    def print_report(self) -> None:
        print(f"  File: {self.file_path}")
        print(f"  " + "-" * 50)
        for dim in self.dimensions:
            bar_len = 20
            ratio = dim.score / dim.max_score if dim.max_score > 0 else 0
            filled = int(ratio * bar_len)
            bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
            print(
                f"  {dim.name:<10} {bar} "
                f"{dim.score:>5.1f}/{dim.max_score:<5.1f}  {dim.reason}"
            )
        print(f"  " + "-" * 50)
        print(f"  Total:       {self.total_score:>5.1f}/100.0  Grade: {self.grade}")


# ──────────────────────── Scoring Functions ────────────────────────

def _get_text(entry: dict, field: str, default: str = "") -> str:
    val = entry.get(field)
    return val if isinstance(val, str) else default


def _get_list(entry: dict, field: str) -> list:
    val = entry.get(field)
    return val if isinstance(val, list) else []


def score_summary_quality(entry: dict) -> tuple[float, str]:
    summary = _get_text(entry, "summary")
    if not summary:
        return (0.0, "No summary field")

    length = len(summary)
    if length >= SUMMARY_FULL_LENGTH:
        base = 20.0
        parts = [f"len={length} >= 50"]
    elif length >= SUMMARY_BASIC_LENGTH:
        base = 15.0
        parts = [f"len={length} >= 20"]
    else:
        base = 10.0
        parts = [f"len={length} < 20"]

    found = [kw for kw in TECH_KEYWORDS if kw in summary]
    if found:
        bonus = min(5.0, len(found) * 1.0)
        total = min(MAX_SUMMARY_SCORE, base + bonus)
        parts.append(f"+{bonus:.0f} tech-kw({','.join(found[:3])})")
        return (total, ", ".join(parts))

    return (base, ", ".join(parts))


def score_technical_depth(entry: dict) -> tuple[float, str]:
    score = entry.get("score")
    if score is None:
        return (0.0, "Missing score field")
    if not isinstance(score, (int, float)):
        return (0.0, f"Non-numeric score: {type(score).__name__}")
    if score < SCORE_FIELD_MIN or score > SCORE_FIELD_MAX:
        return (0.0, f"Score {score} out of range [1, 10]")

    mapped = min(MAX_DEPTH_SCORE, score * 2.5)
    return (mapped, f"score={score}/10 -> {mapped:.1f}/25")


def score_format_compliance(entry: dict) -> tuple[float, str]:
    details: list[str] = []
    total = 0.0

    if entry.get("id") and isinstance(entry["id"], str):
        total += 4.0
        details.append("id\u2713")
    else:
        details.append("id\u2717")

    if entry.get("title") and isinstance(entry["title"], str):
        total += 4.0
        details.append("title\u2713")
    else:
        details.append("title\u2717")

    url = entry.get("source_url")
    if url and isinstance(url, str) and URL_PATTERN.match(url):
        total += 4.0
        details.append("url\u2713")
    else:
        details.append("url\u2717")

    status = entry.get("status")
    if status and isinstance(status, str) and status in VALID_STATUSES:
        total += 4.0
        details.append("status\u2713")
    else:
        details.append("status\u2717")

    ts_fields = ["published_at", "created_at", "updated_at"]
    ts_ok = sum(1 for f in ts_fields if entry.get(f) and isinstance(entry[f], str))
    total += (ts_ok / len(ts_fields)) * 4.0
    details.append(f"ts({ts_ok}/3)\u2713" if ts_ok == 3 else f"ts({ts_ok}/3)")

    return (total, ", ".join(details))


def score_tag_precision(entry: dict) -> tuple[float, str]:
    tags = _get_list(entry, "tags")
    tags = [t for t in tags if isinstance(t, str) and t]
    if not tags:
        return (0.0, "No tags")

    known = sum(1 for t in tags if t in STANDARD_TAGS)
    unknown = len(tags) - known

    if len(tags) <= 3:
        base = 12.0
    else:
        base = max(0.0, 12.0 - (len(tags) - 3) * 3.0)

    bonus = min(3.0, known * 1.0)
    penalty = min(base + bonus, unknown * 2.0)
    score = max(0.0, min(MAX_TAG_SCORE, base + bonus - penalty))

    reason = (
        f"{len(tags)} tags ({known} known, {unknown} unknown)"
        if unknown > 0
        else f"{len(tags)} tags (all known)"
    )
    return (score, reason)


def _check_buzzwords_in_text(text: str) -> set[str]:
    found: set[str] = set()
    lower = text.lower()
    for bw in BUZZWORDS_CN:
        if bw in text:
            found.add(bw)
    for bw in BUZZWORDS_EN:
        if bw.lower() in lower:
            found.add(bw)
    return found


def score_buzzword_free(entry: dict) -> tuple[float, str]:
    texts: list[str] = [
        _get_text(entry, "title"),
        _get_text(entry, "summary"),
        _get_text(entry, "score_reason"),
    ]
    highlights = _get_list(entry, "highlights")
    texts.extend(h for h in highlights if isinstance(h, str))

    content = _get_text(entry, "content")
    if content:
        texts.append(content)

    all_found: set[str] = set()
    for t in texts:
        all_found |= _check_buzzwords_in_text(t)

    if not all_found:
        return (MAX_BUZZWORD_SCORE, "No buzzwords detected")

    penalty = min(MAX_BUZZWORD_SCORE, len(all_found) * 5.0)
    score = max(0.0, MAX_BUZZWORD_SCORE - penalty)
    return (
        score,
        f"Found {len(all_found)} buzzword(s): {', '.join(sorted(all_found))}",
    )


# ──────────────────────── Processing ────────────────────────

def score_entry(entry: dict, location: str) -> QualityReport:
    report = QualityReport(file_path=location)

    s, r = score_summary_quality(entry)
    report.add_dimension("\u6458\u8981\u8d28\u91cf", s, MAX_SUMMARY_SCORE, r)

    s, r = score_technical_depth(entry)
    report.add_dimension("\u6280\u672f\u6df1\u5ea6", s, MAX_DEPTH_SCORE, r)

    s, r = score_format_compliance(entry)
    report.add_dimension("\u683c\u5f0f\u89c4\u8303", s, MAX_FORMAT_SCORE, r)

    s, r = score_tag_precision(entry)
    report.add_dimension("\u6807\u7b7e\u7cbe\u5ea6", s, MAX_TAG_SCORE, r)

    s, r = score_buzzword_free(entry)
    report.add_dimension("\u7a7a\u6d1e\u8bcd\u68c0\u6d4b", s, MAX_BUZZWORD_SCORE, r)

    return report


def score_file(file_path: Path) -> list[QualityReport]:
    reports: list[QualityReport] = []
    location = str(file_path)

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        report = QualityReport(file_path=location)
        report.total_score = 0.0
        report.add_dimension("Error", 0.0, MAX_TOTAL_SCORE, str(e))
        return [report]

    if isinstance(data, dict):
        reports.append(score_entry(data, location))
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            reports.append(score_entry(item, f"{location}[{idx}]"))
    else:
        report = QualityReport(file_path=location)
        report.total_score = 0.0
        report.add_dimension("Error", 0.0, MAX_TOTAL_SCORE, "Root must be object or array")
        reports.append(report)

    return reports


def collect_json_files(args: list[str]) -> list[Path]:
    files: list[Path] = []
    for arg in args:
        path = Path(arg)
        if "*" in arg or "?" in arg:
            files.extend(sorted(path.parent.glob(path.name)))
        else:
            if path.exists():
                files.append(path)
            else:
                print(f"Error: file not found: {arg}", file=sys.stderr)
    return files


# ──────────────────────── Main ────────────────────────

def print_summary(all_reports: list[QualityReport]) -> None:
    total = len(all_reports)
    grades = {"A": 0, "B": 0, "C": 0, "E": 0}
    total_score = 0.0

    for report in all_reports:
        if report.dimensions and report.dimensions[0].name == "Error":
            grades["E"] += 1
        else:
            grades[report.grade] += 1
            total_score += report.total_score

    print()
    print("=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"  Files checked:     {total}")
    print(f"  Grade A (>=80):    {grades['A']}")
    print(f"  Grade B (>=60):    {grades['B']}")
    print(f"  Grade C (<60):     {grades['C']}")
    if grades["E"]:
        print(f"  Errors:            {grades['E']}")
    non_error = total - grades["E"]
    if non_error > 0:
        print(f"  Average score:     {total_score / non_error:.1f}/100.0")
    print("=" * 60)


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <json_file> [json_file2 ...]", file=sys.stderr)
        return 1

    files = collect_json_files(sys.argv[1:])
    if not files:
        print("Error: no JSON files to process", file=sys.stderr)
        return 1

    all_reports: list[QualityReport] = []

    for i, file_path in enumerate(files):
        pct = (i + 1) / len(files) * 100
        bar_len = 30
        filled = int((i + 1) / len(files) * bar_len)
        bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
        sys.stdout.write(
            f"\r  Processing: [{bar}] {pct:>5.1f}% ({i+1}/{len(files)})  "
        )
        sys.stdout.flush()

        reports = score_file(file_path)
        all_reports.extend(reports)

    print("\n")

    for report in all_reports:
        report.print_report()
        print()

    print_summary(all_reports)

    has_c = any(
        r.grade == "C"
        for r in all_reports
        if not (r.dimensions and r.dimensions[0].name == "Error")
    )
    return 1 if has_c else 0


if __name__ == "__main__":
    sys.exit(main())
