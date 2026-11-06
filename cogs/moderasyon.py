"""Moderasyon komutları."""
import time
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from utils.helpers import mark_action, KIRMIZI, RENK, TURUNCU, can_act, err, human_duration, ok, parse_duration, send_log


class Moderasyon(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def modlog(self, i: discord.Interaction, action: str, target, reason: str | None, extra: str | None = None,
                     color=KIRMIZI):
        e = discord.Embed(title=f"🛡️ {action}", color=color, timestamp=discord.utils.utcnow())
        e.add_field(name="Üye", value=f"{target.mention} ({target})")
        e.add_field(name="Yetkili", value=i.user.mention)
        if extra:
            e.add_field(name="Süre", value=extra)
        e.add_field(name="Sebep", value=reason or "Belirtilmedi", inline=False)
        await send_log(self.bot, i.guild, e)

    async def notify(self, member: discord.abc.User, guild: discord.Guild, action: str, reason: str | None):
        try:
            await member.send(f"**{guild.name}** sunucusunda {action}. Sebep: {reason or 'Belirtilmedi'}")
        except discord.HTTPException:
            pass

    # ---------- ban / kick ----------
    @app_commands.command(name="ban", description="Üyeyi sunucudan yasakla")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    @app_commands.describe(mesaj_sil="Son kaç günün mesajları silinsin (0-7)")
    async def ban(self, i: discord.Interaction, uye: discord.User, sebep: str | None = None,
                  mesaj_sil: app_commands.Range[int, 0, 7] = 0):
        member = i.guild.get_member(uye.id)
        if member and (problem := can_act(i.user, member)):
            return await i.response.send_message(embed=err(problem), ephemeral=True)
        await self.notify(uye, i.guild, "yasaklandın", sebep)
        mark_action(self.bot, "ban", i.guild_id, uye.id)
        await i.guild.ban(uye, reason=f"{i.user}: {sebep or 'Sebep yok'}", delete_message_seconds=mesaj_sil * 86400)
        await i.response.send_message(embed=ok(f"**{uye}** yasaklandı. Sebep: {sebep or 'Belirtilmedi'}"))
        await self.modlog(i, "Yasaklama", uye, sebep)

    @app_commands.command(name="unban", description="Yasağı kaldır (kullanıcı ID'si ile)")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    async def unban(self, i: discord.Interaction, kullanici_id: str, sebep: str | None = None):
        if not kullanici_id.isdigit():
            return await i.response.send_message(embed=err("Geçerli bir kullanıcı ID'si yaz."), ephemeral=True)
        try:
            user = await self.bot.fetch_user(int(kullanici_id))
            mark_action(self.bot, "unban", i.guild_id, user.id)
            await i.guild.unban(user, reason=f"{i.user}: {sebep or 'Sebep yok'}")
        except discord.NotFound:
            return await i.response.send_message(embed=err("Bu kullanıcı bulunamadı ya da yasaklı değil."), ephemeral=True)
        await i.response.send_message(embed=ok(f"**{user}** kullanıcısının yasağı kaldırıldı."))
        await self.modlog(i, "Yasak kaldırma", user, sebep, color=RENK)

    @app_commands.command(name="kick", description="Üyeyi sunucudan at")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick(self, i: discord.Interaction, uye: discord.Member, sebep: str | None = None):
        if problem := can_act(i.user, uye):
            return await i.response.send_message(embed=err(problem), ephemeral=True)
        await self.notify(uye, i.guild, "sunucudan atıldın", sebep)
        await uye.kick(reason=f"{i.user}: {sebep or 'Sebep yok'}")
        await i.response.send_message(embed=ok(f"**{uye}** sunucudan atıldı."))
        await self.modlog(i, "Atma", uye, sebep)

    # ---------- susturma (Discord zaman aşımı) ----------
    @app_commands.command(name="sustur", description="Üyeyi belirli bir süre sustur (örn: 10dk, 1sa, 2g)")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def sustur(self, i: discord.Interaction, uye: discord.Member, sure: str, sebep: str | None = None):
        if problem := can_act(i.user, uye):
            return await i.response.send_message(embed=err(problem), ephemeral=True)
        td = parse_duration(sure)
        if td is None:
            return await i.response.send_message(embed=err("Süre anlaşılmadı. Örnekler: `30dk`, `2sa`, `1g`, `1sa30dk`"),
                                                 ephemeral=True)
        if td > timedelta(days=28):
            return await i.response.send_message(embed=err("Discord en fazla 28 gün susturmaya izin veriyor."), ephemeral=True)
        mark_action(self.bot, "timeout", i.guild_id, uye.id)
        await uye.timeout(td, reason=f"{i.user}: {sebep or 'Sebep yok'}")
        await self.notify(uye, i.guild, f"{human_duration(td)} susturuldun", sebep)
        await i.response.send_message(embed=ok(f"{uye.mention} **{human_duration(td)}** susturuldu."))
        await self.modlog(i, "Susturma", uye, sebep, human_duration(td), TURUNCU)

    @app_commands.command(name="susturma-kaldir", description="Üyenin susturmasını kaldır")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def unmute(self, i: discord.Interaction, uye: discord.Member):
        await uye.timeout(None, reason=f"{i.user}: susturma kaldırıldı")
        await i.response.send_message(embed=ok(f"{uye.mention} artık konuşabilir."))
        await self.modlog(i, "Susturma kaldırma", uye, None, color=RENK)

    # ---------- mesaj temizleme ----------
    @app_commands.command(name="temizle", description="Kanaldaki mesajları sil (en fazla 100)")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.describe(uye="Sadece bu üyenin mesajlarını sil")
    async def temizle(self, i: discord.Interaction, sayi: app_commands.Range[int, 1, 100], uye: discord.Member | None = None):
        await i.response.defer(ephemeral=True)
        check = (lambda m: m.author.id == uye.id) if uye else None
        if check:
            deleted = await i.channel.purge(limit=500, check=_limited(check, sayi))
        else:
            deleted = await i.channel.purge(limit=sayi)
        await i.followup.send(embed=ok(f"**{len(deleted)}** mesaj silindi. (14 günden eski mesajlar silinemez.)"),
                              ephemeral=True)

    # ---------- uyarılar ----------
    @app_commands.command(name="uyar", description="Üyeye uyarı ver")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def uyar(self, i: discord.Interaction, uye: discord.Member, sebep: str):
        if uye.bot:
            return await i.response.send_message(embed=err("Botlara uyarı verilemez."), ephemeral=True)
        self.bot.db.execute("INSERT INTO warnings (guild_id, user_id, mod_id, reason, ts) VALUES (?, ?, ?, ?, ?)",
                            (i.guild_id, uye.id, i.user.id, sebep, time.time()))
        count = self.bot.db.one("SELECT COUNT(*) c FROM warnings WHERE guild_id=? AND user_id=?", (i.guild_id, uye.id))["c"]
        await self.notify(uye, i.guild, f"uyarıldın (toplam {count} uyarı)", sebep)
        await i.response.send_message(embed=ok(f"{uye.mention} uyarıldı. Toplam uyarı: **{count}**"))
        await self.modlog(i, f"Uyarı (#{count})", uye, sebep, color=TURUNCU)

    @app_commands.command(name="uyarilar", description="Üyenin uyarılarını göster")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def uyarilar(self, i: discord.Interaction, uye: discord.Member):
        rows = self.bot.db.all("SELECT * FROM warnings WHERE guild_id=? AND user_id=? ORDER BY ts DESC LIMIT 25",
                               (i.guild_id, uye.id))
        if not rows:
            return await i.response.send_message(embed=ok(f"{uye.mention} hiç uyarı almamış."))
        e = discord.Embed(title=f"{uye.display_name} - {len(rows)} uyarı", color=TURUNCU)
        for r in rows:
            e.add_field(name=f"Uyarı ID: {r['id']}",
                        value=f"{r['reason']}\nYetkili: <@{r['mod_id']}> • <t:{int(r['ts'])}:R>", inline=False)
        await i.response.send_message(embed=e)

    @app_commands.command(name="uyari-sil", description="Bir uyarıyı sil (ID'si /uyarilar'da yazar) veya üyenin hepsini sil")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def uyari_sil(self, i: discord.Interaction, uyari_id: int | None = None, uye: discord.Member | None = None):
        if uyari_id is not None:
            cur = self.bot.db.execute("DELETE FROM warnings WHERE id=? AND guild_id=?", (uyari_id, i.guild_id))
            msg = f"{cur.rowcount} uyarı silindi."
        elif uye is not None:
            cur = self.bot.db.execute("DELETE FROM warnings WHERE user_id=? AND guild_id=?", (uye.id, i.guild_id))
            msg = f"{uye.mention} için {cur.rowcount} uyarı silindi."
        else:
            return await i.response.send_message(embed=err("Bir uyarı ID'si ya da üye seçmelisin."), ephemeral=True)
        await i.response.send_message(embed=ok(msg))

    # ---------- kanal araçları ----------
    @app_commands.command(name="kilitle", description="Kanalı herkese yazmaya kapat")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def kilitle(self, i: discord.Interaction, kanal: discord.TextChannel | None = None):
        kanal = kanal or i.channel
        ow = kanal.overwrites_for(i.guild.default_role)
        ow.send_messages = False
        await kanal.set_permissions(i.guild.default_role, overwrite=ow, reason=f"{i.user}: kilitlendi")
        await i.response.send_message(embed=ok(f"🔒 {kanal.mention} kilitlendi."))

    @app_commands.command(name="kilit-ac", description="Kanalın kilidini aç")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def kilit_ac(self, i: discord.Interaction, kanal: discord.TextChannel | None = None):
        kanal = kanal or i.channel
        ow = kanal.overwrites_for(i.guild.default_role)
        ow.send_messages = None
        await kanal.set_permissions(i.guild.default_role, overwrite=ow, reason=f"{i.user}: kilit açıldı")
        await i.response.send_message(embed=ok(f"🔓 {kanal.mention} kilidi açıldı."))

    @app_commands.command(name="yavasmod", description="Kanala yavaş mod koy (0 = kapat)")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def yavasmod(self, i: discord.Interaction, saniye: app_commands.Range[int, 0, 21600]):
        await i.channel.edit(slowmode_delay=saniye)
        await i.response.send_message(embed=ok("Yavaş mod kapatıldı." if saniye == 0 else f"Yavaş mod: {saniye} saniye."))

    # ---------- rol ----------
    @app_commands.command(name="rol-ver", description="Üyeye rol ver")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def rol_ver(self, i: discord.Interaction, uye: discord.Member, rol: discord.Role):
        if problem := self._role_problem(i, rol):
            return await i.response.send_message(embed=err(problem), ephemeral=True)
        await uye.add_roles(rol, reason=f"{i.user} tarafından")
        await i.response.send_message(embed=ok(f"{uye.mention} kullanıcısına {rol.mention} verildi."))

    @app_commands.command(name="rol-al", description="Üyeden rol al")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def rol_al(self, i: discord.Interaction, uye: discord.Member, rol: discord.Role):
        if problem := self._role_problem(i, rol):
            return await i.response.send_message(embed=err(problem), ephemeral=True)
        await uye.remove_roles(rol, reason=f"{i.user} tarafından")
        await i.response.send_message(embed=ok(f"{uye.mention} kullanıcısından {rol.mention} alındı."))

    @staticmethod
    def _role_problem(i: discord.Interaction, rol: discord.Role) -> str | None:
        if rol.managed or rol.is_default():
            return "Bu rol elle verilemez."
        if rol >= i.guild.me.top_role:
            return "Bu rol botun rolünden yüksek."
        if i.user != i.guild.owner and rol >= i.user.top_role:
            return "Bu rol senin en yüksek rolünle aynı ya da daha yüksek."
        return None


def _limited(check, limit):
    """purge için: sadece ilk `limit` eşleşmeyi kabul eden kontrol."""
    state = {"n": 0}

    def inner(m):
        if state["n"] >= limit or not check(m):
            return False
        state["n"] += 1
        return True
    return inner


async def setup(bot):
    await bot.add_cog(Moderasyon(bot))
