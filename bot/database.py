import aiosqlite
from pathlib import Path
from typing import Optional


DB_PATH = Path("data/bot.db")


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS translation_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                UNIQUE(guild_id, name)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS translation_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                language TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                webhook_url TEXT,
                UNIQUE(group_id, language),
                UNIQUE(group_id, channel_id),
                FOREIGN KEY(group_id)
                    REFERENCES translation_groups(id)
                    ON DELETE CASCADE
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS message_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                source_channel_id INTEGER NOT NULL,
                target_message_id INTEGER NOT NULL,
                target_channel_id INTEGER NOT NULL,
                FOREIGN KEY(group_id)
                    REFERENCES translation_groups(id)
                    ON DELETE CASCADE
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS welcome_settings (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS welcome_messages (
                guild_id INTEGER NOT NULL,
                language TEXT NOT NULL,
                content TEXT NOT NULL,
                PRIMARY KEY(guild_id, language)
            )
        """)

        await db.commit()


# =========================================================
# GROUP
# =========================================================

async def create_group(guild_id: int, name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cursor = await db.execute(
                """
                INSERT INTO translation_groups (guild_id, name)
                VALUES (?, ?)
                """,
                (guild_id, name)
            )

            await db.commit()

            return cursor.lastrowid

        except aiosqlite.IntegrityError:
            return None


async def get_groups(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT id, name, enabled
            FROM translation_groups
            WHERE guild_id = ?
            ORDER BY id
            """,
            (guild_id,)
        )

        return await cursor.fetchall()


async def get_group(guild_id: int, name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT id, name, enabled
            FROM translation_groups
            WHERE guild_id = ? AND name = ?
            """,
            (guild_id, name)
        )

        return await cursor.fetchone()


async def rename_group(
    guild_id: int,
    old_name: str,
    new_name: str
):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cursor = await db.execute(
                """
                UPDATE translation_groups
                SET name = ?
                WHERE guild_id = ? AND name = ?
                """,
                (new_name, guild_id, old_name)
            )

            await db.commit()

            return cursor.rowcount > 0

        except aiosqlite.IntegrityError:
            return False


async def delete_group(
    guild_id: int,
    name: str
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")

        cursor = await db.execute(
            """
            DELETE FROM translation_groups
            WHERE guild_id = ? AND name = ?
            """,
            (guild_id, name)
        )

        await db.commit()

        return cursor.rowcount > 0


async def toggle_group(
    guild_id: int,
    name: str
):
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute(
            """
            UPDATE translation_groups
            SET enabled = CASE enabled
                WHEN 1 THEN 0
                ELSE 1
            END
            WHERE guild_id = ? AND name = ?
            """,
            (guild_id, name)
        )

        await db.commit()

        if cursor.rowcount == 0:
            return None

        cursor = await db.execute(
            """
            SELECT enabled
            FROM translation_groups
            WHERE guild_id = ? AND name = ?
            """,
            (guild_id, name)
        )

        row = await cursor.fetchone()

        return bool(row[0])


# =========================================================
# TRANSLATION CHANNEL
# =========================================================

async def set_translation_channel(
    guild_id: int,
    group_name: str,
    language: str,
    channel_id: int,
    webhook_url: Optional[str] = None
):
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute(
            """
            SELECT id
            FROM translation_groups
            WHERE guild_id = ? AND name = ?
            """,
            (guild_id, group_name)
        )

        group = await cursor.fetchone()

        if group is None:
            return "GROUP_NOT_FOUND"

        group_id = group[0]

        cursor = await db.execute(
            """
            SELECT id
            FROM translation_channels
            WHERE group_id = ? AND language = ?
            """,
            (group_id, language)
        )

        existing = await cursor.fetchone()

        try:

            if existing is None:

                await db.execute(
                    """
                    INSERT INTO translation_channels
                    (
                        group_id,
                        language,
                        channel_id,
                        webhook_url
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        group_id,
                        language,
                        channel_id,
                        webhook_url
                    )
                )

                result = "ADDED"

            else:

                await db.execute(
                    """
                    UPDATE translation_channels
                    SET
                        channel_id = ?,
                        webhook_url = ?
                    WHERE group_id = ?
                      AND language = ?
                    """,
                    (
                        channel_id,
                        webhook_url,
                        group_id,
                        language
                    )
                )

                result = "UPDATED"

            await db.commit()

            return result

        except aiosqlite.IntegrityError:
            return "DUPLICATE"


async def remove_translation_channel(
    guild_id: int,
    group_name: str,
    language: str
):
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute(
            """
            SELECT id
            FROM translation_groups
            WHERE guild_id = ? AND name = ?
            """,
            (guild_id, group_name)
        )

        group = await cursor.fetchone()

        if group is None:
            return "GROUP_NOT_FOUND"

        group_id = group[0]

        cursor = await db.execute(
            """
            DELETE FROM translation_channels
            WHERE group_id = ? AND language = ?
            """,
            (group_id, language)
        )

        await db.commit()

        if cursor.rowcount == 0:
            return "CHANNEL_NOT_FOUND"

        return "SUCCESS"


