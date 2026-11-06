"""Ekstralar: yıldız panosu ve geçici (özel) ses kanalları."""
import discord
from discord import app_commands
from discord.ext import commands

from utils.helpers import err, ok

YILDIZ = "⭐"


class Ekstra(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    yildiz = app_commands.Group(name="yildiz", description="Yıldız panosu: çok ⭐ alan mesajlar ayrı kanalda paylaşılır",
                                default_permissions=discord.Permissions(manage_guild=True), guild_only=True)
    ozelses = app_commands.Group(name="ozelses", description="Girince kişiye özel ses kanalı açan sistem",
                                 default_permissions=discord.Permissions(manage_channels=True), guild_only=True)

    # ================= YILDIZ PANOSU =================
    @yildiz.command(name="kanal", description="Yıldız panosu kanalı")
    async def y_kanal(self, i: discord.Interaction, kanal: discord.TextChannel):
        self.bot.db.set(i.guild_id, "star_channel", kanal.id)
        await i.response.send_message(embed=ok(f"Yıldız panosu: {kanal.mention}. Eşik: {self.bot.db.get(i.guild_id, 'star_limit', 3)} ⭐"))

    @yildiz.command(name="esik", description="Kaç ⭐ alınca panoya düşsün")
    async def y_esik(self, i: discord.Interaction, sayi: app_commands.Range[int, 1, 50]):
        self.bot.db.set(i.guild_id, "star_limit", sayi)
        await i.response.send_message(embed=ok(f"Eşik **{sayi}** ⭐ olarak ayarlandı."))

    @yildiz.command(name="kapat", description="Yıldız panosunu kapat")
    async def y_kapat(self, i: discord.Interaction):
        self.bot.db.set(i.guild_id, "star_channel", None)
        await i.response.send_message(embed=ok("Yıldız panosu kapatıldı."))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, p: discord.RawReactionActionEvent):
        if p.guild_id is None or str(p.emoji) != YILDIZ:
            return
        db = self.bot.db
        ch_id = db.get(p.guild_id, "star_channel")
        if not ch_id or p.channel_id == ch_id:
            return
        guild = self.bot.get_guild(p.guild_id)
        board = guild and guild.get_channel(ch_id)
        source = guild and guild.get_channel(p.channel_id)
        if board is None or source is None:
            return
        try:
            msg = await source.fetch_message(p.message_id)
        except discord.HTTPException:
            return
        count = next((r.count for r in msg.reactions if str(r.emoji) == YILDIZ), 0)
        if count < db.get(p.guild_id, "star_limit", 3):
            return
        header = f"{YILDIZ} **{count}** • {source.mention}"
        existing = db.one("SELECT board_msg_id FROM starboard WHERE message_id=?", (msg.id,))
        if existing:
            try:
                bm = await board.fetch_message(existing["board_msg_id"])
                await bm.edit(content=header)
            except discord.HTTPException:
                pass
            return
        e = discord.Embed(description=msg.content or None, color=discord.Color.gold(), timestamp=msg.created_at)
        e.set_author(name=msg.author.display_name, icon_url=msg.author.display_avatar.url)
        e.add_field(name="Kaynak", value=f"[Mesaja git]({msg.jump_url})")
        img = next((a for a in msg.attachments if (a.content_type or "").startswith("image/")), None)
        if img:
            e.set_image(url=img.url)
        try:
            bm = await board.send(content=header, embed=e)
            db.execute("INSERT OR REPLACE INTO starboard (message_id, board_msg_id) VALUES (?, ?)", (msg.id, bm.id))
        except discord.HTTPException:
            pass

    # ================= ÖZEL SES KANALLARI =================
    @ozelses.command(name="kur", description="'Kanal oluştur' ses kanalını hazırla")
    async def o_kur(self, i: discord.Interaction, kategori: discord.CategoryChannel | None = None):
        await i.response.defer()
        ch = await i.guild.create_voice_channel("➕ Kanal Oluştur", category=kategori, reason="Özel ses sistemi")
        self.bot.db.set(i.guild_id, "tempvoice_hub", ch.id)
        await i.followup.send(embed=ok(f"{ch.mention} kanalına giren herkese kendine ait bir ses kanalı açılacak. "
                                       "Kanal boşalınca otomatik silinir."))

    @ozelses.command(name="kapat", description="Özel ses sistemini kapat")
    async def o_kapat(self, i: discord.Interaction):
        hub_id = self.bot.db.get(i.guild_id, "tempvoice_hub")
        self.bot.db.set(i.guild_id, "tempvoice_hub", None)
        hub = hub_id and i.guild.get_channel(hub_id)
        if hub:
            try:
                await hub.delete(reason="Özel ses sistemi kapatıldı")
            except discord.HTTPException:
                pass
        await i.response.send_message(embed=ok("Özel ses sistemi kapatıldı."))

    @app_commands.command(name="ses-limit", description="Kendi özel ses kanalının kişi sınırını ayarla (0 = sınırsız)")
    @app_commands.guild_only()
    async def o_limit(self, i: discord.Interaction, sayi: app_commands.Range[int, 0, 99]):
        ch = i.user.voice.channel if isinstance(i.user, discord.Member) and i.user.voice else None
        row = ch and self.bot.db.one("SELECT owner_id FROM temp_channels WHERE channel_id=?", (ch.id,))
        if not row or row["owner_id"] != i.user.id:
            return await i.response.send_message(embed=err("Önce kendi özel ses kanalında olmalısın."), ephemeral=True)
        await ch.edit(user_limit=sayi)
        await i.response.send_message(embed=ok(f"Kişi sınırı: {sayi or 'sınırsız'}"), ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        db = self.bot.db
        hub_id = db.get(member.guild.id, "tempvoice_hub")
        # Hub'a girdi: yeni kanal aç ve taşı
        if hub_id and after.channel and after.channel.id == hub_id:
            hub = after.channel
            overwrites = dict(hub.overwrites)
            overwrites[member] = discord.PermissionOverwrite(manage_channels=True, move_members=True, connect=True)
            try:
                new = await member.guild.create_voice_channel(f"🔊 {member.display_name}", category=hub.category,
                                                              overwrites=overwrites, reason="Özel ses kanalı")
                db.execute("INSERT OR REPLACE INTO temp_channels (channel_id, owner_id) VALUES (?, ?)", (new.id, member.id))
                await member.move_to(new)
            except discord.HTTPException:
                pass
        # Boşalan özel kanalı sil
        if before.channel and before.channel != after.channel and not before.channel.members:
            if db.one("SELECT 1 FROM temp_channels WHERE channel_id=?", (before.channel.id,)):
                try:
                    await before.channel.delete(reason="Özel ses kanalı boşaldı")
                except discord.HTTPException:
                    pass
                db.execute("DELETE FROM temp_channels WHERE channel_id=?", (before.channel.id,))


async def setup(bot):
    await bot.add_cog(Ekstra(bot))
