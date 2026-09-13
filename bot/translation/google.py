from googletrans import Translator


class GoogleTranslator:
    def __init__(self):
        self.translator = Translator()

    async def translate(
        self,
        text: str,
        source: str,
        target: str
    ) -> str:
        if not text.strip():
            return text

        if source == target:
            return text

        result = await self.translator.translate(
            text,
            src=source,
            dest=target
        )

        return result.text

# from googletrans import Translator


# class GoogleTranslator:
#     def __init__(self):
#         self.translator = Translator()

#     async def translate(
#         self,
#         text: str,
#         source: str,
#         target: str
#     ) -> str:
#         if not text.strip():
#             return text

#         if source == target:
#             return text

#         print(f"[GoogleTrans] {source} -> {target}")
#         print(f"[GoogleTrans] 요청: {text}")

#         result = await self.translator.translate(
#             text,
#             src=source,
#             dest=target
#         )

#         print(f"[GoogleTrans] 결과: {result}")
#         print(f"[GoogleTrans] 결과 text: {result.text}")

#         return result.text