import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.knowledge_bot import (
    Intent,
    KnowledgeBot,
    KnowledgeSearchEngine,
    _format_results,
    recognize_intent,
)


def test_search():
    # 测试意图识别
    tests = [
        ("/search MCP", Intent.SEARCH, "MCP"),
        ("/today", Intent.TODAY, ""),
        ("/top 5", Intent.TOP, "5"),
        ("搜索 Agent 文章", Intent.SEARCH, "Agent 文章"),
        ("今天有什么新内容", Intent.TODAY, "有什么新内容"),
        ("随便聊聊", Intent.UNKNOWN, "随便聊聊"),
    ]

    print("=== 意图识别测试 ===")
    for text, expected_intent, expected_args in tests:
        intent, args = recognize_intent(text)
        ok = intent == expected_intent and args == expected_args
        status = "PASS" if ok else "FAIL"
        print(f'  [{status}] "{text}"')
        print(f'          → intent={intent.value}  args={args!r}')
        if not ok:
            print(
                f'          expected intent={expected_intent.value}  args={expected_args!r}'
            )

    # 测试 Bot 完整流程
    bot = KnowledgeBot()
    print()
    print("=== Bot 消息处理测试 ===")
    for text in ["/help", "/search Agent", "/today", "搜索 MCP 协议"]:
        reply = bot.handle_message("test-user", text)
        print(f"  输入: {text}")
        print(f"  回复: {reply[:120]}{'...' if len(reply) > 120 else ''}")
        print()


def test_command():
    # 1. 意图识别
    print("--- 意图识别 ---")
    for q in ["/search agent", "/today", "/top 3", "/help", "搜一下 RAG"]:
        intent, payload = recognize_intent(q)
        print(f"  {q!r:25s} → {intent.name:18s} payload={payload!r}")

    # 2. 搜索
    print()
    print("--- /search agent (top 3) ---")
    knowledge_dir = (
        Path(__file__).resolve().parent.parent / "knowledge" / "articles"
    )
    engine = KnowledgeSearchEngine(knowledge_dir)
    results = engine.search(keywords="agent", limit=3)
    print(_format_results(results, header="搜索「agent」的结果"))


if __name__ == "__main__":
    test_command()
    print("===================")
    test_search()
