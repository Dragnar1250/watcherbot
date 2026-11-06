"""Ortak yardımcı fonksiyonlar."""
import re
import time
from datetime import timedelta

import discord

RENK = discord.Color.from_rgb(88, 101, 242)
YESIL = discord.Color.green()
KIRMIZI = discord.Color.red()
TURUNCU = discord.Color.orange()

DEGISKEN_ACIKLAMA = (
    "`{kullanici}` etiket, `{isim}` kullanıcı adı, `{sunucu}` sunucu adı, "
    "`{uye_sayisi}` üye sayısı, `{seviye}` seviye (sadece seviye mesajında)"
)


def format_message(template: str, member: discord.abc.User, guild: discord.Guild | None = None, **extra) -> str:
    guild = guild or getattr(member, "guild", None)
    text = (
        template.replace("{kullanici}", member.mention)
        .replace("{isim}", member.display_name)
        .replace("{sunucu}", guild.name if guild else "")
        .replace("{uye_sayisi}", str(guild.member_count) if guild else "")
    )
    for k, v in extra.items():
        text = text.replace("{" + k + "}", str(v))
    return text


_SURE = {"s": 1, "sn": 1, "dk": 60, "m": 60, "sa": 3600, "h": 3600, "g": 86400, "d": 86400, "hf": 604800, "w": 604800}


def parse_duration(text: str) -> timedelta | None:
    """'10dk', '1sa', '2g', '1sa30dk', '10m', '1h' gibi süreleri çözer."""
    text = text.lower().replace(" ", "")
    parts = re.findall(r"(\d+)(sn|dk|sa|hf|s|m|h|g|d|w)", text)
    if not parts or "".join(n + u for n, u in parts) != text:
        return None
    seconds = sum(int(n) * _SURE[u] for n, u in parts)
    return timedelta(seconds=seconds) if seconds > 0 else None


def human_duration(td: timedelta) -> str:
    s = int(td.total_seconds())
    out = []
    for name, size in (("gün", 86400), ("saat", 3600), ("dakika", 60), ("saniye", 1)):
        if s >= size:
            out.append(f"{s // size} {name}")
            s %= size
    return " ".join(out) or "0 saniye"


def ok(text: str) -> discord.Embed:
    return discord.Embed(description=f"✅ {text}", color=YESIL)


def err(text: str) -> discord.Embed:
    return discord.Embed(description=f"❌ {text}", color=KIRMIZI)


def can_act(actor: discord.Member, target: discord.Member) -> str | None:
    """Rol hiyerarşisini kontrol eder. Sorun varsa hata metni döner."""
    guild = actor.guild
    if target == guild.owner:
        return "Sunucu sahibine bu işlemi yapamazsın."
    if target == actor:
        return "Bunu kendine yapamazsın."
    if actor != guild.owner and target.top_role >= actor.top_role:
        return "Bu üyenin rolü seninkiyle aynı ya da daha yüksek."
    if target.top_role >= guild.me.top_role:
        return "Bu üyenin rolü botun rolünden yüksek. Bot rolünü rol listesinde yukarı taşı."
    return None


async def send_log(bot, guild: discord.Guild, embed: discord.Embed, file: discord.File | None = None):
    channel_id = bot.db.get(guild.id, "log_channel")
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if channel is None:
        return
    try:
        await channel.send(embed=embed, file=file) if file else await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass


# ---------- Botun kendi yaptığı işlemler (çift log olmasın diye) ----------
# Bot bir işlemi kendisi yapıp ayrıntılı log attığında (ör. /ban → "Yasaklama"), Discord'un aynı işlem için
# gönderdiği genel olay (ör. "Üye yasaklandı") log modülünde atlanır.
_ISLEM_SURE = {"ban": 30, "unban": 30, "timeout": 30, "msgdel": 30, "roles": 8}


def mark_action(bot, kind: str, guild_id: int, target_id: int):
    """İşlemden ÖNCE çağrılır (Discord olayı, işlem bitmeden gelebilir)."""
    actions = bot.__dict__.setdefault("_own_actions", {})
    now = time.monotonic()
    for k in [k for k, t in actions.items() if t < now]:
        del actions[k]
    actions[(kind, guild_id, target_id)] = now + _ISLEM_SURE.get(kind, 15)


def is_own_action(bot, kind: str, guild_id: int, target_id: int) -> bool:
    t = getattr(bot, "_own_actions", {}).get((kind, guild_id, target_id))
    return t is not None and t >= time.monotonic()
