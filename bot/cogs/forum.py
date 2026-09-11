import asyncio
import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.database import (
    add_forum_channel,
    get_forum_channels,
    is_forum_channel_monitored,
    remove_forum_channel,
)


# ============================================================
# 설정
# ============================================================

TRIBE_PRIORITY = [
    "EGG",
    "EGG4",
    "EGG9",
    "EGG13",
    "ACD",
]

KNOWN_TRIBES = set(TRIBE_PRIORITY)


# ============================================================
# 날짜 추출
# ============================================================

def extract_date_from_title(title: str) -> Optional[str]:
    """
    제목에서 날짜를 찾아 M.D 형식으로 반환한다.

    지원:
    - 8월 11일
    - 8월 11
    - 8월11일
    - 8.11
    - 08.11
    - 8/11
    - 08/11
    - 8-11
    - 08-11
    - 0811
    """

    # 8월 11일 / 8월 11 / 8월11일
    match = re.search(
        r"(?<!\d)(1[0-2]|0?[1-9])\s*월\s*(3[01]|[12]?\d)\s*일?",
        title,
        re.IGNORECASE,
    )

    if match:
        month = int(match.group(1))
        day = int(match.group(2))

        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{month}.{day}"

    # 8.11 / 8/11 / 8-11
    match = re.search(
        r"(?<!\d)(1[0-2]|0?[1-9])\s*[./-]\s*(3[01]|[12]?\d)(?!\d)",
        title,
    )

    if match:
        month = int(match.group(1))
        day = int(match.group(2))

        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{month}.{day}"

    # 0811
    match = re.search(
        r"(?<!\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)",
        title,
    )

    if match:
        month = int(match.group(1))
        day = int(match.group(2))

        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{month}.{day}"

    return None


# ============================================================
# 태그 정리
# ============================================================

