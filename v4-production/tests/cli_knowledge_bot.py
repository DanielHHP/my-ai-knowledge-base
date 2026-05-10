from bot.knowledge_bot import KnowledgeBot

if __name__ == "__main__":
    # CLI 交互模式
    bot = KnowledgeBot()
    while True:
        text = input("你：").strip()
        if text.lower() in ("quit", "exit"):
            break
        print(f"助手：{bot.handle_message('cli-user', text)}")