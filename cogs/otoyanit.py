"""Otomatik yanıtlayıcı: belirli bir mesaja otomatik cevap."""
import discord
from discord import app_commands
from discord.ext import commands

from utils.helpers import RENK, err, format_message, ok
from cogs.otomod import tr_lower


class Otoyanit(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cache: dict[int, list] = {}

    grup = app_commands.Group(name="otoyanit", description="Otomatik yanıtlar",
                              default_permissions=discord.Permissions(manage_guild=True), guild_only=True)

    def rules(self, guild_id: int):
        if guild_id not in self.cache:
            self.cache[guild_id] = [dict(r) for r in
                                    self.bot.db.all("SELECT * FROM autoresponses WHERE guild_id=?", (guild_id,))]
        return self.cache[guild_id]

    @grup.command(name="ekle", description="Yeni otomatik yanıt ekle")
    @app_commands.describe(tetikleyici="Hangi mesaja cevap verilsin", cevap="Bot ne yazsın ({kullanici} kullanılabilir)",
                           eslesme="Mesaj tam olarak bu mu olmalı, yoksa içinde geçmesi yeterli mi?")
    @app_commands.choices(eslesme=[app_commands.Choice(name="Tam eşleşme", value="tam"),
                                   app_commands.Choice(name="İçinde geçerse", value="icerir")])
    async def ekle(self, i: discord.Interaction, tetikleyici: str, cevap: str,
                   eslesme: app_commands.Choice[str] | None = None):
        mode = eslesme.value if eslesme else "tam"
        self.bot.db.execute("INSERT OR REPLACE INTO autoresponses (guild_id, trigger, response, mode) VALUES (?, ?, ?, ?)",
                            (i.guild_id, tr_lower(tetikleyici.strip()), cevap.replace("\\n", "\n"), mode))
        self.cache.pop(i.guild_id, None)
        await i.response.send_message(embed=ok(f"`{tetikleyici}` yazılınca cevap verilecek."))

    @grup.command(name="sil", description="Otomatik yanıtı sil")
    async def sil(self, i: discord.Interaction, tetikleyici: str):
        cur = self.bot.db.execute("DELETE FROM autoresponses WHERE guild_id=? AND trigger=?",
                                  (i.guild_id, tr_lower(tetikleyici.strip())))
        self.cache.pop(i.guild_id, None)
        await i.response.send_message(embed=ok("Silindi.") if cur.rowcount else err("Böyle bir otomatik yanıt yok."))

    @grup.command(name="liste", description="Otomatik yanıtları listele")
    async def liste(self, i: discord.Interaction):
        rules = self.rules(i.guild_id)
        text = "\n".join(f"`{r['trigger']}` ({'tam' if r['mode'] == 'tam' else 'içerir'}) → {r['response'][:60]}"
                         for r in rules) or "Henüz otomatik yanıt yok."
        await i.response.send_message(embed=discord.Embed(title="Otomatik yanıtlar", description=text[:4000], color=RENK))

    @commands.Cog.listener()
    async def on_message(self, m: discord.Message):
        if m.guild is None or m.author.bot or not m.content:
            return
        low = tr_lower(m.content.strip())
        for r in self.rules(m.guild.id):
            if (r["mode"] == "tam" and low == r["trigger"]) or (r["mode"] == "icerir" and r["trigger"] in low):
                try:
                    await m.reply(format_message(r["response"], m.author), mention_author=False)
                except discord.HTTPException:
                    pass
                return


async def setup(bot):
    await bot.add_cog(Otoyanit(bot))
