from bot.translation.google import GoogleTranslator


class TranslationService:
    def __init__(self):
        self.google = GoogleTranslator()

    async def translate(
        self,
        text: str,
        source: str,
        target: str
    ) -> str:
        return await self.google.translate(
            text=text,
            source=source,
            target=target
        )