"""Ayrıntılı log sistemi."""
import io
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.helpers import KIRMIZI, RENK, TURUNCU, YESIL, is_own_action, ok, send_log


def _cut(text: str | None, n: int = 1000) -> str:
    if not text:
        return "*(boş)*"
    return text if len(text) <= n else text[: n - 3] + "..."


def _ts() -> datetime:
    return datetime.now(timezone.utc)


class Log(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    grup = app_commands.Group(name="log", description="Log sistemi ayarları",
                              default_permissions=discord.Permissions(manage_guild=True), guild_only=True)

    @grup.command(name="kanal", description="Logların gönderileceği kanal")
    async def kanal(self, i: discord.Interaction, kanal: discord.TextChannel):
        self.bot.db.set(i.guild_id, "log_channel", kanal.id)
        await i.response.send_message(embed=ok(f"Loglar artık {kanal.mention} kanalına gidecek."))

    @grup.command(name="kapat", description="Log sistemini kapat")
    async def kapat(self, i: discord.Interaction):
        self.bot.db.set(i.guild_id, "log_channel", None)
        await i.response.send_message(embed=ok("Log sistemi kapatıldı."))

    @grup.command(name="yoksay-kanal", description="Bu kanalın (ya da kategorinin) mesaj silme/düzenleme logları tutulmasın / tekrar tutulsun")
    @app_commands.describe(kanal="Yazı kanalı, ses kanalı (sohbeti) ya da kategori. Tekrar seçersen loglar geri açılır")
    async def yoksay_kanal(self, i: discord.Interaction,
                           kanal: discord.TextChannel | discord.VoiceChannel | discord.StageChannel
                           | discord.ForumChannel | discord.CategoryChannel):
        ids = set(self.bot.db.get(i.guild_id, "log_ignored_channels", []))
        tur = "kategorisindeki kanalların" if isinstance(kanal, discord.CategoryChannel) else "kanalının"
        if kanal.id in ids:
            ids.remove(kanal.id)
            msg = f"**{kanal.name}** {tur} mesaj logları tekrar tutulacak."
        else:
            ids.add(kanal.id)
            msg = f"**{kanal.name}** {tur} mesaj silme/düzenleme logları artık tutulmayacak."
        self.bot.db.set(i.guild_id, "log_ignored_channels", list(ids))
        liste = ", ".join(f"<#{c}>" for c in ids) or "yok"
        await i.response.send_message(embed=ok(f"{msg}\nMesaj logu tutulmayanlar: {liste}"))

    def ignored(self, channel) -> bool:
        """Mesaj logları bu kanalda kapalı mı? Kanal, kategorisi, alt başlıksa ana kanalı ve onun kategorisi kontrol edilir."""
        if channel is None or getattr(channel, "guild", None) is None:
            return False
        ids = set(self.bot.db.get(channel.guild.id, "log_ignored_channels", []))
        if not ids:
            return False
        chain = [channel]
        parent = getattr(channel, "parent", None)   # alt başlık (thread) ise ana kanal
        if parent is not None:
            chain.append(parent)
        for ch in list(chain):
            cid = getattr(ch, "category_id", None)
            if cid:
                chain.append(type("C", (), {"id": cid})())
        return any(getattr(ch, "id", None) in ids for ch in chain)

    async def log(self, guild, embed, file=None):
        if guild is None:
            return
        embed.timestamp = _ts()
        await send_log(self.bot, guild, embed, file)

    # ---------- mesajlar ----------
    @commands.Cog.listener()
    async def on_message_delete(self, m: discord.Message):
        if m.guild is None or m.author.bot or self.ignored(m.channel):
            return
        if is_own_action(self.bot, "msgdel", m.guild.id, m.id):
            return  # otomod sildi, kendi logunu attı
        e = discord.Embed(title="🗑️ Mesaj silindi", color=KIRMIZI)
        e.set_author(name=str(m.author), icon_url=m.author.display_avatar.url)
        e.add_field(name="Kanal", value=m.channel.mention)
        e.add_field(name="Yazan", value=m.author.mention)
        e.add_field(name="İçerik", value=_cut(m.content), inline=False)
        if m.attachments:
            e.add_field(name="Ekler", value="\n".join(a.filename for a in m.attachments)[:1000], inline=False)
        e.set_footer(text=f"Kullanıcı ID: {m.author.id}")
        await self.log(m.guild, e)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.guild is None or after.author.bot or before.content == after.content or self.ignored(after.channel):
            return
        e = discord.Embed(title="✏️ Mesaj düzenlendi", color=TURUNCU, url=after.jump_url)
        e.set_author(name=str(after.author), icon_url=after.author.display_avatar.url)
        e.add_field(name="Kanal", value=after.channel.mention)
        e.add_field(name="Yazan", value=after.author.mention)
        e.add_field(name="Önce", value=_cut(before.content), inline=False)
        e.add_field(name="Sonra", value=_cut(after.content), inline=False)
        await self.log(after.guild, e)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        if not messages or messages[0].guild is None or self.ignored(messages[0].channel):
            return
        ch = messages[0].channel
        lines = [f"[{m.created_at:%d.%m.%Y %H:%M}] {m.author}: {m.content}" for m in sorted(messages, key=lambda x: x.id)]
        f = discord.File(io.BytesIO("\n".join(lines).encode("utf-8")), filename="silinen_mesajlar.txt")
        e = discord.Embed(title="🧹 Toplu mesaj silme", description=f"{ch.mention} kanalında **{len(messages)}** mesaj silindi.",
                          color=KIRMIZI)
        await self.log(messages[0].guild, e, f)

    # ---------- üyeler ----------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        created = int(member.created_at.timestamp())
        e = discord.Embed(title="📥 Üye katıldı", description=f"{member.mention} ({member})", color=YESIL)
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Hesap oluşturulma", value=f"<t:{created}:F> (<t:{created}:R>)")
        e.set_footer(text=f"ID: {member.id} • Üye sayısı: {member.guild.member_count}")
        # Davet bilgisi ayrı log yerine bu loga eklenir
        davet = self.bot.get_cog("Davet")
        if davet is not None:
            info = await davet.wait_info(member)
            if info is not None:
                if info["code"]:
                    text = f"`{info['code']}`"
                    if info["inviter"]:
                        text += f" • davet eden <@{info['inviter']}>"
                else:
                    text = "Belirlenemedi (aynı anda birden fazla giriş ya da geçici davet)"
                e.add_field(name="Davet", value=text, inline=False)
                if info["roles"]:
                    e.add_field(name="Davet rolleri", value=" ".join(info["roles"]), inline=False)
        await self.log(member.guild, e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        roles = [r.mention for r in member.roles[1:]]
        e = discord.Embed(title="📤 Üye ayrıldı", description=f"{member.mention} ({member})", color=KIRMIZI)
        e.set_thumbnail(url=member.display_avatar.url)
        if member.joined_at:
            e.add_field(name="Katılma", value=f"<t:{int(member.joined_at.timestamp())}:R>")
        e.add_field(name="Roller", value=" ".join(roles)[:1000] or "Yok", inline=False)
        e.set_footer(text=f"ID: {member.id}")
        await self.log(member.guild, e)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick != after.nick:
            e = discord.Embed(title="🏷️ Takma ad değişti", description=after.mention, color=RENK)
            e.add_field(name="Önce", value=before.nick or "*(yok)*")
            e.add_field(name="Sonra", value=after.nick or "*(yok)*")
            await self.log(after.guild, e)
        if before.roles != after.roles and not is_own_action(self.bot, "roles", after.guild.id, after.id):
            added = [r.mention for r in after.roles if r not in before.roles]
            removed = [r.mention for r in before.roles if r not in after.roles]
            e = discord.Embed(title="🎭 Roller güncellendi", description=after.mention, color=RENK)
            if added:
                e.add_field(name="Eklenen", value=" ".join(added)[:1000])
            if removed:
                e.add_field(name="Alınan", value=" ".join(removed)[:1000])
            await self.log(after.guild, e)
        if before.timed_out_until != after.timed_out_until and after.timed_out_until \
                and not is_own_action(self.bot, "timeout", after.guild.id, after.id):
            e = discord.Embed(title="🔇 Üye susturuldu", description=after.mention, color=TURUNCU)
            e.add_field(name="Bitiş", value=f"<t:{int(after.timed_out_until.timestamp())}:R>")
            await self.log(after.guild, e)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        if is_own_action(self.bot, "ban", guild.id, user.id):
            return  # /ban kendi ayrıntılı logunu attı
        e = discord.Embed(title="🔨 Üye yasaklandı", description=f"{user.mention} ({user})", color=KIRMIZI)
        e.set_footer(text=f"ID: {user.id}")
        await self.log(guild, e)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        if is_own_action(self.bot, "unban", guild.id, user.id):
            return
        e = discord.Embed(title="🔓 Yasak kaldırıldı", description=f"{user.mention} ({user})", color=YESIL)
        await self.log(guild, e)

    # ---------- ses ----------
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if before.channel == after.channel:
            return
        if before.channel is None:
            e = discord.Embed(title="🔊 Ses kanalına girdi", description=f"{member.mention} → {after.channel.mention}", color=YESIL)
        elif after.channel is None:
            e = discord.Embed(title="🔈 Ses kanalından çıktı", description=f"{member.mention} ← {before.channel.mention}", color=KIRMIZI)
        else:
            e = discord.Embed(title="🔀 Ses kanalı değiştirdi",
                              description=f"{member.mention}: {before.channel.mention} → {after.channel.mention}", color=RENK)
        await self.log(member.guild, e)

    # ---------- kanallar, kategoriler ve roller ----------
    async def who(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int) -> str | None:
        """Denetim kaydından işlemi kimin yaptığını bulur (bot 'Denetim Kaydını Görüntüle' yetkisine sahip olmalı)."""
        try:
            async for entry in guild.audit_logs(limit=6, action=action):
                if entry.target and getattr(entry.target, "id", None) == target_id and \
                        (discord.utils.utcnow() - entry.created_at).total_seconds() < 20:
                    return entry.user.mention if entry.user else None
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None

    async def log_by(self, guild, e: discord.Embed, action, target_id):
        if (by := await self.who(guild, action, target_id)):
            e.add_field(name="Yapan", value=by, inline=False)
        await self.log(guild, e)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, ch):
        e = discord.Embed(title=f"📁 {_tur(ch)} oluşturuldu", description=f"{ch.mention} (`{ch.name}`)", color=YESIL)
        if getattr(ch, "category", None):
            e.add_field(name="Kategori", value=ch.category.name)
        await self.log_by(ch.guild, e, discord.AuditLogAction.channel_create, ch.id)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, ch):
        e = discord.Embed(title=f"🗑️ {_tur(ch)} silindi", description=f"`{ch.name}`", color=KIRMIZI)
        if getattr(ch, "category", None):
            e.add_field(name="Kategori", value=ch.category.name)
        await self.log_by(ch.guild, e, discord.AuditLogAction.channel_delete, ch.id)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes.append(("İsim", f"`{before.name}` → `{after.name}`"))
        if getattr(before, "category", None) != getattr(after, "category", None):
            b = before.category.name if before.category else "Kategorisiz"
            a = after.category.name if after.category else "Kategorisiz"
            changes.append(("Kategori", f"{b} → {a}"))
        if getattr(before, "topic", None) != getattr(after, "topic", None):
            changes.append(("Konu", f"{_cut(before.topic, 400)} → {_cut(after.topic, 400)}"))
        if getattr(before, "slowmode_delay", None) != getattr(after, "slowmode_delay", None):
            changes.append(("Yavaş mod", f"{before.slowmode_delay} sn → {after.slowmode_delay} sn"))
        if getattr(before, "nsfw", None) != getattr(after, "nsfw", None):
            changes.append(("Yaş sınırı", f"{'açık' if before.nsfw else 'kapalı'} → {'açık' if after.nsfw else 'kapalı'}"))
        if getattr(before, "user_limit", None) != getattr(after, "user_limit", None):
            changes.append(("Kişi sınırı", f"{before.user_limit or 'sınırsız'} → {after.user_limit or 'sınırsız'}"))
        if getattr(before, "bitrate", None) != getattr(after, "bitrate", None):
            changes.append(("Ses kalitesi", f"{before.bitrate // 1000} kbps → {after.bitrate // 1000} kbps"))
        perm_lines = _overwrite_diff(before.overwrites, after.overwrites)
        if not changes and not perm_lines:
            return  # sadece sıralama değişmiş, log kirletmesin
        e = discord.Embed(title=f"✏️ {_tur(after)} düzenlendi", description=f"{after.mention} (`{after.name}`)", color=TURUNCU)
        for name, value in changes:
            e.add_field(name=name, value=value[:1024], inline=False)
        if perm_lines:
            text = "\n".join(perm_lines)
            e.add_field(name="İzinler", value=text[:1020] + ("…" if len(text) > 1020 else ""), inline=False)
        action = (discord.AuditLogAction.overwrite_update if perm_lines and not changes
                  else discord.AuditLogAction.channel_update)
        by = await self.who(after.guild, action, after.id)
        if by is None and perm_lines:
            for act in (discord.AuditLogAction.overwrite_create, discord.AuditLogAction.overwrite_delete,
                        discord.AuditLogAction.overwrite_update):
                if (by := await self.who(after.guild, act, after.id)):
                    break
        if by:
            e.add_field(name="Yapan", value=by, inline=False)
        await self.log(after.guild, e)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        e = discord.Embed(title="🎨 Rol oluşturuldu", description=f"{role.mention} (`{role.name}`)", color=YESIL)
        await self.log_by(role.guild, e, discord.AuditLogAction.role_create, role.id)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        e = discord.Embed(title="🎨 Rol silindi", description=f"`{role.name}`", color=KIRMIZI)
        await self.log_by(role.guild, e, discord.AuditLogAction.role_delete, role.id)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        changes = []
        if before.name != after.name:
            changes.append(("İsim", f"`{before.name}` → `{after.name}`"))
        if before.color != after.color:
            changes.append(("Renk", f"`{before.color}` → `{after.color}`"))
        if before.hoist != after.hoist:
            changes.append(("Ayrı göster", f"{'evet' if before.hoist else 'hayır'} → {'evet' if after.hoist else 'hayır'}"))
        if before.mentionable != after.mentionable:
            changes.append(("Etiketlenebilir", f"{'evet' if before.mentionable else 'hayır'} → {'evet' if after.mentionable else 'hayır'}"))
        if before.permissions != after.permissions:
            added = [_perm(n) for n, v in after.permissions if v and not getattr(before.permissions, n)]
            removed = [_perm(n) for n, v in after.permissions if not v and getattr(before.permissions, n)]
            lines = []
            if added:
                lines.append("✅ " + ", ".join(added))
            if removed:
                lines.append("❌ " + ", ".join(removed))
            changes.append(("Yetkiler", "\n".join(lines)))
        if not changes:
            return  # sadece sıralama değişmiş
        e = discord.Embed(title="🎨 Rol düzenlendi", description=f"{after.mention} (`{after.name}`)", color=TURUNCU)
        for name, value in changes:
            e.add_field(name=name, value=value[:1024], inline=False)
        await self.log_by(after.guild, e, discord.AuditLogAction.role_update, after.id)

    # ---------- sunucu ----------
    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        changes = []
        if before.name != after.name:
            changes.append(("İsim", f"`{before.name}` → `{after.name}`"))
        if before.icon != after.icon:
            changes.append(("Simge", "değiştirildi"))
        if before.banner != after.banner:
            changes.append(("Afiş", "değiştirildi"))
        if before.afk_channel != after.afk_channel:
            changes.append(("AFK kanalı", f"{before.afk_channel or 'yok'} → {after.afk_channel or 'yok'}"))
        if before.verification_level != after.verification_level:
            changes.append(("Doğrulama seviyesi", f"{before.verification_level} → {after.verification_level}"))
        if not changes:
            return
        e = discord.Embed(title="🏠 Sunucu ayarları değişti", color=TURUNCU)
        for name, value in changes:
            e.add_field(name=name, value=value, inline=False)
        if after.icon:
            e.set_thumbnail(url=after.icon.url)
        await self.log_by(after, e, discord.AuditLogAction.guild_update, after.id)


