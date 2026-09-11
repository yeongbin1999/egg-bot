import asyncio
import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.database import (
    create_group,
    get_groups,
    get_group,
    rename_group,
    delete_group,
    toggle_group,
    set_translation_channel,
    remove_translation_channel,
    get_translation_channels,
    get_translation_source,
    get_translation_targets,
    save_message_mapping,
    get_message_mappings,
    get_source_message_mapping,
    delete_message_mappings,
)

from bot.translation.service import TranslationService


# =========================================================
# LANGUAGE
# =========================================================

LANGUAGE_CHOICES = [
    app_commands.Choice(
        name="🇰🇷 한국어",
        value="ko"
    ),
    app_commands.Choice(
        name="🇺🇸 English",
        value="en"
    ),
    app_commands.Choice(
        name="🇯🇵 日本語",
        value="ja"
    ),
    app_commands.Choice(
        name="🇹🇼 繁體中文 (台灣)",
        value="zh-TW"
    ),
]


LANGUAGE_NAMES = {
    "ko": "🇰🇷 한국어",
    "en": "🇺🇸 English",
    "ja": "🇯🇵 日本語",
    "zh-TW": "🇹🇼 繁體中文 (台灣)",
}


# =========================================================
# DISCORD TIMESTAMP RESTORE
# =========================================================

def restore_discord_timestamps(
    text: str
) -> str:
    """
    번역 과정에서 공백이 생긴 Discord timestamp 문법을 복구합니다.

    예:
        <t : 1757588400 : R>
        <t:1757588400 :R>
        <t :1757588400:R>
        <t : 1757588400>
        <t:1757588400>

    ->
        <t:1757588400:R>
        <t:1757588400>
    """

    if not text:
        return text

    return re.sub(
        r"<\s*t\s*[:：]\s*(\d+)\s*[:：]?\s*([tTdDfFR])?\s*>",
        lambda match: (
            f"<t:{match.group(1)}"
            f"{':' + match.group(2) if match.group(2) else ''}>"
        ),
        text
    )


# =========================================================
# GROUP AUTOCOMPLETE
# =========================================================

async def group_autocomplete(
    interaction: discord.Interaction,
    current: str
):
    if interaction.guild is None:
        return []

    groups = await get_groups(
        interaction.guild.id
    )

    current = current.strip().lower()

    choices = []

    for _, name, enabled in groups:

        if current and current not in name.lower():
            continue

        status = "🟢" if enabled else "🔴"

        choices.append(
            app_commands.Choice(
                name=f"{status} {name}",
                value=name
            )
        )

        if len(choices) >= 25:
            break

    return choices


# =========================================================
# COG
# =========================================================

