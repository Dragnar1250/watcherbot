"""Tepki rolleri: bir mesaja emoji koyan üye rolü alır, kaldırınca rol gider."""
import discord
from discord import app_commands
from discord.ext import commands

from utils.helpers import RENK, err, ok


class Roller(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    grup = app_commands.Group(name="tepkirol", description="Tepki rolleri",
                              default_permissions=discord.Permissions(manage_roles=True), guild_only=True)

    @grup.command(name="ekle", description="Bir mesaja tepki rolü ekle")
    @app_commands.describe(mesaj_id="Mesaja sağ tıkla → Mesaj ID'sini Kopyala (Geliştirici Modu açık olmalı)",
                           kanal="Mesajın olduğu kanal (boş = bu kanal)")
    async def ekle(self, i: discord.Interaction, mesaj_id: str, emoji: str, rol: discord.Role,
                   kanal: discord.TextChannel | None = None):
        kanal = kanal or i.channel
        if rol >= i.guild.me.top_role or rol.managed or rol.is_default():
            return await i.response.send_message(embed=err("Bu rolü veremem. Bot rolünü rol listesinde daha yukarı taşı."),
                                                 ephemeral=True)
        try:
            msg = await kanal.fetch_message(int(mesaj_id))
        except (ValueError, discord.NotFound):
            return await i.response.send_message(embed=err("Mesaj bulunamadı. ID'yi ve kanalı kontrol et."), ephemeral=True)
        emoji = emoji.strip()
        try:
            await msg.add_reaction(emoji)
        except discord.HTTPException:
            return await i.response.send_message(embed=err("Bu emoji kullanılamıyor. Bu sunucudaki ya da standart bir emoji seç."),
                                                 ephemeral=True)
        self.bot.db.execute("INSERT OR REPLACE INTO reaction_roles (guild_id, message_id, emoji, role_id) VALUES (?, ?, ?, ?)",
                            (i.guild_id, msg.id, emoji, rol.id))
        await i.response.send_message(embed=ok(f"[Bu mesaja]({msg.jump_url}) {emoji} tepkisi koyan {rol.mention} alacak."))

    @grup.command(name="sil", description="Tepki rolünü kaldır")
    async def sil(self, i: discord.Interaction, mesaj_id: str, emoji: str):
        cur = self.bot.db.execute("DELETE FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",
                                  (i.guild_id, int(mesaj_id) if mesaj_id.isdigit() else 0, emoji.strip()))
        await i.response.send_message(embed=ok("Kaldırıldı.") if cur.rowcount else err("Böyle bir tepki rolü yok."))

    @grup.command(name="liste", description="Tepki rollerini listele")
    async def liste(self, i: discord.Interaction):
        rows = self.bot.db.all("SELECT * FROM reaction_roles WHERE guild_id=?", (i.guild_id,))
        text = "\n".join(f"`{r['message_id']}` {r['emoji']} → <@&{r['role_id']}>" for r in rows) or "Henüz tepki rolü yok."
        await i.response.send_message(embed=discord.Embed(title="Tepki rolleri", description=text[:4000], color=RENK))

    def _lookup(self, payload: discord.RawReactionActionEvent):
        return self.bot.db.one("SELECT role_id FROM reaction_roles WHERE message_id=? AND emoji=?",
                               (payload.message_id, str(payload.emoji)))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return
        row = self._lookup(payload)
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        member = payload.member or (guild and guild.get_member(payload.user_id))
        role = guild and guild.get_role(row["role_id"])
        if member and role and not member.bot:
            try:
                await member.add_roles(role, reason="Tepki rolü")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        row = self._lookup(payload)
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        member = guild and guild.get_member(payload.user_id)
        role = guild and guild.get_role(row["role_id"])
        if member and role:
            try:
                await member.remove_roles(role, reason="Tepki rolü kaldırıldı")
            except discord.HTTPException:
                pass


async def setup(bot):
    await bot.add_cog(Roller(bot))