def _tur(ch) -> str:
    if isinstance(ch, discord.CategoryChannel):
        return "Kategori"
    if isinstance(ch, discord.StageChannel):
        return "Sahne kanalı"
    if isinstance(ch, discord.VoiceChannel):
        return "Ses kanalı"
    if isinstance(ch, discord.ForumChannel):
        return "Forum kanalı"
    return "Kanal"


IZINLER = {
    "set_voice_channel_status": "Ses Kanalı Durumu", "use_external_apps": "Harici Uygulamalar",
    "pin_messages": "Mesaj Sabitle", "bypass_slowmode": "Yavaş Modu Atla",
    "read_messages": "Kanalı Görüntüle", "view_channel": "Kanalı Görüntüle", "external_emojis": "Harici Emoji",
    "send_tts_messages": "Sesli Mesaj (TTS)", "change_nickname": "Takma Ad Değiştir", "manage_threads": "Alt Başlıkları Yönet",
    "create_private_threads": "Özel Alt Başlık", "external_stickers": "Harici Çıkartma", "manage_events": "Etkinlikleri Yönet",
    "create_events": "Etkinlik Oluştur", "manage_expressions": "İfadeleri Yönet", "create_expressions": "İfade Oluştur",
    "send_voice_messages": "Sesli Mesaj Gönder", "use_soundboard": "Ses Panosu", "use_external_sounds": "Harici Sesler",
    "send_polls": "Anket Oluştur", "request_to_speak": "Konuşma İsteği", "use_embedded_activities": "Etkinlikler",
    "view_guild_insights": "Sunucu İstatistikleri", "view_creator_monetization_analytics": "Gelir Analizleri", "send_messages": "Mesaj Gönder", "read_message_history": "Mesaj Geçmişini Oku",
    "connect": "Bağlan", "speak": "Konuş", "stream": "Video/Yayın", "manage_channels": "Kanalları Yönet",
    "manage_roles": "Rolleri Yönet", "manage_messages": "Mesajları Yönet", "mention_everyone": "@everyone Etiketle",
    "embed_links": "Bağlantı Yerleştir", "attach_files": "Dosya Ekle", "add_reactions": "Tepki Ekle",
    "use_application_commands": "Uygulama Komutları", "administrator": "Yönetici", "kick_members": "Üyeleri At",
    "ban_members": "Üyeleri Yasakla", "moderate_members": "Zaman Aşımı Uygula", "manage_guild": "Sunucuyu Yönet",
    "manage_nicknames": "Takma Adları Yönet", "move_members": "Üyeleri Taşı", "mute_members": "Üyeleri Sustur",
    "deafen_members": "Üyeleri Sağırlaştır", "create_instant_invite": "Davet Oluştur",
    "send_messages_in_threads": "Alt Başlıklarda Mesaj", "create_public_threads": "Herkese Açık Alt Başlık",
    "use_external_emojis": "Harici Emoji", "view_audit_log": "Denetim Kaydını Görüntüle",
    "manage_webhooks": "Webhook'ları Yönet", "priority_speaker": "Öncelikli Konuşmacı", "use_voice_activation": "Ses Etkinliği",
}


def _perm(name: str) -> str:
    return IZINLER.get(name, name.replace("_", " ").title())


def _target_name(t) -> str:
    if isinstance(t, discord.Role):
        return "@everyone" if t.is_default() else f"@{t.name}"
    return str(t)


def _overwrite_diff(before: dict, after: dict) -> list[str]:
    """Kanal izin değişikliklerini okunur satırlara çevirir. ✅ izin verildi, ❌ engellendi, ⬜ varsayılana döndü."""
    lines = []
    sym = {True: "✅", False: "❌", None: "⬜"}
    for target in set(before) | set(after):
        b, a = before.get(target), after.get(target)
        name = _target_name(target)
        if b is None:
            lines.append(f"➕ **{name}** için izin ayarı eklendi")
        if a is None:
            lines.append(f"➖ **{name}** için izin ayarı kaldırıldı")
            continue
        b = b or discord.PermissionOverwrite()
        diffs = [f"{sym[v]} {_perm(n)}" for n, v in a if getattr(b, n) != v]
        if diffs:
            lines.append(f"**{name}:** " + ", ".join(diffs))
    return lines


async def setup(bot):
    await bot.add_cog(Log(bot))
