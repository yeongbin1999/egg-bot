import asyncio

from bot.translation.service import TranslationService


async def main():
    service = TranslationService()

    tests = [
        ("안녕하세요. 좋은 하루입니다.", "ko", "en"),
        ("안녕하세요. 좋은 하루입니다.", "ko", "ja"),
        ("안녕하세요. 좋은 하루입니다.", "ko", "zh-TW"),
    ]

    for text, source, target in tests:
        result = await service.translate(
            text=text,
            source=source,
            target=target
        )

        print(
            f"[{source} -> {target}]"
        )
        print(
            f"원문: {text}"
        )
        print(
            f"번역: {result}"
        )
        print()


if __name__ == "__main__":
    asyncio.run(main())