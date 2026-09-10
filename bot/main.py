import asyncio

import discord
from discord.ext import commands

from bot.config import DISCORD_TOKEN
from bot.database import init_db


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


@bot.event
async def on_ready():
    print(f"로그인 완료: {bot.user}")
    print(f"Bot ID: {bot.user.id}")

    try:
        synced = await bot.tree.sync()
        print(f"Slash Commands 동기화 완료: {len(synced)}개")
    except Exception as e:
        print(f"Slash Commands 동기화 실패: {e}")


async def main():
    await init_db()

    await bot.load_extension(
        "bot.cogs.translation"
    )

    await bot.load_extension(
        "bot.cogs.welcome"
    )

    await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