class Translation(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot
    ):
        self.bot = bot

        self.translation_service = (
            TranslationService()
        )

    # =========================================================
    # /translation
    # =========================================================

    translation = app_commands.Group(
        name="translation",
        description="번역 설정 관리"
    )

    # =========================================================
    # /translation channel
    # =========================================================

    channel = app_commands.Group(
        name="channel",
        description="번역 채널 관리",
        parent=translation
    )

    # =========================================================
    # WEBHOOK
    # =========================================================

    async def get_or_create_webhook(
        self,
        channel: discord.TextChannel
    ) -> Optional[discord.Webhook]:

        try:

            webhooks = await channel.webhooks()

            # -------------------------------------------------
            # 기존 봇 Webhook 검색
            # -------------------------------------------------

            for webhook in webhooks:

                if (
                    webhook.user is not None
                    and self.bot.user is not None
                    and webhook.user.id == self.bot.user.id
                ):
                    return webhook

            # -------------------------------------------------
            # 없으면 생성
            # -------------------------------------------------

            webhook = await channel.create_webhook(
                name="Translation Bot"
            )

            print(
                f"Webhook 생성 완료: #{channel.name}"
            )

            return webhook

        except discord.Forbidden:

            print(
                f"Webhook 관리 권한이 없습니다: "
                f"#{channel.name}"
            )

            return None

        except discord.HTTPException as e:

            print(
                f"Webhook 생성 실패 "
                f"#{channel.name}: {e}"
            )

            return None

    # =========================================================
    # REPLY REFERENCE
    # =========================================================

    async def get_reply_reference(
        self,
        message: discord.Message,
        source: dict,
        target_channel_id: int
    ) -> Optional[discord.MessageReference]:
        """대상 언어 채널에서 답글로 연결할 부모 메시지를 찾습니다."""

        if message.reference is None:
            return None

        referenced_message_id = message.reference.message_id

        if referenced_message_id is None:
            return None

        parent_source_message_id = None
        parent_source_channel_id = None

        parent_mappings = await get_message_mappings(
            referenced_message_id,
            message.channel.id
        )

        # 번역 메시지에 답글을 단 경우에는
        # 번역본에서 원문을 역추적합니다.
        if not parent_mappings:

            parent_source = await get_source_message_mapping(
                referenced_message_id,
                message.channel.id
            )

            if (
                parent_source is not None
                and parent_source[0] == source["group_id"]
            ):
                parent_source_message_id = parent_source[1]
                parent_source_channel_id = parent_source[2]

                parent_mappings = await get_message_mappings(
                    parent_source_message_id,
                    parent_source_channel_id
                )

        for (
            parent_group_id,
            parent_target_message_id,
            parent_target_channel_id,
            parent_webhook_url,
            parent_language
        ) in parent_mappings:

            if (
                parent_group_id == source["group_id"]
                and parent_target_channel_id == target_channel_id
            ):
                return discord.MessageReference(
                    message_id=parent_target_message_id,
                    channel_id=target_channel_id,
                    guild_id=message.guild.id
                )

        # 답글을 원문의 언어 채널로 번역할 때는
        # 원문을 부모로 사용합니다.
        if (
            parent_source_message_id is not None
            and parent_source_channel_id == target_channel_id
        ):
            return discord.MessageReference(
                message_id=parent_source_message_id,
                channel_id=target_channel_id,
                guild_id=message.guild.id
            )

        return None

    # =========================================================
    # SEND TRANSLATION
    # =========================================================

    async def send_translation(
        self,
        message: discord.Message,
        source: dict,
        target_language: str,
        target_channel_id: int,
        webhook_url: Optional[str]
    ):

        target_channel = (
            message.guild.get_channel(
                target_channel_id
            )
        )

        if target_channel is None:
            return

        if not isinstance(
            target_channel,
            discord.TextChannel
        ):
            return

        # -----------------------------------------------------
        # Webhook 가져오기
        # -----------------------------------------------------

        webhook = None

        if webhook_url:

            try:

                webhook = (
                    discord.Webhook.from_url(
                        webhook_url,
                        client=self.bot
                    )
                )

            except Exception as e:

                print(
                    f"Webhook URL 처리 실패: {e}"
                )

        # -----------------------------------------------------
        # Webhook이 없으면 생성
        # -----------------------------------------------------

        if webhook is None:

            webhook = (
                await self.get_or_create_webhook(
                    target_channel
                )
            )

            if webhook is None:
                return

            webhook_url = webhook.url

            await set_translation_channel(
                message.guild.id,
                source["group_name"],
                target_language,
                target_channel.id,
                webhook_url
            )

        # -----------------------------------------------------
        # 번역
        # -----------------------------------------------------

        translated = ""

        if message.content.strip():

            try:

                translated = (
                    await self.translation_service.translate(
                        text=message.content,
                        source=source["language"],
                        target=target_language
                    )
                )

                # -------------------------------------------------
                # Discord Timestamp 문법 복구
                # -------------------------------------------------

                translated = restore_discord_timestamps(
                    translated
                )

            except Exception as e:

                print(
                    f"번역 실패 "
                    f"[{source['language']} -> "
                    f"{target_language}]: "
                    f"{e}"
                )

                return

        # -----------------------------------------------------
        # 첨부파일
        # -----------------------------------------------------

        attachments = []

        for attachment in message.attachments:

            try:

                file = await attachment.to_file()

                attachments.append(file)

                print(
                    f"첨부파일 준비 완료: "
                    f"{attachment.filename}"
                )

            except Exception as e:

                print(
                    f"첨부파일 처리 실패 "
                    f"{attachment.filename}: {e}"
                )

        # -----------------------------------------------------
        # Reply 대상 찾기
        # -----------------------------------------------------

        reference = await self.get_reply_reference(
            message,
            source,
            target_channel.id
        )

        reply_prefix = ""

        if reference is not None:

            author_name = discord.utils.escape_markdown(
                message.author.display_name
            )

            reply_prefix = f"{author_name}: "

        # -----------------------------------------------------
        # 원본 사용자 정보
        # -----------------------------------------------------

        username = (
            message.author.display_name
        )

        avatar_url = (
            message.author.display_avatar.url
        )

        # -----------------------------------------------------
        # 보낼 내용이 아무것도 없으면 무시
        # -----------------------------------------------------

        if not translated and not attachments:
            return

        outgoing_content = (
            f"{reply_prefix}{translated}"
            if translated
            else (reply_prefix or None)
        )

        # -----------------------------------------------------
        # Webhook 전송
        # -----------------------------------------------------

        async def deliver(
            active_webhook: discord.Webhook
        ):

            if reference is not None:

                return await target_channel.send(
                    outgoing_content,
                    files=attachments,
                    reference=reference
                )

            return await active_webhook.send(
                outgoing_content,
                username=username,
                avatar_url=avatar_url,
                files=attachments,
                wait=True
            )

        try:

            sent_message = await deliver(
                webhook
            )

        except discord.NotFound as e:

            # 저장된 URL의 webhook이 삭제되었거나
            # 토큰이 무효해진 경우입니다.
            if reference is not None:

                print(
                    f"답글 번역 대상 메시지를 찾을 수 없습니다: "
                    f"#{target_channel.name}: {e}"
                )

                return

            print(
                f"저장된 Webhook을 찾을 수 없어 다시 연결합니다: "
                f"#{target_channel.name}"
            )

            webhook = await self.get_or_create_webhook(
                target_channel
            )

            if webhook is None:
                return

            await set_translation_channel(
                message.guild.id,
                source["group_name"],
                target_language,
                target_channel.id,
                webhook.url
            )

            # 첫 요청 뒤 파일 객체는 닫히므로
            # 원본 첨부파일에서 다시 만듭니다.
            attachments = []

            for source_attachment in message.attachments:

                try:

                    attachments.append(
                        await source_attachment.to_file()
                    )

                except Exception as attachment_error:

                    print(
                        f"재연결 첨부파일 처리 실패 "
                        f"{source_attachment.filename}: "
                        f"{attachment_error}"
                    )

                    return

            try:

                sent_message = await deliver(
                    webhook
                )

            except discord.Forbidden:

                print(
                    f"Webhook 전송 권한이 없습니다: "
                    f"#{target_channel.name}"
                )

                return

            except discord.HTTPException as retry_error:

                print(
                    f"Webhook 재연결 후 전송 실패 "
                    f"#{target_channel.name}: "
                    f"{retry_error}"
                )

                return

        except discord.Forbidden:

            print(
                f"Webhook 전송 권한이 없습니다: "
                f"#{target_channel.name}"
            )

            return

        except discord.HTTPException as e:

            print(
                f"Webhook 전송 실패 "
                f"#{target_channel.name}: {e}"
            )

            return

        # -----------------------------------------------------
        # 번역 메시지 ID 저장
        # -----------------------------------------------------

        if sent_message is not None:

            await save_message_mapping(
                group_id=source["group_id"],
                source_message_id=message.id,
                source_channel_id=message.channel.id,
                target_message_id=sent_message.id,
                target_channel_id=target_channel.id
            )

    # =========================================================
    # MESSAGE CREATE
    # =========================================================

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message
    ):

        # -----------------------------------------------------
        # DM 무시
        # -----------------------------------------------------

        if message.guild is None:
            return

        # -----------------------------------------------------
        # 봇 메시지 무시
        # -----------------------------------------------------

        if message.author.bot:
            return

        # -----------------------------------------------------
        # 빈 메시지 무시
        # -----------------------------------------------------

        if (
            not message.content.strip()
            and not message.attachments
        ):
            return

        # -----------------------------------------------------
        # 번역 채널 확인
        # -----------------------------------------------------

        source = await get_translation_source(
            message.guild.id,
            message.channel.id
        )

        if source is None:
            return

        # -----------------------------------------------------
        # 그룹 OFF
        # -----------------------------------------------------

        if not source["enabled"]:
            return

        # -----------------------------------------------------
        # 번역 대상
        # -----------------------------------------------------

        targets = await get_translation_targets(
            source["group_id"],
            source["language"]
        )

        if not targets:
            return

        # -----------------------------------------------------
        # 모든 언어 동시 번역
        # -----------------------------------------------------

        tasks = [
            self.send_translation(
                message=message,
                source=source,
                target_language=target_language,
                target_channel_id=target_channel_id,
                webhook_url=webhook_url
            )
            for (
                target_language,
                target_channel_id,
                webhook_url
            ) in targets
        ]

        await asyncio.gather(
            *tasks
        )

    # =========================================================
    # MESSAGE EDIT
    # =========================================================

    @staticmethod
    def attachment_signature(
        message: discord.Message
    ):
        """첨부파일 변경 여부를 비교하기 위한 값입니다."""

        return tuple(
            (
                attachment.id,
                attachment.filename,
                attachment.size,
                attachment.description,
            )
            for attachment in message.attachments
        )

    async def sync_message_edit(
        self,
        message: discord.Message,
        source: dict,
        *,
        sync_content: bool,
        sync_attachments: bool
    ):
        """원본 메시지의 변경 사항을 각 번역 메시지에 반영합니다."""

        mappings = await get_message_mappings(
            message.id,
            message.channel.id
        )

        if not mappings:
            return

        async def edit_one(mapping):

            (
                group_id,
                target_message_id,
                target_channel_id,
                webhook_url,
                target_language
            ) = mapping

            if group_id != source["group_id"] or not webhook_url:
                return

            edit_kwargs = {}

            # -------------------------------------------------
            # 본문 수정
            # -------------------------------------------------

            if sync_content:

                translated = None

                if message.content.strip():

                    try:

                        translated = (
                            await self.translation_service.translate(
                                text=message.content,
                                source=source["language"],
                                target=target_language
                            )
                        )

                        # -----------------------------------------
                        # Discord Timestamp 문법 복구
                        # -----------------------------------------

                        translated = restore_discord_timestamps(
                            translated
                        )

                    except Exception as e:

                        print(
                            f"수정 번역 실패 "
                            f"[{source['language']} -> "
                            f"{target_language}]: {e}"
                        )

                        return

                reply_reference = await self.get_reply_reference(
                    message,
                    source,
                    target_channel_id
                )

                reply_prefix = ""

                if reply_reference is not None:

                    author_name = discord.utils.escape_markdown(
                        message.author.display_name
                    )

                    reply_prefix = f"{author_name}: "

                # None을 전달하면
                # 번역 메시지의 본문도 비워집니다.
                edit_kwargs["content"] = (
                    f"{reply_prefix}{translated}"
                    if translated
                    else (reply_prefix or None)
                )

            # -------------------------------------------------
            # 첨부파일 수정
            # -------------------------------------------------

            if sync_attachments:

                files = []

                for attachment in message.attachments:

                    try:

                        files.append(
                            await attachment.to_file()
                        )

                    except Exception as e:

                        # 일부만 반영하면 원본과 번역본이
                        # 더 달라지므로 이번 수정은 건너뜁니다.
                        print(
                            f"수정 첨부파일 처리 실패 "
                            f"{attachment.filename}: {e}"
                        )

                        return

                # 새 파일 목록만 전달해
                # 기존 첨부파일을 완전히 교체합니다.
                #
                # 빈 목록은 번역 메시지의
                # 첨부파일을 모두 삭제합니다.
                edit_kwargs["attachments"] = files

            try:

                target_channel = self.bot.get_channel(
                    target_channel_id
                )

                if isinstance(
                    target_channel,
                    discord.TextChannel
                ):

                    target_message = (
                        await target_channel.fetch_message(
                            target_message_id
                        )
                    )

                    # 답글은 일반 봇 메시지로 전송되므로
                    # 해당 방식으로 수정합니다.
                    if target_message.webhook_id is None:

                        await target_message.edit(
                            **edit_kwargs
                        )

                        return

                webhook = discord.Webhook.from_url(
                    webhook_url,
                    client=self.bot
                )

                await webhook.edit_message(
                    target_message_id,
                    **edit_kwargs
                )

            except discord.NotFound:

                print(
                    f"수정 대상 메시지를 찾을 수 없습니다: "
                    f"{target_message_id}"
                )

            except discord.Forbidden:

                print(
                    f"번역 메시지 수정 권한이 없습니다: "
                    f"{target_message_id}"
                )

            except discord.HTTPException as e:

                print(
                    f"번역 메시지 수정 실패: {e}"
                )

        await asyncio.gather(
            *(edit_one(mapping) for mapping in mappings)
        )

    @commands.Cog.listener()
    async def on_message_edit(
        self,
        before: discord.Message,
        after: discord.Message
    ):

        # -----------------------------------------------------
        # DM 무시
        # -----------------------------------------------------

        if after.guild is None:
            return

        # -----------------------------------------------------
        # 봇 메시지 무시
        # -----------------------------------------------------

        if after.author.bot:
            return

        # -----------------------------------------------------
        # 본문과 첨부파일 모두 바뀌지 않았으면 무시
        # -----------------------------------------------------

        content_changed = (
            before.content != after.content
        )

        attachments_changed = (
            self.attachment_signature(before)
            != self.attachment_signature(after)
        )

        if not content_changed and not attachments_changed:
            return

        # -----------------------------------------------------
        # 번역 대상 확인
        # -----------------------------------------------------

        source = await get_translation_source(
            after.guild.id,
            after.channel.id
        )

        if source is None:
            return

        if not source["enabled"]:
            return

        await self.sync_message_edit(
            after,
            source,
            sync_content=content_changed,
            sync_attachments=attachments_changed
        )

    @commands.Cog.listener()
    async def on_raw_message_edit(
        self,
        payload: discord.RawMessageUpdateEvent
    ):
        """캐시에 없는 메시지의 수정도 동기화합니다."""

        if (
            payload.cached_message is not None
            or payload.guild_id is None
        ):
            return

        channel = self.bot.get_channel(
            payload.channel_id
        )

        if not isinstance(
            channel,
            discord.TextChannel
        ):
            return

        try:

            message = await channel.fetch_message(
                payload.message_id
            )

        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException
        ):
            return

        if message.author.bot:
            return

        source = await get_translation_source(
            payload.guild_id,
            payload.channel_id
        )

        if source is None or not source["enabled"]:
            return

        # 캐시된 이전 상태가 없으므로
        # 본문과 첨부파일을 모두 최신 상태로 맞춥니다.
        await self.sync_message_edit(
            message,
            source,
            sync_content=True,
            sync_attachments=True
        )

    # =========================================================
    # MESSAGE DELETE
    # =========================================================

    async def sync_message_delete(
        self,
        source_message_id: int,
        source_channel_id: int
    ):
        """원본이 삭제되면 연결된 번역 메시지도 삭제합니다."""

        mappings = await get_message_mappings(
            source_message_id,
            source_channel_id
        )

        if not mappings:
            return

        # -----------------------------------------------------
        # 번역 메시지 삭제
        # -----------------------------------------------------

        async def delete_one(
            mapping
        ):

            (
                group_id,
                target_message_id,
                target_channel_id,
                webhook_url,
                target_language
            ) = mapping

            try:

                target_channel = self.bot.get_channel(
                    target_channel_id
                )

                if isinstance(
                    target_channel,
                    discord.TextChannel
                ):

                    target_message = (
                        await target_channel.fetch_message(
                            target_message_id
                        )
                    )

                    # webhook 토큰이 바뀌어도
                    # 봇의 Manage Messages 권한으로
                    # 대상 메시지를 직접 삭제할 수 있습니다.
                    await target_message.delete()

                    return True

                if not webhook_url:
                    return False

                webhook = discord.Webhook.from_url(
                    webhook_url,
                    client=self.bot
                )

                await webhook.delete_message(
                    target_message_id
                )

                return True

            except discord.NotFound:

                # 대상이 이미 삭제된 경우에도
                # 동기화 상태는 완료입니다.
                return True

            except discord.Forbidden:

                print(
                    f"번역 메시지 삭제 권한이 없습니다: "
                    f"{target_message_id}"
                )

                return False

            except discord.HTTPException as e:

                print(
                    f"번역 메시지 삭제 실패: {e}"
                )

                return False

        delete_results = await asyncio.gather(
            *[
                delete_one(mapping)
                for mapping in mappings
            ]
        )

        # -----------------------------------------------------
        # 매핑 삭제
        # -----------------------------------------------------

        if all(delete_results):

            await delete_message_mappings(
                source_message_id,
                source_channel_id
            )

    @commands.Cog.listener()
    async def on_message_delete(
        self,
        message: discord.Message
    ):

        if (
            message.guild is None
            or message.author.bot
        ):
            return

        await self.sync_message_delete(
            message.id,
            message.channel.id
        )

    @commands.Cog.listener()
    async def on_raw_message_delete(
        self,
        payload: discord.RawMessageDeleteEvent
    ):
        """캐시에 없는 원본 메시지의 삭제도 동기화합니다."""

        if (
            payload.cached_message is not None
            or payload.guild_id is None
        ):
            return

        await self.sync_message_delete(
            payload.message_id,
            payload.channel_id
        )

    @commands.Cog.listener()
    async def on_bulk_message_delete(
        self,
        messages: list[discord.Message]
    ):
        """캐시된 메시지를 일괄 삭제할 때 번역본도 함께 삭제합니다."""

        tasks = [
            self.sync_message_delete(
                message.id,
                message.channel.id
            )
            for message in messages
            if (
                message.guild is not None
                and not message.author.bot
            )
        ]

        if tasks:
            await asyncio.gather(
                *tasks
            )

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(
        self,
        payload: discord.RawBulkMessageDeleteEvent
    ):
        """캐시에 없는 일괄 삭제 메시지도 동기화합니다."""

        if payload.guild_id is None:
            return

        # 캐시된 메시지는
        # on_bulk_message_delete에서 처리합니다.
        cached_ids = {
            message.id
            for message in payload.cached_messages
        }

        tasks = [
            self.sync_message_delete(
                message_id,
                payload.channel_id
            )
            for message_id in payload.message_ids
            if message_id not in cached_ids
        ]

        if tasks:
            await asyncio.gather(
                *tasks
            )

    # =========================================================
    # GROUP CREATE
    # =========================================================

    @translation.command(
        name="create",
        description="번역 그룹을 생성합니다."
    )
    @app_commands.describe(
        name="생성할 그룹 이름"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def create(
        self,
        interaction: discord.Interaction,
        name: str
    ):

        if interaction.guild is None:

            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )

            return

        name = name.strip()

        if not name:

            await interaction.response.send_message(
                "그룹 이름을 입력해주세요.",
                ephemeral=True
            )

            return

        if len(name) > 50:

            await interaction.response.send_message(
                "그룹 이름은 50자 이하로 입력해주세요.",
                ephemeral=True
            )

            return

        group_id = await create_group(
            interaction.guild.id,
            name
        )

        if group_id is None:

            await interaction.response.send_message(
                f"❌ 이미 `{name}` 그룹이 존재합니다.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            f"✅ 번역 그룹 `{name}`을 생성했습니다.",
            ephemeral=True
        )

    # =========================================================
    # GROUP CONFIG
    # =========================================================

    @translation.command(
        name="config",
        description="전체 번역 설정을 확인합니다."
    )
    async def config(
        self,
        interaction: discord.Interaction
    ):

        if interaction.guild is None:

            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )

            return

        groups = await get_groups(
            interaction.guild.id
        )

        if not groups:

            await interaction.response.send_message(
                "현재 등록된 번역 그룹이 없습니다.",
                ephemeral=True
            )

            return

        embed = discord.Embed(
            title="🌐 Translation Configuration",
            description="현재 서버의 전체 번역 설정입니다.",
            color=discord.Color.blue()
        )

        for group_id, name, enabled in groups:

            status = (
                "🟢 ON"
                if enabled
                else "🔴 OFF"
            )

            channels = await get_translation_channels(
                interaction.guild.id,
                name
            )

            if channels:

                channel_lines = []

                for (
                    language,
                    channel_id,
                    webhook_url
                ) in channels:

                    language_name = (
                        LANGUAGE_NAMES.get(
                            language,
                            language
                        )
                    )

                    webhook_status = (
                        "🔗"
                        if webhook_url
                        else "⚠️"
                    )

                    channel_lines.append(
                        f"{language_name} → "
                        f"<#{channel_id}> "
                        f"{webhook_status}"
                    )

                channel_text = "\n".join(
                    channel_lines
                )

            else:

                channel_text = (
                    "등록된 채널 없음"
                )

            value = (
                f"**상태:** {status}\n\n"
                f"{channel_text}"
            )

            embed.add_field(
                name=f"📁 {name}",
                value=value,
                inline=False
            )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    # =========================================================
    # GROUP RENAME
    # =========================================================

    @translation.command(
        name="rename",
        description="번역 그룹의 이름을 변경합니다."
    )
    @app_commands.describe(
        old_name="현재 그룹 이름",
        new_name="새 그룹 이름"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def rename(
        self,
        interaction: discord.Interaction,
        old_name: str,
        new_name: str
    ):

        if interaction.guild is None:

            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )

            return

        old_name = old_name.strip()
        new_name = new_name.strip()

        if not old_name or not new_name:

            await interaction.response.send_message(
                "그룹 이름을 입력해주세요.",
                ephemeral=True
            )

            return

        group = await get_group(
            interaction.guild.id,
            old_name
        )

        if group is None:

            await interaction.response.send_message(
                f"❌ `{old_name}` 그룹을 찾을 수 없습니다.",
                ephemeral=True
            )

            return

        success = await rename_group(
            interaction.guild.id,
            old_name,
            new_name
        )

        if not success:

            await interaction.response.send_message(
                f"❌ `{new_name}` 그룹이 이미 존재합니다.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            f"✅ `{old_name}` → `{new_name}`으로 변경했습니다.",
            ephemeral=True
        )

    # =========================================================
    # GROUP DELETE
    # =========================================================

    @translation.command(
        name="delete",
        description="번역 그룹을 삭제합니다."
    )
    @app_commands.describe(
        name="삭제할 그룹 이름"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def delete(
        self,
        interaction: discord.Interaction,
        name: str
    ):

        if interaction.guild is None:

            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )

            return

        success = await delete_group(
            interaction.guild.id,
            name
        )

        if not success:

            await interaction.response.send_message(
                f"❌ `{name}` 그룹을 찾을 수 없습니다.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            f"🗑️ 번역 그룹 `{name}`을 삭제했습니다.",
            ephemeral=True
        )

    # =========================================================
    # GROUP TOGGLE
    # =========================================================

    @translation.command(
        name="toggle",
        description="번역 그룹을 활성화하거나 비활성화합니다."
    )
    @app_commands.describe(
        name="전환할 그룹 이름"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def toggle(
        self,
        interaction: discord.Interaction,
        name: str
    ):

        if interaction.guild is None:

            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )

            return

        enabled = await toggle_group(
            interaction.guild.id,
            name
        )

        if enabled is None:

            await interaction.response.send_message(
                f"❌ `{name}` 그룹을 찾을 수 없습니다.",
                ephemeral=True
            )

            return

        status = (
            "🟢 활성화"
            if enabled
            else "🔴 비활성화"
        )

        await interaction.response.send_message(
            f"✅ `{name}` 그룹을 {status}했습니다.",
            ephemeral=True
        )

    # =========================================================
    # CHANNEL SET
    # =========================================================

    @channel.command(
        name="set",
        description="그룹의 언어 채널을 설정합니다."
    )
    @app_commands.describe(
        group="번역 그룹",
        language="채널의 언어",
        channel="번역에 사용할 Discord 채널"
    )
    @app_commands.autocomplete(
        group=group_autocomplete
    )
    @app_commands.choices(
        language=LANGUAGE_CHOICES
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def channel_set(
        self,
        interaction: discord.Interaction,
        group: str,
        language: app_commands.Choice[str],
        channel: discord.TextChannel
    ):

        if interaction.guild is None:

            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )

            return

        group = group.strip()

        # -----------------------------------------------------
        # 그룹 확인
        # -----------------------------------------------------

        group_data = await get_group(
            interaction.guild.id,
            group
        )

        if group_data is None:

            await interaction.response.send_message(
                f"❌ `{group}` 그룹을 찾을 수 없습니다.",
                ephemeral=True
            )

            return

        # -----------------------------------------------------
        # Webhook
        # -----------------------------------------------------

        webhook = await self.get_or_create_webhook(
            channel
        )

        if webhook is None:

            await interaction.response.send_message(
                "❌ 해당 채널에 Webhook을 생성할 수 없습니다.\n"
                "봇에게 `Manage Webhooks` 권한이 있는지 확인해주세요.",
                ephemeral=True
            )

            return

        # -----------------------------------------------------
        # DB
        # -----------------------------------------------------

        result = await set_translation_channel(
            interaction.guild.id,
            group,
            language.value,
            channel.id,
            webhook.url
        )

        if result == "DUPLICATE":

            await interaction.response.send_message(
                "❌ 이미 다른 언어에서 사용 중인 채널입니다.",
                ephemeral=True
            )

            return

        if result == "ADDED":

            message = (
                f"✅ `{group}` 그룹에 "
                f"{language.name} → {channel.mention} "
                f"채널을 추가했습니다.\n"
                f"🔗 번역용 Webhook도 연결했습니다."
            )

        else:

            message = (
                f"✅ `{group}` 그룹의 "
                f"{language.name} 채널을 "
                f"{channel.mention}으로 변경했습니다.\n"
                f"🔗 번역용 Webhook을 연결했습니다."
            )

        await interaction.response.send_message(
            message,
            ephemeral=True
        )

    # =========================================================
    # CHANNEL REMOVE
    # =========================================================

    @channel.command(
        name="remove",
        description="그룹에서 언어 채널을 제거합니다."
    )
    @app_commands.describe(
        group="번역 그룹",
        language="제거할 언어"
    )
    @app_commands.autocomplete(
        group=group_autocomplete
    )
    @app_commands.choices(
        language=LANGUAGE_CHOICES
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def channel_remove(
        self,
        interaction: discord.Interaction,
        group: str,
        language: app_commands.Choice[str]
    ):

        if interaction.guild is None:

            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )

            return

        group = group.strip()

        result = await remove_translation_channel(
            interaction.guild.id,
            group,
            language.value
        )

        if result == "GROUP_NOT_FOUND":

            await interaction.response.send_message(
                f"❌ `{group}` 그룹을 찾을 수 없습니다.",
                ephemeral=True
            )

            return

        if result == "CHANNEL_NOT_FOUND":

            await interaction.response.send_message(
                f"❌ `{group}` 그룹에 "
                f"{language.name} 채널이 등록되어 있지 않습니다.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            f"🗑️ `{group}` 그룹에서 "
            f"{language.name} 채널을 제거했습니다.",
            ephemeral=True
        )

    # =========================================================
    # CLEAR
    # =========================================================

    @app_commands.command(
        name="clear",
        description="현재 채널의 최근 메시지를 삭제합니다."
    )
    @app_commands.describe(
        count="삭제할 메시지 수 (1~100)"
    )
    @app_commands.checks.has_permissions(
        manage_messages=True
    )
    async def clear(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[int, 1, 100]
    ):
        """현재 채널에서 최근 메시지를 지정한 수만큼 삭제합니다."""

        if interaction.guild is None:

            await interaction.response.send_message(
                "❌ 서버 채널에서만 사용할 수 있습니다.",
                ephemeral=True
            )

            return

        channel = interaction.channel

        if not isinstance(
            channel,
            (discord.TextChannel, discord.Thread)
        ):

            await interaction.response.send_message(
                "❌ 메시지를 삭제할 수 있는 채널에서 사용해주세요.",
                ephemeral=True
            )

            return

        await interaction.response.defer(
            ephemeral=True
        )

        try:

            deleted = await channel.purge(
                limit=count,
                reason=(
                    f"/clear by {interaction.user} "
                    f"({interaction.user.id})"
                )
            )

        except discord.Forbidden:

            await interaction.edit_original_response(
                content=(
                    "❌ 메시지를 삭제할 권한이 없습니다. "
                    "봇에 `Manage Messages` 권한이 있는지 확인해주세요."
                )
            )

            return

        except discord.HTTPException as e:

            print(
                f"메시지 삭제 실패: {e}"
            )

            await interaction.edit_original_response(
                content="❌ 메시지 삭제 중 오류가 발생했습니다."
            )

            return

        await interaction.edit_original_response(
            content=f"🗑️ 메시지 {len(deleted)}개를 삭제했습니다."
        )

    # =========================================================
    # ERROR HANDLER
    # =========================================================

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):

        if isinstance(
            error,
            app_commands.MissingPermissions
        ):

            message = (
                "❌ 이 명령어는 서버 관리 권한이 필요합니다."
            )

        else:

            print(
                f"Slash Command Error: {error}"
            )

            message = (
                "❌ 명령어 실행 중 오류가 발생했습니다."
            )

        if interaction.response.is_done():

            await interaction.followup.send(
                message,
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                message,
                ephemeral=True
            )


# =========================================================
# SETUP
# =========================================================

async def setup(
    bot: commands.Bot
):
    await bot.add_cog(
        Translation(bot)
    )