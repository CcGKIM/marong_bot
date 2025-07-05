# support_utils.py
import discord
from discord import PermissionOverwrite
from discord.utils import get as dc_get
from discord.ext import tasks
from config.constants import ALLOWED_CHANNEL_IDS, BLOCKED_WORDS, INJECTION_KEYWORDS, THANK_WORDS, FAQ_2

channel_activity: dict[int, discord.utils.MISSING] = {}

async def create_channel(
    guild: discord.Guild,
    author: discord.Member,
    include_admin: bool = False
) -> discord.TextChannel:
    """운영진 포함 여부에 따라 1:1 문의 채널을 생성하거나 이미 있으면 반환."""
    name = f"문의-{author.name}" + (f"-{author.discriminator}" if include_admin else "")
    existing = discord.utils.get(guild.channels, name=name)
    if existing:
        return existing

    overwrites = {
        guild.default_role: PermissionOverwrite(read_messages=False),
        author: PermissionOverwrite(read_messages=True, send_messages=True),
    }
    if include_admin:
        admin = dc_get(guild.roles, name="운영진")
        overwrites[admin] = PermissionOverwrite(read_messages=True, send_messages=True)
    else:
        overwrites[guild.me] = PermissionOverwrite(read_messages=True, send_messages=True)

    new_ch = await guild.create_text_channel(
        name, overwrites=overwrites, reason="유저 1:1 문의 채널 생성"
    )
    ALLOWED_CHANNEL_IDS.add(new_ch.id)
    channel_activity[new_ch.id] = discord.utils.utcnow()
    return new_ch

def is_filtered(content: str) -> bool:
    """욕설, 보안키워드, 감사 인사, 도움말 여부를 검사."""
    if any(b in content for b in BLOCKED_WORDS):
        return True
    if any(k in content for k in INJECTION_KEYWORDS):
        return True
    if any(w in content for w in THANK_WORDS):
        return True
    if content.startswith(("도움","헬프")) or content == "help":
        return True
    return False

async def send_help(channel: discord.TextChannel):
    """FAQ_2 키워드를 25개씩 Embed로 나눠 전송."""
    items = list(FAQ_2.items())
    for i in range(0, len(items), 25):
        chunk = items[i : i + 25]
        embed = discord.Embed(
            title="마롱 사용 가이드" if i == 0 else "📄 추가 키워드 안내",
            description="아래 키워드를 입력하면 관련 정보를 알려드려요:",
            color=0x6cc644
        )
        for k, v in chunk:
            short = v if len(v) <= 1024 else v[:1020] + "..."
            embed.add_field(name=k, value=short, inline=False)
        await channel.send(embed=embed)
        
async def get_notice_channel_content(guild, notice_channel_id: int) -> str:
    channel = guild.get_channel(notice_channel_id)

    if not isinstance(channel, discord.TextChannel):
        return "❗️공지사항 채널을 찾을 수 없습니다."

    messages = [message async for message in channel.history(limit=50)]
    messages.reverse()

    if not messages:
        return "📭 공지사항이 아직 없습니다."

    return "\n".join([
        f"{m.created_at.strftime('%Y-%m-%d')}: {m.content or '[첨부파일/임베드 포함]'}"
        for m in messages if m.content or m.attachments
    ]) or "📭 공지사항이 아직 없습니다."