def clean_tag_text(tag_name: str) -> str:
    """
    태그 이름에서 이모지/특수문자 등을 제거한다.
    """

    text = re.sub(
        r"[^\w가-힣\s]",
        "",
        tag_name,
        flags=re.UNICODE,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return text


# ============================================================
# 부족 찾기
# ============================================================

def find_tribe(tag_names: list[str]) -> Optional[str]:
    """
    태그에서 부족을 찾는다.

    우선순위:
        EGG
        EGG4
        EGG9
        EGG13
        ACD

    EGG가 EGG4 / EGG9 / EGG13에 포함되는 문제를 방지한다.
    """

    cleaned_tags = [
        clean_tag_text(tag)
        for tag in tag_names
    ]

    for tribe in TRIBE_PRIORITY:
        pattern = rf"(?<!\w){re.escape(tribe)}(?!\w)"

        for tag in cleaned_tags:
            if re.search(
                pattern,
                tag,
                re.IGNORECASE,
            ):
                return tribe

    return None


# ============================================================
# 과금 태그 확인
# ============================================================

def check_is_billing(tag_names: list[str]) -> bool:
    """
    과금 태그가 있는지 확인한다.
    """

    for tag in tag_names:
        cleaned = clean_tag_text(tag)

        if "과금" in cleaned:
            return True

    return False


# ============================================================
# 내용 태그 찾기
# ============================================================

def find_content_tag(
    tag_names: list[str],
) -> Optional[str]:
    """
    부족 태그와 과금 태그를 제외한
    첫 번째 태그를 내용 태그로 사용한다.
    """

    for tag in tag_names:
        cleaned = clean_tag_text(tag)

        if not cleaned:
            continue

        is_tribe = False

        for tribe in KNOWN_TRIBES:
            pattern = rf"(?<!\w){re.escape(tribe)}(?!\w)"

            if re.search(
                pattern,
                cleaned,
                re.IGNORECASE,
            ):
                is_tribe = True
                break

        if is_tribe:
            continue

        if "과금" in cleaned:
            continue

        return cleaned

    return None


# ============================================================
# 날짜 / 기간 제거
# ============================================================

def remove_date_and_periods(
    text: str,
) -> str:
    """
    문자열에서 날짜 및 날짜 범위를 제거한다.

    예:
        9월 11일
        9월11일
        9/11
        9.11
        9-11
        9월 11일~15일
        9/11~9/15
        9.11-9.15
        0911
    """

    # --------------------------------------------------------
    # 한국식 날짜 범위
    # --------------------------------------------------------

    korean_range = (
        r"(?<!\d)"
        r"(?:1[0-2]|0?[1-9])\s*월\s*"
        r"(?:3[01]|[12]?\d)\s*일?"
        r"\s*(?:~|～|-|–|—)\s*"
        r"(?:(?:1[0-2]|0?[1-9])\s*월\s*)?"
        r"(?:3[01]|[12]?\d)\s*일?"
        r"(?!\d)"
    )

    text = re.sub(
        korean_range,
        " ",
        text,
    )

    # --------------------------------------------------------
    # 숫자 날짜 범위
    # --------------------------------------------------------

    numeric_range = (
        r"(?<!\d)"
        r"(?:1[0-2]|0?[1-9])\s*[./-]\s*"
        r"(?:3[01]|[12]?\d)"
        r"\s*(?:~|～|-|–|—)\s*"
        r"(?:(?:1[0-2]|0?[1-9])\s*[./-]\s*)?"
        r"(?:3[01]|[12]?\d)"
        r"(?!\d)"
    )

    text = re.sub(
        numeric_range,
        " ",
        text,
    )

    # --------------------------------------------------------
    # 단일 한국식 날짜
    # --------------------------------------------------------

    korean_date = (
        r"(?<!\d)"
        r"(?:1[0-2]|0?[1-9])\s*월\s*"
        r"(?:3[01]|[12]?\d)\s*일?"
        r"(?!\d)"
    )

    text = re.sub(
        korean_date,
        " ",
        text,
    )

    # --------------------------------------------------------
    # 단일 숫자 날짜
    # --------------------------------------------------------

    numeric_date = (
        r"(?<!\d)"
        r"(?:1[0-2]|0?[1-9])\s*[./-]\s*"
        r"(?:3[01]|[12]?\d)"
        r"(?!\d)"
    )

    text = re.sub(
        numeric_date,
        " ",
        text,
    )

    # --------------------------------------------------------
    # 4자리 날짜
    # --------------------------------------------------------

    text = re.sub(
        r"(?<!\d)"
        r"(?:0[1-9]|1[0-2])"
        r"(?:0[1-9]|[12]\d|3[01])"
        r"(?!\d)",
        " ",
        text,
    )

    return text


# ============================================================
# 과금 포스트 결제자 이름 추출
# ============================================================

def extract_payer_names(
    title: str,
) -> Optional[str]:
    """
    과금 포스트 제목에서 결제자 이름을 추출한다.

    제거:
    - 부족명
    - 과금
    - 날짜
    - 날짜 기간
    - 괄호

    예:
        [EGG] 과금 9월 11일 영빈
        -> 영빈

        [EGG] 과금 9/11~9/15 영빈
        -> 영빈

        [EGG] 과금 영빈, 철수
        -> 영빈, 철수
    """

    text = title.strip()

    # --------------------------------------------------------
    # 대괄호 안의 내용 처리
    # --------------------------------------------------------

    def process_bracket(
        match: re.Match,
    ) -> str:

        content = match.group(1)
        cleaned = clean_tag_text(content)

        # 부족명이 들어간 괄호
        for tribe in KNOWN_TRIBES:
            pattern = (
                rf"(?<!\w)"
                rf"{re.escape(tribe)}"
                rf"(?!\w)"
            )

            if re.search(
                pattern,
                cleaned,
                re.IGNORECASE,
            ):
                return ""

        # 과금이 들어간 괄호
        if "과금" in cleaned:
            return ""

        # 날짜가 들어간 괄호
        if extract_date_from_title(cleaned):
            return ""

        return content

    text = re.sub(
        r"\[([^\]]*)\]",
        process_bracket,
        text,
    )

    # --------------------------------------------------------
    # 부족명 제거
    # --------------------------------------------------------

    for tribe in TRIBE_PRIORITY:
        text = re.sub(
            rf"(?<!\w){re.escape(tribe)}(?!\w)",
            " ",
            text,
            flags=re.IGNORECASE,
        )

    # --------------------------------------------------------
    # 과금 제거
    # --------------------------------------------------------

    text = re.sub(
        r"과금",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    # --------------------------------------------------------
    # 날짜 / 기간 제거
    # --------------------------------------------------------

    text = remove_date_and_periods(text)

    # --------------------------------------------------------
    # 괄호 제거
    # --------------------------------------------------------

    text = re.sub(
        r"[()[\]{}]",
        " ",
        text,
    )

    # --------------------------------------------------------
    # 이름 구분자 통일
    # --------------------------------------------------------

    text = re.sub(
        r"\s*[,/|&+]\s*",
        ", ",
        text,
    )

    # --------------------------------------------------------
    # 공백 정리
    # --------------------------------------------------------

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    # --------------------------------------------------------
    # 앞뒤 구분자 제거
    # --------------------------------------------------------

    text = re.sub(
        r"^[,\s]+|[,\s]+$",
        "",
        text,
    )

    # 연속 쉼표 정리
    text = re.sub(
        r",\s*,+",
        ", ",
        text,
    )

    text = text.strip(" ,")

    if not text:
        return None

    return text


# ============================================================
# 포럼 제목 변환
# ============================================================

def format_forum_title(
    title: str,
    tag_names: list[str],
) -> Optional[str]:
    """
    현재 제목과 태그를 기준으로 최종 제목을 만든다.

    일반:
        [부족] 날짜 내용태그

    과금:
        [부족] 결제자
    """

    tribe = find_tribe(tag_names)

    if tribe is None:
        return None

    # --------------------------------------------------------
    # 과금 포스트
    # --------------------------------------------------------

    if check_is_billing(tag_names):
        payers = extract_payer_names(title)

        if not payers:
            return None

        new_title = (
            f"[{tribe}] {payers}"
        )

    # --------------------------------------------------------
    # 일반 포스트
    # --------------------------------------------------------

    else:
        content_tag = find_content_tag(
            tag_names
        )

        if not content_tag:
            return None

        date_str = extract_date_from_title(
            title
        )

        if not date_str:
            return None

        new_title = (
            f"[{tribe}] "
            f"{date_str} "
            f"{content_tag}"
        )

    # --------------------------------------------------------
    # 이미 동일하면 수정하지 않음
    # --------------------------------------------------------

    if title.strip() == new_title:
        return None

    return new_title


# ============================================================
# Forum Cog
# ============================================================

class Forum(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    # ========================================================
    # 포스트 하나 처리
    # ========================================================

    async def _process_thread(
        self,
        thread: discord.Thread,
    ) -> bool:

        if not isinstance(
            thread.parent,
            discord.ForumChannel,
        ):
            return False

        forum_channel = thread.parent

        # 등록된 포럼인지 확인
        if not await is_forum_channel_monitored(
            forum_channel.guild.id,
            forum_channel.id,
        ):
            return False

        # ----------------------------------------------------
        # 적용 태그
        # ----------------------------------------------------

        tag_names = [
            tag.name
            for tag in thread.applied_tags
        ]

        # ----------------------------------------------------
        # 변경할 제목 계산
        # ----------------------------------------------------

        new_title = format_forum_title(
            thread.name,
            tag_names,
        )

        if not new_title:
            return False

        # ----------------------------------------------------
        # 이미 같은 제목이면 수정하지 않음
        # ----------------------------------------------------

        if thread.name.strip() == new_title:
            return False

        was_archived = thread.archived

        try:
            # ------------------------------------------------
            # Archived 포스트
            # ------------------------------------------------

            if was_archived:
                await thread.edit(
                    archived=False
                )

                await asyncio.sleep(0.5)

            # ------------------------------------------------
            # 제목 수정
            # ------------------------------------------------

            await thread.edit(
                name=new_title
            )

            # ------------------------------------------------
            # 원래 Archived였다면 다시 Archived
            # ------------------------------------------------

            if was_archived:
                await asyncio.sleep(0.5)

                await thread.edit(
                    archived=True
                )

            return True

        except discord.Forbidden:
            print(
                "[Forum] 제목 수정 권한 없음: "
                f"{thread.name}"
            )

        except discord.HTTPException as e:
            print(
                "[Forum] 제목 수정 실패: "
                f"{thread.name} / {e}"
            )

        return False

    # ========================================================
    # 새 포스트 생성
    # ========================================================

    @commands.Cog.listener()
    async def on_thread_create(
        self,
        thread: discord.Thread,
    ):
        if not isinstance(
            thread.parent,
            discord.ForumChannel,
        ):
            return

        # 태그가 완전히 반영될 때까지 대기
        await asyncio.sleep(2)

        try:
            fetched_thread = (
                await self.bot.fetch_channel(
                    thread.id
                )
            )

        except (
            discord.NotFound,
            discord.HTTPException,
        ):
            return

        if not isinstance(
            fetched_thread,
            discord.Thread,
        ):
            return

        await self._process_thread(
            fetched_thread
        )

    # ========================================================
    # 포스트 수정
    # ========================================================

    @commands.Cog.listener()
    async def on_thread_update(
        self,
        before: discord.Thread,
        after: discord.Thread,
    ):
        if not isinstance(
            after.parent,
            discord.ForumChannel,
        ):
            return

        # 제목 변경 여부
        title_changed = (
            before.name != after.name
        )

        # 태그 변경 여부
        before_tags = {
            tag.id
            for tag in before.applied_tags
        }

        after_tags = {
            tag.id
            for tag in after.applied_tags
        }

        tags_changed = (
            before_tags != after_tags
        )

        if not title_changed and not tags_changed:
            return

        await self._process_thread(
            after
        )

    # ========================================================
    # /forum
    # ========================================================

    forum = app_commands.Group(
        name="forum",
        description="포럼 관리",
    )

    # ========================================================
    # /forum channel
    # ========================================================

    channel = app_commands.Group(
        name="channel",
        description="포럼 채널 관리",
        parent=forum,
    )

    # ========================================================
    # /forum channel add
    # ========================================================

    @channel.command(
        name="add",
        description="자동 제목 정리를 적용할 포럼 채널을 등록합니다.",
    )
    @app_commands.describe(
        channel="등록할 포럼 채널",
    )
    async def forum_channel_add(
        self,
        interaction: discord.Interaction,
        channel: discord.ForumChannel,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        added = await add_forum_channel(
            interaction.guild.id,
            channel.id,
        )

        if added:
            await interaction.response.send_message(
                f"✅ {channel.mention} 포럼 채널을 등록했습니다.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"ℹ️ {channel.mention}은 이미 등록되어 있습니다.",
                ephemeral=True,
            )

    # ========================================================
    # /forum channel remove
    # ========================================================

    @channel.command(
        name="remove",
        description="자동 제목 정리 대상에서 포럼 채널을 제거합니다.",
    )
    @app_commands.describe(
        channel="제거할 포럼 채널",
    )
    async def forum_channel_remove(
        self,
        interaction: discord.Interaction,
        channel: discord.ForumChannel,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        removed = await remove_forum_channel(
            interaction.guild.id,
            channel.id,
        )

        if removed:
            await interaction.response.send_message(
                f"✅ {channel.mention} 포럼 채널을 제거했습니다.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"ℹ️ {channel.mention}은 등록되어 있지 않습니다.",
                ephemeral=True,
            )

    # ========================================================
    # /forum channel list
    # ========================================================

    @channel.command(
        name="list",
        description="자동 제목 정리 대상 포럼 채널을 확인합니다.",
    )
    async def forum_channel_list(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        channels = await get_forum_channels(
            interaction.guild.id,
        )

        if not channels:
            await interaction.response.send_message(
                "등록된 포럼 채널이 없습니다.",
                ephemeral=True,
            )
            return

        lines = []

        for channel_id in channels:
            channel = (
                interaction.guild.get_channel(
                    channel_id
                )
            )

            if channel:
                lines.append(
                    f"• {channel.mention}"
                )
            else:
                lines.append(
                    f"• 알 수 없는 채널 (`{channel_id}`)"
                )

        await interaction.response.send_message(
            "📋 **자동 제목 정리 포럼 채널**\n"
            + "\n".join(lines),
            ephemeral=True,
        )

    # ========================================================
    # /forum sync
    # ========================================================

    @forum.command(
        name="sync",
        description="포럼 채널의 모든 포스트 제목을 일괄 정리합니다.",
    )
    @app_commands.describe(
        channel="정리할 포럼 채널",
    )
    async def forum_sync(
        self,
        interaction: discord.Interaction,
        channel: discord.ForumChannel,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        # ----------------------------------------------------
        # 등록된 포럼인지 확인
        # ----------------------------------------------------

        if not await is_forum_channel_monitored(
            interaction.guild.id,
            channel.id,
        ):
            await interaction.response.send_message(
                "❌ 먼저 해당 포럼 채널을 등록해주세요.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            ephemeral=True,
        )

        # ====================================================
        # 모든 포스트 수집
        # ====================================================

        threads: list[discord.Thread] = []

        # ----------------------------------------------------
        # 현재 활성 포스트
        # ----------------------------------------------------

        threads.extend(
            channel.threads
        )

        # ----------------------------------------------------
        # Archived 포스트
        # ----------------------------------------------------

        try:
            existing_ids = {
                thread.id
                for thread in threads
            }

            async for archived_thread in (
                channel.archived_threads(
                    limit=None,
                )
            ):
                if (
                    archived_thread.id
                    not in existing_ids
                ):
                    threads.append(
                        archived_thread
                    )

                    existing_ids.add(
                        archived_thread.id
                    )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Archived 포스트를 읽을 권한이 없습니다.",
                ephemeral=True,
            )
            return

        except discord.HTTPException as e:
            await interaction.followup.send(
                "❌ 포스트 목록을 가져오는 중 오류가 발생했습니다.\n"
                f"`{e}`",
                ephemeral=True,
            )
            return

        # ====================================================
        # 오래된 포스트 → 최신 포스트
        # ====================================================

        threads.sort(
            key=lambda thread: thread.created_at
        )

        # ====================================================
        # 전체 포스트 처리
        # ====================================================

        checked_count = 0
        changed_count = 0
        skipped_count = 0
        failed_count = 0

        for thread in threads:
            checked_count += 1

            try:
                changed = (
                    await self._process_thread(
                        thread
                    )
                )

                if changed:
                    changed_count += 1

                    # Rate Limit 방지
                    await asyncio.sleep(1.5)

                else:
                    skipped_count += 1

            except discord.HTTPException as e:
                failed_count += 1

                print(
                    "[Forum Sync] 처리 실패: "
                    f"{thread.id} / {e}"
                )

        # ====================================================
        # 결과
        # ====================================================

        await interaction.followup.send(
            "✅ **포럼 제목 정리를 완료했습니다.**\n\n"
            f"📋 검사: **{checked_count}개**\n"
            f"✏️ 변경: **{changed_count}개**\n"
            f"⏭️ 변경 없음: **{skipped_count}개**\n"
            f"❌ 실패: **{failed_count}개**",
            ephemeral=True,
        )


# ============================================================
# Cog Setup
# ============================================================

async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        Forum(bot)
    )