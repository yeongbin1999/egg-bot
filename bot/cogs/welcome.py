import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.database import (
    disable_welcome,
    get_welcome_messages,
    get_welcome_settings,
    set_welcome_message,
    set_welcome_settings,
)


LANGUAGE_CHOICES = [
    app_commands.Choice(name="🇰🇷 한국어", value="ko"),
    app_commands.Choice(name="🇺🇸 English", value="en"),
    app_commands.Choice(name="🇯🇵 日本語", value="ja"),
    app_commands.Choice(name="🇹🇼 繁體中文 (台灣)", value="zh-TW"),
]

LANGUAGE_NAMES = {
    "ko": "🇰🇷 한국어",
    "en": "🇺🇸 English",
    "ja": "🇯🇵 日本語",
    "zh-TW": "🇹🇼 繁體中文",
}

DEFAULT_MESSAGES = {
    "ko": (
        "환영합니다, {user}님!\n"
        "Discord 별명을 정해진 형식으로 변경해주세요.\n"
        "운영자가 확인한 뒤 필요한 권한을 수동으로 부여합니다."
    ),
    "en": (
        "Welcome, {user}!\n"
        "Please change your Discord nickname to the required format.\n"
        "A staff member will review it and grant the necessary access manually."
    ),
    "ja": (
        "{user}さん、ようこそ！\n"
        "指定された形式にDiscordのニックネームを変更してください。\n"
        "確認後、スタッフが必要な権限を手動で付与します。"
    ),
    "zh-TW": (
        "歡迎加入，{user}！\n"
        "請將 Discord 暱稱修改為指定格式。\n"
        "管理員確認後會手動授予必要的權限。"
    ),
}


def render_message(template: str, member: discord.Member) -> str:
    return (
        template
        .replace("\r\n", "\n")
        .replace("\\n", "\n")
        .replace("{user}", member.mention)
        .replace("{name}", member.display_name)
    )


class WelcomeMessageModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "Welcome",
        language_choice: app_commands.Choice[str],
        initial_content: str = ""
    ):
        super().__init__(title=f"{language_choice.name} 환영 메시지 설정")
        self.cog = cog
        self.language_choice = language_choice

        formatted_initial = (
            initial_content
            .replace("\r\n", "\n")
            .replace("\\n", "\n")
        )

        self.message_input = discord.ui.TextInput(
            label="환영 메시지 내용",
            style=discord.TextStyle.paragraph,
            placeholder="환영 메시지를 입력하세요.\n{user}=유저 멘션, {name}=유저 별명",
            default=formatted_initial,
            max_length=2000,
            required=True
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        content = (
            self.message_input.value
            .replace("\r\n", "\n")
            .replace("\\n", "\n")
            .strip()
        )
        if not content:
            await interaction.response.send_message(
                "메시지를 입력해주세요.",
                ephemeral=True
            )
            return

        if len(content) > 2000:
            await interaction.response.send_message(
                "메시지는 2,000자 이하로 입력해주세요.",
                ephemeral=True
            )
            return

        await set_welcome_message(
            interaction.guild.id,
            self.language_choice.value,
            content
        )
        await interaction.response.send_message(
            f"✅ **{self.language_choice.name} 환영 메시지를 저장했습니다!**\n\n"
            f"**[적용된 메시지 미리보기]**\n```\n{content}\n```",
            ephemeral=True
        )


class WelcomeLanguageView(discord.ui.View):
    def __init__(
        self,
        cog: "Welcome",
        selected_language: Optional[str] = None,
        disabled: bool = False
    ):
        super().__init__(timeout=None)
        self.cog = cog

        if disabled:
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
                    if child.custom_id == f"welcome:lang:{selected_language}":
                        child.style = discord.ButtonStyle.success
                    else:
                        child.style = discord.ButtonStyle.secondary

    @discord.ui.button(
        label="한국어",
        emoji="🇰🇷",
        style=discord.ButtonStyle.secondary,
        custom_id="welcome:lang:ko"
    )
    async def btn_ko(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.cog.handle_language_selection(interaction, "ko")

    @discord.ui.button(
        label="English",
        emoji="🇺🇸",
        style=discord.ButtonStyle.secondary,
        custom_id="welcome:lang:en"
    )
    async def btn_en(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.cog.handle_language_selection(interaction, "en")

    @discord.ui.button(
        label="日本語",
        emoji="🇯🇵",
        style=discord.ButtonStyle.secondary,
        custom_id="welcome:lang:ja"
    )
    async def btn_ja(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.cog.handle_language_selection(interaction, "ja")

    @discord.ui.button(
        label="繁體中文",
        emoji="🇹🇼",
        style=discord.ButtonStyle.secondary,
        custom_id="welcome:lang:zh-TW"
    )
    async def btn_zh(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.cog.handle_language_selection(interaction, "zh-TW")


class Welcome(commands.Cog):
    welcome = app_commands.Group(
        name="welcome",
        description="신규 유저 환영 메시지를 설정합니다."
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def handle_language_selection(
        self,
        interaction: discord.Interaction,
        language: str
    ):
        if interaction.guild is None or interaction.user is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        # 환영 메시지 대상자(멘션된 본인)만 누를 수 있도록 검증
        target_ids = set()
        if interaction.message:
            if interaction.message.mentions:
                target_ids.update(m.id for m in interaction.message.mentions)
            if interaction.message.content:
                raw_ids = re.findall(r"<@!?([0-9]+)>", interaction.message.content)
                target_ids.update(int(uid) for uid in raw_ids)

        if target_ids and interaction.user.id not in target_ids:
            await interaction.response.send_message(
                "❌ 환영 대상 멤버 본인만 언어를 선택할 수 있습니다. / Only the welcomed member can select.",
                ephemeral=True
            )
            return

        messages = dict(await get_welcome_messages(interaction.guild.id))
        template = messages.get(language, DEFAULT_MESSAGES[language])
        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "서버 멤버만 선택할 수 있습니다.",
                ephemeral=True
            )
            return

        # 선택한 버튼을 초록색으로 강조하고 모든 버튼을 비활성화하여 선택 완료 표시
        updated_view = WelcomeLanguageView(
            self,
            selected_language=language,
            disabled=True
        )

        await interaction.response.edit_message(
            content=render_message(template, member),
            view=updated_view
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        settings = await get_welcome_settings(member.guild.id)
        if settings is None or not settings["enabled"]:
            return

        channel = member.guild.get_channel(settings["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            await channel.send(
                f"🎉 {member.mention}님, 환영합니다! / Welcome, {member.mention}!\n"
                "아래에서 사용하실 언어를 선택해주세요. / Please select your language below.",
                view=WelcomeLanguageView(self),
                allowed_mentions=discord.AllowedMentions(users=True)
            )
        except discord.Forbidden:
            print(f"Welcome 메시지 권한이 없습니다: #{channel.name}")
        except discord.HTTPException as e:
            print(f"Welcome 메시지 전송 실패: {e}")

    @welcome.command(
        name="setup",
        description="환영 메시지를 보낼 채널을 설정합니다."
    )
    @app_commands.describe(channel="환영 메시지를 보낼 채널")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        await set_welcome_settings(interaction.guild.id, channel.id)
        await interaction.response.send_message(
            f"✅ 환영 채널을 {channel.mention}으로 설정했습니다.",
            ephemeral=True
        )

    @welcome.command(
        name="message",
        description="언어별 환영 메시지를 설정합니다."
    )
    @app_commands.describe(
        language="설정할 언어 선택"
    )
    @app_commands.choices(language=LANGUAGE_CHOICES)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def message(
        self,
        interaction: discord.Interaction,
        language: app_commands.Choice[str]
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        messages = dict(await get_welcome_messages(interaction.guild.id))
        current_content = messages.get(
            language.value,
            DEFAULT_MESSAGES.get(language.value, "")
        )
        modal = WelcomeMessageModal(self, language, current_content)
        await interaction.response.send_modal(modal)

    @welcome.command(
        name="disable",
        description="환영 메시지를 비활성화합니다."
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        await disable_welcome(interaction.guild.id)
        await interaction.response.send_message(
            "✅ 환영 메시지를 비활성화했습니다.",
            ephemeral=True
        )

    @welcome.command(
        name="test",
        description="현재 설정으로 환영 메시지를 테스트합니다."
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def test(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        settings = await get_welcome_settings(interaction.guild.id)
        if settings is None or not settings["enabled"]:
            await interaction.response.send_message(
                "먼저 `/welcome setup`으로 welcome 채널을 설정해주세요.",
                ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(settings["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "설정된 welcome 채널을 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        try:
            test_message = await channel.send(
                f"🧪 {interaction.user.mention}님, 웰컴 메시지 테스트입니다. / Welcome message test.\n"
                "아래에서 사용하실 언어를 선택해보세요. / Please select your language below.",
                view=WelcomeLanguageView(self),
                allowed_mentions=discord.AllowedMentions(users=True)
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ welcome 채널에 메시지를 보낼 권한이 없습니다.",
                ephemeral=True
            )
            return
        except discord.HTTPException as e:
            print(f"Welcome 테스트 전송 실패: {e}")
            await interaction.response.send_message(
                "❌ 테스트 메시지 전송 중 오류가 발생했습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ 테스트 메시지를 전송했습니다: {test_message.jump_url}",
            ephemeral=True
        )

    @welcome.command(
        name="config",
        description="환영 메시지 설정 현황과 언어별 등록된 메시지를 확인합니다."
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        settings = await get_welcome_settings(interaction.guild.id)
        if settings is None:
            await interaction.response.send_message(
                "아직 환영 채널이 설정되지 않았습니다. `/welcome setup`으로 먼저 채널을 설정해주세요.",
                ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(settings["channel_id"])
        channel_text = channel.mention if channel else f"채널 없음 (ID: {settings['channel_id']})"
        messages = dict(await get_welcome_messages(interaction.guild.id))

        is_enabled = bool(settings["enabled"])
        embed = discord.Embed(
            title="⚙️ 환영 메시지 설정 현황",
            color=discord.Color.green() if is_enabled else discord.Color.red()
        )
        embed.add_field(
            name="📢 환영 채널",
            value=channel_text,
            inline=True
        )
        embed.add_field(
            name="⚡ 상태",
            value="🟢 활성화" if is_enabled else "🔴 비활성화",
            inline=True
        )

        for lang_code, lang_name in LANGUAGE_NAMES.items():
            is_custom = lang_code in messages
            content = messages.get(
                lang_code,
                DEFAULT_MESSAGES.get(lang_code, "메시지 없음")
            )
            content = content.replace("\\n", "\n").strip()

            badge = "*(사용자 지정)*" if is_custom else "*(기본값)*"

            if len(content) > 1000:
                display_content = content[:997] + "..."
            else:
                display_content = content

            embed.add_field(
                name=f"{lang_name} {badge}",
                value=f"```\n{display_content}\n```",
                inline=False
            )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            message = "❌ 이 명령어는 서버 관리 권한이 필요합니다."
        else:
            print(f"Welcome Command Error: {error}")
            message = "❌ 환영 설정 중 오류가 발생했습니다."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot):
    cog = Welcome(bot)
    await bot.add_cog(cog)
    bot.add_view(WelcomeLanguageView(cog))
