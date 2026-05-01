import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from pipeline.model_client import quick_chat

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "articles"
INDEX_PATH = KNOWLEDGE_DIR / "index.json"

INTENT_KEYWORDS = {
    "github_search": [
        "github", "仓库", "项目", "开源", "repository", "repo",
        "star", "trending", "代码库", "git",
    ],
    "knowledge_query": [
        "知识库", "文章", "知识", "knowledge", "article",
        "条目", "技术动态", "资讯", "know",
    ],
}


def chat(prompt: str, system_prompt: str | None = None) -> tuple[str, object]:
    resp = quick_chat(prompt, system_prompt=system_prompt)
    return resp.content, resp.usage


def chat_json(prompt: str, system_prompt: str | None = None) -> dict:
    sys_prompt = (
        (system_prompt or "")
        + "\n\nYou MUST respond with valid JSON only. "
        "No markdown fences, no explanation."
    )
    resp = quick_chat(prompt, system_prompt=sys_prompt)
    return json.loads(resp.content)


def _keyword_classify(query: str) -> str | None:
    q_lower = query.lower()
    matched = []
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in q_lower:
                matched.append(intent)
                break
    if len(matched) == 1:
        return matched[0]
    return None


def _llm_classify(query: str) -> str:
    system_prompt = (
        "Classify the user's query into one of these intents:\n"
        "- github_search: searching for GitHub repositories, "
        "open source projects\n"
        "- knowledge_query: querying local knowledge base articles\n"
        "- general_chat: general conversation, other topics\n\n"
        "Respond with ONLY the intent name, no other text."
    )
    text, _ = chat(query, system_prompt=system_prompt)
    text = text.strip().lower()
    for intent in ("github_search", "knowledge_query", "general_chat"):
        if intent in text:
            return intent
    return "general_chat"


def classify_intent(query: str) -> str:
    intent = _keyword_classify(query)
    if intent:
        return intent
    return _llm_classify(query)


def handle_github_search(query: str) -> str:
    encoded = urllib.parse.quote(query)
    url = f"https://api.github.com/search/repositories?q={encoded}&per_page=5&sort=stars&order=desc"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "MyAIKnowledgeBase/1.0",
        },
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    items = data.get("items", [])
    if not items:
        return f"GitHub 未找到与「{query}」相关的仓库。"
    lines = [f"找到 {data['total_count']} 个结果，展示前 {len(items)} 个："]
    for repo in items:
        name = repo["full_name"]
        desc = repo.get("description") or "无描述"
        stars = repo["stargazers_count"]
        repo_url = repo["html_url"]
        lang = repo.get("language") or ""
        lang_tag = f" [{lang}]" if lang else ""
        lines.append(f"- [{name}]({repo_url}){lang_tag} ⭐{stars}")
        if desc:
            lines.append(f"  {desc}")
    return "\n".join(lines)


def handle_knowledge_query(query: str) -> str:
    if INDEX_PATH.exists():
        with open(INDEX_PATH) as f:
            articles = json.load(f)
    else:
        articles = []
        for fpath in sorted(KNOWLEDGE_DIR.glob("*.json")):
            if fpath.name == "index.json":
                continue
            with open(fpath) as f:
                articles.append(json.load(f))
    q_lower = query.lower()
    results = []
    for art in articles:
        title = art.get("title", "")
        summary = art.get("summary", "")
        tags = art.get("tags", [])
        if (q_lower in title.lower()
                or q_lower in summary.lower()
                or any(q_lower in t.lower() for t in tags)):
            results.append(art)
    if not results:
        return f"知识库中未找到与「{query}」相关的条目。"
    lines = [f"找到 {len(results)} 条相关条目："]
    for art in results[:5]:
        snippet = (art.get("summary") or "")[:100]
        tag_str = ", ".join(art.get("tags", [])[:3])
        lines.append(
            f"- [{art['title']}]({art.get('source_url', '')}) "
            f"[{art.get('category', '')}] #{tag_str}"
        )
        if snippet:
            lines.append(f"  {snippet}")
    return "\n".join(lines)


def handle_general_chat(query: str) -> str:
    text, _ = chat(query)
    return text


def route(query: str) -> str:
    intent = classify_intent(query)
    print(f"[Router] intent={intent}")
    if intent == "github_search":
        return handle_github_search(query)
    elif intent == "knowledge_query":
        return handle_knowledge_query(query)
    else:
        return handle_general_chat(query)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
    else:
        q = input("Enter your query: ")
    result = route(q)
    print(result)
