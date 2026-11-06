"""Sosyal: kredi, günlük ödül, itibar, profil kartı."""
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils.helpers import RENK, err, human_duration, ok
from utils.images import profile_card
from datetime import timedelta

GUN = 86400
VERGI = 0.05  # kredi transferinde %5 kesinti (ProBot gibi)


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


class Sosyal(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="gunluk", description="Günlük kredi ödülünü al")
    async def gunluk(self, i: discord.Interaction):
        u = self.bot.db.user(i.user.id)
        left = u["last_daily"] + GUN - time.time()
        if left > 0:
            return await i.response.send_message(
                embed=err(f"Günlük ödülünü zaten aldın. Kalan süre: **{human_duration(timedelta(seconds=int(left)))}**"),
                ephemeral=True)
        amount = random.randint(150, 400)
        self.bot.db.execute("UPDATE users SET credits=credits+?, last_daily=? WHERE user_id=?", (amount, time.time(), i.user.id))
        await i.response.send_message(embed=ok(f"💰 **{fmt(amount)}** kredi kazandın! Yarın tekrar gel."))

    @app_commands.command(name="kredi", description="Kredi bakiyeni ya da başkasınınkini gör")
    async def kredi(self, i: discord.Interaction, uye: discord.User | None = None):
        uye = uye or i.user
        u = self.bot.db.user(uye.id)
        await i.response.send_message(embed=discord.Embed(
            description=f"💳 {uye.mention} bakiyesi: **{fmt(u['credits'])}** kredi", color=RENK))

    @app_commands.command(name="kredi-gonder", description="Birine kredi gönder (%5 kesinti)")
    async def kredi_gonder(self, i: discord.Interaction, uye: discord.User, miktar: app_commands.Range[int, 1, 10_000_000]):
        if uye.bot or uye.id == i.user.id:
            return await i.response.send_message(embed=err("Kendine ya da bir bota kredi gönderemezsin."), ephemeral=True)
        db = self.bot.db
        u = db.user(i.user.id)
        if u["credits"] < miktar:
            return await i.response.send_message(embed=err(f"Yeterli kredin yok. Bakiye: {fmt(u['credits'])}"), ephemeral=True)
        db.user(uye.id)
        received = int(miktar * (1 - VERGI))
        # Önce düşür, bakiye yetersizse işlem olmaz (aynı anda iki komut atılırsa güvenli)
        cur = db.execute("UPDATE users SET credits=credits-? WHERE user_id=? AND credits>=?", (miktar, i.user.id, miktar))
        if cur.rowcount == 0:
            return await i.response.send_message(embed=err("Yeterli kredin yok."), ephemeral=True)
        db.execute("UPDATE users SET credits=credits+? WHERE user_id=?", (received, uye.id))
        await i.response.send_message(embed=ok(
            f"{uye.mention} kullanıcısına **{fmt(received)}** kredi gönderildi. (Kesinti: {fmt(miktar - received)})"))

    @app_commands.command(name="itibar", description="Birine günde bir itibar puanı ver")
    async def itibar(self, i: discord.Interaction, uye: discord.User):
        if uye.bot or uye.id == i.user.id:
            return await i.response.send_message(embed=err("Kendine ya da bir bota itibar veremezsin."), ephemeral=True)
        db = self.bot.db
        u = db.user(i.user.id)
        left = u["last_rep"] + GUN - time.time()
        if left > 0:
            return await i.response.send_message(
                embed=err(f"Tekrar itibar verebilmek için: **{human_duration(timedelta(seconds=int(left)))}**"), ephemeral=True)
        db.user(uye.id)
        db.execute("UPDATE users SET rep=rep+1 WHERE user_id=?", (uye.id,))
        db.execute("UPDATE users SET last_rep=? WHERE user_id=?", (time.time(), i.user.id))
        await i.response.send_message(embed=ok(f"⭐ {uye.mention} kullanıcısına itibar verdin!"))

    @app_commands.command(name="hakkimda", description="Profilindeki hakkımda yazısını değiştir")
    async def hakkimda(self, i: discord.Interaction, yazi: app_commands.Range[str, 1, 120]):
        self.bot.db.user(i.user.id)
        self.bot.db.execute("UPDATE users SET bio=? WHERE user_id=?", (yazi, i.user.id))
        await i.response.send_message(embed=ok("Hakkımda yazın güncellendi."), ephemeral=True)

    @app_commands.command(name="profil", description="Profil kartını göster")
    async def profil(self, i: discord.Interaction, uye: discord.User | None = None):
        uye = uye or i.user
        if uye.bot:
            return await i.response.send_message(embed=err("Botların profili yok."), ephemeral=True)
        await i.response.defer()
        u = self.bot.db.user(uye.id)
        level = 0
        if i.guild_id:
            level = self.bot.db.level_row(i.guild_id, uye.id)["level"]
        avatar = await uye.display_avatar.replace(size=256, format="png").read()
        img = profile_card(avatar, uye.display_name, u["credits"], u["rep"], level, u["bio"])
        await i.followup.send(file=discord.File(img, filename="profil.png"))

    @app_commands.command(name="zenginler", description="En çok krediye sahip kullanıcılar")
    async def zenginler(self, i: discord.Interaction):
        rows = self.bot.db.all("SELECT user_id, credits FROM users WHERE credits>0 ORDER BY credits DESC LIMIT 10")
        text = "\n".join(f"`#{n}` <@{r['user_id']}> • **{fmt(r['credits'])}** kredi" for n, r in enumerate(rows, 1))
        await i.response.send_message(embed=discord.Embed(title="💰 En zenginler", description=text or "Henüz kimse yok.",
                                                          color=RENK))


async def setup(bot):
    await bot.add_cog(Sosyal(bot))
