"""Cezalı sistemi: rolleri alıp Cezalı rolü verir, süre bitince rolleri geri verir."""
import json
import time
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.helpers import mark_action, KIRMIZI, RENK, YESIL, can_act, err, human_duration, ok, parse_duration, send_log


class Cezali(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_expired.start()

    def cog_unload(self):
        self.check_expired.cancel()

    grup = app_commands.Group(name="cezali", description="Cezalı sistemi (rolleri alıp Cezalı rolü verir)",
                              default_permissions=discord.Permissions(moderate_members=True), guild_only=True)

    # ================= yardımcılar =================
    def jail_role(self, guild: discord.Guild) -> discord.Role | None:
        rid = self.bot.db.get(guild.id, "jail_role")
        return guild.get_role(rid) if rid else None

    def record(self, guild_id: int, user_id: int):
        return self.bot.db.one("SELECT * FROM jail WHERE guild_id=? AND user_id=?", (guild_id, user_id))

    async def log(self, guild, title, member, color, **fields):
        e = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())
        e.add_field(name="Üye", value=f"{member.mention} ({member})")
        for k, v in fields.items():
            if v:
                e.add_field(name=k.replace("_", " "), value=str(v)[:1000], inline=k == "Sebep")
        await send_log(self.bot, guild, e)

    async def release(self, guild: discord.Guild, user_id: int, by: str) -> tuple[bool, list[str]]:
        """Cezayı kaldırır, rolleri geri verir. (üye sunucuda mı, geri verilemeyen roller)"""
        row = self.record(guild.id, user_id)
        if row is None:
            return False, []
        # Önce kaydı sil: aşağıdaki rol değişikliği on_member_update'i tekrar tetiklemesin
        self.bot.db.execute("DELETE FROM jail WHERE guild_id=? AND user_id=?", (guild.id, user_id))
        member = guild.get_member(user_id)
        if member is None:
            return False, []
        jail = self.jail_role(guild)
        saved = json.loads(row["roles"])
        give, failed = [], []
        for rid in saved:
            role = guild.get_role(rid)
            if role is None:
                continue  # rol silinmiş
            if role >= guild.me.top_role:
                failed.append(role.name)
                continue
            give.append(role)
        new_roles = [r for r in member.roles if not r.is_default() and r != jail]
        new_roles += [r for r in give if r not in new_roles]
        mark_action(self.bot, "roles", guild.id, member.id)
        try:
            await member.edit(roles=new_roles, reason=f"Ceza bitti ({by})")
        except discord.HTTPException:
            # Toplu düzenleme olmazsa tek tek dene
            try:
                if jail and jail in member.roles:
                    await member.remove_roles(jail, reason=f"Ceza bitti ({by})")
                if give:
                    await member.add_roles(*give, reason=f"Ceza bitti ({by})")
            except discord.HTTPException:
                failed.append("(bazı roller verilemedi, bot yetkilerini kontrol et)")
        await self.log(guild, "🔓 Ceza bitti", member, YESIL, Kaldıran=by,
                       Geri_verilen=" ".join(r.mention for r in give) or "Yok")
        try:
            await member.send(f"**{guild.name}** sunucusundaki cezan sona erdi, rollerin geri verildi.")
        except discord.HTTPException:
            pass
        return True, failed

    # ================= süre kontrolü =================
    @tasks.loop(seconds=30)
    async def check_expired(self):
        rows = self.bot.db.all("SELECT guild_id, user_id FROM jail WHERE until IS NOT NULL AND until<=?", (time.time(),))
        for r in rows:
            guild = self.bot.get_guild(r["guild_id"])
            if guild is None:
                continue
            await self.release(guild, r["user_id"], "süre doldu")

    @check_expired.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ================= olaylar =================
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Cezalıyken çıkıp geri giren kişiye Cezalı rolü tekrar verilir."""
        row = self.record(member.guild.id, member.id)
        if row is None:
            return
        jail = self.jail_role(member.guild)
        if jail:
            try:
                await member.add_roles(jail, reason="Cezası devam ederken sunucuya geri girdi")
            except discord.HTTPException:
                pass
            await self.log(member.guild, "⛓️ Cezalı üye geri girdi", member, KIRMIZI,
                           Durum="Cezalı rolü tekrar verildi")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Bir yetkili Cezalı rolünü elle alırsa cezayı kaldırıp rolleri geri ver."""
        jail = self.jail_role(after.guild)
        if jail is None or jail not in before.roles or jail in after.roles:
            return
        if self.record(after.guild.id, after.id) is None:
            return
        await self.release(after.guild, after.id, "Cezalı rolü elle alındı")

    # ================= komutlar =================
    @grup.command(name="rol", description="Cezalı olarak kullanılacak rolü seç")
    async def rol(self, i: discord.Interaction, rol: discord.Role):
        if rol.managed or rol.is_default():
            return await i.response.send_message(embed=err("Bu rol kullanılamaz."), ephemeral=True)
        if rol >= i.guild.me.top_role:
            return await i.response.send_message(embed=err("Bu rol botun rolünden yüksek. Bot rolünü üste taşı."),
                                                 ephemeral=True)
        self.bot.db.set(i.guild_id, "jail_role", rol.id)
        await i.response.send_message(embed=ok(
            f"Cezalı rolü: {rol.mention}\n"
            "-# Bu rolün kanallarda neyi göremeyeceğini/yazamayacağını kanal izinlerinden ayarlamayı unutma."))

    @grup.command(name="ver", description="Üyenin rollerini alıp Cezalı rolü ver (süre boşsa süresiz)")
    @app_commands.describe(sure="Örn: 30dk, 2sa, 1g, 1hf. Boş bırakırsan ceza elle kaldırılana kadar sürer")
    async def ver(self, i: discord.Interaction, uye: discord.Member, sure: str | None = None, sebep: str | None = None):
        g = i.guild
        jail = self.jail_role(g)
        if jail is None:
            return await i.response.send_message(embed=err("Önce cezalı rolünü seç: `/cezali rol`"), ephemeral=True)
        if uye.bot:
            return await i.response.send_message(embed=err("Botlara ceza verilemez."), ephemeral=True)
        if problem := can_act(i.user, uye):
            return await i.response.send_message(embed=err(problem), ephemeral=True)
        if self.record(g.id, uye.id):
            return await i.response.send_message(embed=err(f"{uye.mention} zaten cezalı. Önce `/cezali kaldir` kullan."),
                                                 ephemeral=True)
        td = None
        if sure:
            td = parse_duration(sure)
            if td is None:
                return await i.response.send_message(embed=err("Süre anlaşılmadı. Örnekler: `30dk`, `2sa`, `1g`, `1hf`"),
                                                     ephemeral=True)
        await i.response.defer()

        # Alınabilecek roller: @everyone, otomatik (Booster/bot) ve botun üstündeki roller hariç
        removable = [r for r in uye.roles
                     if not r.is_default() and not r.managed and r != jail and r < g.me.top_role]
        kept = [r for r in uye.roles if not r.is_default() and r not in removable and r != jail]
        until = time.time() + td.total_seconds() if td else None
        self.bot.db.execute(
            "INSERT INTO jail (guild_id, user_id, roles, until, reason, mod_id, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (g.id, uye.id, json.dumps([r.id for r in removable]), until, sebep, i.user.id, time.time()))
        reason = f"{i.user}: {sebep or 'Sebep yok'}"
        mark_action(self.bot, "roles", g.id, uye.id)
        try:
            await uye.edit(roles=kept + [jail], reason=reason)
        except discord.HTTPException:
            try:
                if removable:
                    await uye.remove_roles(*removable, reason=reason)
                await uye.add_roles(jail, reason=reason)
            except discord.HTTPException:
                self.bot.db.execute("DELETE FROM jail WHERE guild_id=? AND user_id=?", (g.id, uye.id))
                return await i.followup.send(embed=err("Roller değiştirilemedi. Botun 'Rolleri Yönet' yetkisini "
                                                       "ve rolünün sırasını kontrol et."))

        sure_txt = human_duration(td) if td else "süresiz"
        bitis = f"<t:{int(until)}:R>" if until else "elle kaldırılana kadar"
        msg = (f"⛓️ {uye.mention} **{sure_txt}** cezalıya atıldı. Bitiş: {bitis}\n"
               f"Alınan rol sayısı: **{len(removable)}** (ceza bitince geri verilecek)")
        if kept:
            msg += f"\n-# Alınamayan roller (otomatik ya da bottan yüksek): {', '.join(r.name for r in kept)}"
        await i.followup.send(embed=discord.Embed(description=msg, color=KIRMIZI))
        await self.log(g, "⛓️ Cezalı", uye, KIRMIZI, Yetkili=i.user.mention, Süre=sure_txt,
                       Bitiş=bitis, Sebep=sebep or "Belirtilmedi")
        try:
            await uye.send(f"**{g.name}** sunucusunda **{sure_txt}** cezalıya atıldın. "
                           f"Sebep: {sebep or 'Belirtilmedi'}")
        except discord.HTTPException:
            pass

    @grup.command(name="kaldir", description="Cezayı hemen kaldır ve rolleri geri ver")
    async def kaldir(self, i: discord.Interaction, uye: discord.Member):
        if self.record(i.guild_id, uye.id) is None:
            return await i.response.send_message(embed=err(f"{uye.mention} cezalı değil."), ephemeral=True)
        await i.response.defer()
        _, failed = await self.release(i.guild, uye.id, str(i.user))
        msg = f"{uye.mention} cezası kaldırıldı, rolleri geri verildi."
        if failed:
            msg += f"\n-# Geri verilemeyenler: {', '.join(failed)}"
        await i.followup.send(embed=ok(msg))

    @grup.command(name="liste", description="Cezalı üyeleri ve kalan sürelerini göster")
    async def liste(self, i: discord.Interaction):
        rows = self.bot.db.all("SELECT * FROM jail WHERE guild_id=? ORDER BY ts DESC", (i.guild_id,))
        if not rows:
            return await i.response.send_message(embed=ok("Şu an cezalı kimse yok."))
        lines = []
        for r in rows[:25]:
            bitis = f"<t:{int(r['until'])}:R>" if r["until"] else "süresiz"
            lines.append(f"<@{r['user_id']}> • bitiş: {bitis} • yetkili: <@{r['mod_id']}>"
                         f"\n-# {r['reason'] or 'Sebep belirtilmedi'}")
        e = discord.Embed(title=f"⛓️ Cezalılar ({len(rows)})", description="\n".join(lines), color=RENK)
        await i.response.send_message(embed=e)

    @grup.command(name="sure", description="Cezalı üyenin süresini değiştir (boş = süresiz yap)")
    @app_commands.describe(sure="Şu andan itibaren yeni süre. Örn: 1g. Boş bırakırsan süresiz olur")
    async def sure(self, i: discord.Interaction, uye: discord.Member, sure: str | None = None):
        if self.record(i.guild_id, uye.id) is None:
            return await i.response.send_message(embed=err(f"{uye.mention} cezalı değil."), ephemeral=True)
        until = None
        if sure:
            td = parse_duration(sure)
            if td is None:
                return await i.response.send_message(embed=err("Süre anlaşılmadı. Örnekler: `30dk`, `2sa`, `1g`"),
                                                     ephemeral=True)
            until = time.time() + td.total_seconds()
        self.bot.db.execute("UPDATE jail SET until=? WHERE guild_id=? AND user_id=?", (until, i.guild_id, uye.id))
        await i.response.send_message(embed=ok(
            f"{uye.mention} cezası " + (f"<t:{int(until)}:R> bitecek." if until else "artık süresiz.")))


async def setup(bot):
    await bot.add_cog(Cezali(bot))
