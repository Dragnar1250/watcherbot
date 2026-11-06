"""Karşılama, veda, otomatik rol."""
import os

import discord
from discord import app_commands
from discord.ext import commands

from utils.helpers import DEGISKEN_ACIKLAMA, RENK, err, format_message, ok
from utils.images import welcome_card

VARSAYILAN_KARSILAMA = "Hoş geldin {kullanici}! **{sunucu}** sunucusuna katıldın, seninle birlikte **{uye_sayisi}** kişiyiz. 🎉"
VARSAYILAN_VEDA = "**{isim}** aramızdan ayrıldı. Artık **{uye_sayisi}** kişiyiz."


def bg_path(guild_id: int) -> str:
    return os.path.join("data", "arkaplanlar", f"{guild_id}.png")


class Karsilama(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    karsilama = app_commands.Group(name="karsilama", description="Karşılama mesajı ayarları",
                                   default_permissions=discord.Permissions(manage_guild=True), guild_only=True)
    veda = app_commands.Group(name="veda", description="Veda mesajı ayarları",
                              default_permissions=discord.Permissions(manage_guild=True), guild_only=True)
    otorol = app_commands.Group(name="otorol", description="Yeni gelenlere otomatik rol",
                                default_permissions=discord.Permissions(manage_roles=True), guild_only=True)

    # ---------- olaylar ----------
    async def build_welcome(self, member: discord.Member):
        db = self.bot.db
        text = format_message(db.get(member.guild.id, "welcome_message", VARSAYILAN_KARSILAMA), member)
        file = None
        if db.get(member.guild.id, "welcome_image", True):
            avatar = await member.display_avatar.replace(size=256, format="png").read()
            img = welcome_card(avatar, member.display_name, member.guild.name, member.guild.member_count,
                               bg_path(member.guild.id))
            file = discord.File(img, filename="hosgeldin.png")
        return text, file

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        db = self.bot.db
        g = member.guild

        # Otomatik roller
        roles = [r for rid in self.autoroles(g.id, "bot" if member.bot else "uye")
                 if (r := g.get_role(rid)) and r < g.me.top_role and not r.managed]
        if roles:
            try:
                await member.add_roles(*roles, reason="Otomatik rol")
            except discord.HTTPException:
                pass

        # Kanal mesajı
        ch_id = db.get(g.id, "welcome_channel")
        if ch_id and (ch := g.get_channel(ch_id)):
            text, file = await self.build_welcome(member)
            try:
                await ch.send(content=text, file=file) if file else await ch.send(content=text)
            except discord.HTTPException:
                pass

        # Özel mesaj
        dm = db.get(g.id, "welcome_dm")
        if dm and not member.bot:
            try:
                await member.send(format_message(dm, member))
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        db = self.bot.db
        ch_id = db.get(member.guild.id, "goodbye_channel")
        if ch_id and (ch := member.guild.get_channel(ch_id)):
            text = format_message(db.get(member.guild.id, "goodbye_message", VARSAYILAN_VEDA), member)
            try:
                await ch.send(text)
            except discord.HTTPException:
                pass

    # ---------- karşılama komutları ----------
    @karsilama.command(name="kanal", description="Karşılama mesajının gideceği kanalı ayarla")
    async def k_kanal(self, i: discord.Interaction, kanal: discord.TextChannel):
        self.bot.db.set(i.guild_id, "welcome_channel", kanal.id)
        await i.response.send_message(embed=ok(f"Karşılama kanalı {kanal.mention} olarak ayarlandı."))

    @karsilama.command(name="mesaj", description="Karşılama mesajını değiştir")
    @app_commands.describe(mesaj="Değişkenler: {kullanici} {isim} {sunucu} {uye_sayisi}")
    async def k_mesaj(self, i: discord.Interaction, mesaj: str):
        self.bot.db.set(i.guild_id, "welcome_message", mesaj.replace("\\n", "\n"))
        await i.response.send_message(embed=ok("Karşılama mesajı güncellendi. `/karsilama test` ile deneyebilirsin."))

    @karsilama.command(name="resim", description="Karşılama resmini aç veya kapat")
    async def k_resim(self, i: discord.Interaction, acik: bool):
        self.bot.db.set(i.guild_id, "welcome_image", acik)
        await i.response.send_message(embed=ok(f"Karşılama resmi {'açıldı' if acik else 'kapatıldı'}."))

    @karsilama.command(name="arkaplan", description="Karşılama resminin arka planını yükle (boş bırakırsan varsayılana döner)")
    async def k_arkaplan(self, i: discord.Interaction, resim: discord.Attachment | None = None):
        path = bg_path(i.guild_id)
        if resim is None:
            if os.path.exists(path):
                os.remove(path)
            return await i.response.send_message(embed=ok("Arka plan varsayılana döndürüldü."))
        if not (resim.content_type or "").startswith("image/"):
            return await i.response.send_message(embed=err("Lütfen bir resim dosyası yükle (PNG/JPG)."), ephemeral=True)
        if resim.size > 8 * 1024 * 1024:
            return await i.response.send_message(embed=err("Resim 8 MB'tan küçük olmalı."), ephemeral=True)
        await i.response.defer()
        from PIL import Image
        import io
        data = await resim.read()
        try:
            Image.open(io.BytesIO(data)).convert("RGB").save(path, "PNG")
        except Exception:
            return await i.followup.send(embed=err("Bu resim açılamadı."))
        await i.followup.send(embed=ok("Arka plan kaydedildi. `/karsilama test` ile görebilirsin."))

    @karsilama.command(name="ozel-mesaj", description="Yeni gelene özelden gönderilecek mesaj (boş bırakırsan kapanır)")
    async def k_dm(self, i: discord.Interaction, mesaj: str | None = None):
        self.bot.db.set(i.guild_id, "welcome_dm", mesaj.replace("\\n", "\n") if mesaj else None)
        await i.response.send_message(embed=ok("Özel mesaj " + ("ayarlandı." if mesaj else "kapatıldı.")))

    @karsilama.command(name="kapat", description="Karşılama mesajını kapat")
    async def k_kapat(self, i: discord.Interaction):
        self.bot.db.set(i.guild_id, "welcome_channel", None)
        await i.response.send_message(embed=ok("Karşılama mesajı kapatıldı."))

    @karsilama.command(name="test", description="Karşılama mesajını kendinle dene")
    async def k_test(self, i: discord.Interaction):
        await i.response.defer()
        text, file = await self.build_welcome(i.user)
        if file:
            await i.followup.send(content=text, file=file)
        else:
            await i.followup.send(content=text)

    @karsilama.command(name="degiskenler", description="Mesajlarda kullanılabilecek değişkenler")
    async def k_degisken(self, i: discord.Interaction):
        await i.response.send_message(embed=discord.Embed(title="Değişkenler", description=DEGISKEN_ACIKLAMA, color=RENK),
                                      ephemeral=True)

    # ---------- veda ----------
    @veda.command(name="kanal", description="Veda mesajının gideceği kanal")
    async def v_kanal(self, i: discord.Interaction, kanal: discord.TextChannel):
        self.bot.db.set(i.guild_id, "goodbye_channel", kanal.id)
        await i.response.send_message(embed=ok(f"Veda kanalı {kanal.mention} olarak ayarlandı."))

    @veda.command(name="mesaj", description="Veda mesajını değiştir")
    @app_commands.describe(mesaj="Değişkenler: {kullanici} {isim} {sunucu} {uye_sayisi}")
    async def v_mesaj(self, i: discord.Interaction, mesaj: str):
        self.bot.db.set(i.guild_id, "goodbye_message", mesaj.replace("\\n", "\n"))
        await i.response.send_message(embed=ok("Veda mesajı güncellendi."))

    @veda.command(name="kapat", description="Veda mesajını kapat")
    async def v_kapat(self, i: discord.Interaction):
        self.bot.db.set(i.guild_id, "goodbye_channel", None)
        await i.response.send_message(embed=ok("Veda mesajı kapatıldı."))

    # ---------- otorol ----------
    def autoroles(self, guild_id: int, hedef: str) -> list[int]:
        """hedef: 'uye' veya 'bot'. Eski tek rollü ayarı otomatik olarak listeye taşır."""
        db = self.bot.db
        key = f"autoroles_{hedef}"
        roles = db.get(guild_id, key)
        if roles is None:
            old = db.get(guild_id, "autorole_member" if hedef == "uye" else "autorole_bot")
            roles = [old] if old else []
            db.set(guild_id, key, roles)
            db.set(guild_id, "autorole_member" if hedef == "uye" else "autorole_bot", None)
        return roles

    HEDEF = [app_commands.Choice(name="Üyeler", value="uye"), app_commands.Choice(name="Botlar", value="bot")]

    @otorol.command(name="ekle", description="Yeni gelenlere otomatik verilecek bir rol ekle (birden fazla eklenebilir)")
    @app_commands.choices(hedef=HEDEF)
    @app_commands.describe(hedef="Kime verilsin? (boş = üyeler)")
    async def o_ekle(self, i: discord.Interaction, rol: discord.Role, hedef: app_commands.Choice[str] | None = None):
        h = hedef.value if hedef else "uye"
        if rol.managed or rol.is_default():
            return await i.response.send_message(embed=err("Bu rol elle verilemez."), ephemeral=True)
        if rol >= i.guild.me.top_role:
            return await i.response.send_message(embed=err("Bu rol botun rolünden yüksek, veremem. Bot rolünü üste taşı."),
                                                 ephemeral=True)
        roles = self.autoroles(i.guild_id, h)
        if rol.id in roles:
            return await i.response.send_message(embed=err(f"{rol.mention} zaten listede."), ephemeral=True)
        roles.append(rol.id)
        self.bot.db.set(i.guild_id, f"autoroles_{h}", roles)
        kime = "üyelere" if h == "uye" else "botlara"
        await i.response.send_message(embed=ok(f"Yeni gelen {kime} artık {rol.mention} de verilecek."))

    @otorol.command(name="sil", description="Otomatik rol listesinden bir rolü kaldır")
    async def o_sil(self, i: discord.Interaction, rol: discord.Role):
        removed = False
        for h in ("uye", "bot"):
            roles = self.autoroles(i.guild_id, h)
            if rol.id in roles:
                roles.remove(rol.id)
                self.bot.db.set(i.guild_id, f"autoroles_{h}", roles)
                removed = True
        if not removed:
            return await i.response.send_message(embed=err(f"{rol.mention} otomatik rol listesinde yok."), ephemeral=True)
        await i.response.send_message(embed=ok(f"{rol.mention} artık yeni gelenlere verilmeyecek. "
                                               "(Daha önce alanlarda rol kalır.)"))

    @otorol.command(name="liste", description="Otomatik rolleri göster")
    async def o_liste(self, i: discord.Interaction):
        def fmt(ids):
            out = []
            for rid in ids:
                r = i.guild.get_role(rid)
                out.append(f"<@&{rid}>" + ("" if r else " *(silinmiş rol)*"))
            return "\n".join(out) or "Yok"
        e = discord.Embed(title="Otomatik roller", color=RENK)
        e.add_field(name="👤 Üyelere", value=fmt(self.autoroles(i.guild_id, "uye")))
        e.add_field(name="🤖 Botlara", value=fmt(self.autoroles(i.guild_id, "bot")))
        await i.response.send_message(embed=e)

    @otorol.command(name="kapat", description="Tüm otomatik rolleri kaldır")
    async def o_kapat(self, i: discord.Interaction):
        for h in ("uye", "bot"):
            self.autoroles(i.guild_id, h)
            self.bot.db.set(i.guild_id, f"autoroles_{h}", [])
        await i.response.send_message(embed=ok("Tüm otomatik roller kaldırıldı."))


async def setup(bot):
    await bot.add_cog(Karsilama(bot))