async def get_translation_channels(
    guild_id: int,
    group_name: str
):
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute(
            """
            SELECT
                language,
                channel_id,
                webhook_url
            FROM translation_channels
            WHERE group_id = (
                SELECT id
                FROM translation_groups
                WHERE guild_id = ? AND name = ?
            )
            ORDER BY id
            """,
            (guild_id, group_name)
        )

        return await cursor.fetchall()


# =========================================================
# TRANSLATION SOURCE
# =========================================================

async def get_translation_source(
    guild_id: int,
    channel_id: int
):
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute(
            """
            SELECT
                g.id,
                g.name,
                g.enabled,
                tc.language
            FROM translation_channels tc
            INNER JOIN translation_groups g
                ON tc.group_id = g.id
            WHERE g.guild_id = ?
              AND tc.channel_id = ?
            """,
            (guild_id, channel_id)
        )

        row = await cursor.fetchone()

        if row is None:
            return None

        return {
            "group_id": row[0],
            "group_name": row[1],
            "enabled": bool(row[2]),
            "language": row[3],
        }


async def get_translation_targets(
    group_id: int,
    source_language: str
):
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute(
            """
            SELECT
                language,
                channel_id,
                webhook_url
            FROM translation_channels
            WHERE group_id = ?
              AND language != ?
            ORDER BY id
            """,
            (group_id, source_language)
        )

        return await cursor.fetchall()


# =========================================================
# MESSAGE MAPPING
# =========================================================

async def save_message_mapping(
    group_id: int,
    source_message_id: int,
    source_channel_id: int,
    target_message_id: int,
    target_channel_id: int
):
    """
    원본 메시지와 번역 메시지를 연결합니다.
    """

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute(
            """
            INSERT INTO message_mapping
            (
                group_id,
                source_message_id,
                source_channel_id,
                target_message_id,
                target_channel_id
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                group_id,
                source_message_id,
                source_channel_id,
                target_message_id,
                target_channel_id
            )
        )

        await db.commit()


async def get_message_mappings(
    source_message_id: int,
    source_channel_id: int
):
    """
    하나의 원본 메시지가 만들어낸
    모든 번역 메시지를 가져옵니다.

    반환:
        [
            (
                group_id,
                target_message_id,
                target_channel_id,
                webhook_url,
                target_language
            ),
            ...
        ]
    """

    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute(
            """
            SELECT
                mm.group_id,
                mm.target_message_id,
                mm.target_channel_id,
                tc.webhook_url,
                tc.language
            FROM message_mapping mm
            INNER JOIN translation_channels tc
                ON mm.group_id = tc.group_id
                AND mm.target_channel_id = tc.channel_id
            WHERE mm.source_message_id = ?
              AND mm.source_channel_id = ?
            ORDER BY mm.id
            """,
            (
                source_message_id,
                source_channel_id
            )
        )

        return await cursor.fetchall()


async def get_source_message_mapping(
    target_message_id: int,
    target_channel_id: int
):
    """번역 메시지에서 대응되는 원본 메시지를 찾습니다."""

    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute(
            """
            SELECT
                group_id,
                source_message_id,
                source_channel_id
            FROM message_mapping
            WHERE target_message_id = ?
              AND target_channel_id = ?
            ORDER BY id
            LIMIT 1
            """,
            (
                target_message_id,
                target_channel_id
            )
        )

        return await cursor.fetchone()


async def delete_message_mappings(
    source_message_id: int,
    source_channel_id: int
):
    """
    원본 메시지에 연결된 매핑 정보를 삭제합니다.
    """

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute(
            """
            DELETE FROM message_mapping
            WHERE source_message_id = ?
              AND source_channel_id = ?
            """,
            (
                source_message_id,
                source_channel_id
            )
        )

        await db.commit()


# =========================================================
# WELCOME
# =========================================================

async def set_welcome_settings(
    guild_id: int,
    channel_id: int
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO welcome_settings (guild_id, channel_id, enabled)
            VALUES (?, ?, 1)
            ON CONFLICT(guild_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                enabled = 1
            """,
            (guild_id, channel_id)
        )
        await db.commit()


async def get_welcome_settings(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT channel_id, enabled
            FROM welcome_settings
            WHERE guild_id = ?
            """,
            (guild_id,)
        )
        row = await cursor.fetchone()

        if row is None:
            return None

        return {
            "channel_id": row[0],
            "enabled": bool(row[1]),
        }


async def disable_welcome(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE welcome_settings
            SET enabled = 0
            WHERE guild_id = ?
            """,
            (guild_id,)
        )
        await db.commit()


async def set_welcome_message(
    guild_id: int,
    language: str,
    content: str
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO welcome_messages (guild_id, language, content)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, language) DO UPDATE SET
                content = excluded.content
            """,
            (guild_id, language, content)
        )
        await db.commit()


async def get_welcome_messages(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT language, content
            FROM welcome_messages
            WHERE guild_id = ?
            ORDER BY language
            """,
            (guild_id,)
        )
        return await cursor.fetchall()
