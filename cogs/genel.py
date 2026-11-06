"""Genel komutlar: yardım, bilgi, avatar, embed oluşturucu."""
import discord
from discord import app_commands
from discord.ext import commands

from utils.helpers import RENK, err, ok

YARDIM = {
    "⚙️ Kurulum": [
        "`/karsilama kanal|mesaj|resim|arkaplan|ozel-mesaj|test|kapat`",
        "`/veda kanal|mesaj|kapat` • `/otorol ekle|sil|liste|kapat`",
        "`/log kanal|kapat|yoksay-kanal`",
    ],
    "🛡️ Moderasyon": [
        "`/ban` `/unban` `/kick` `/sustur` `/susturma-kaldir`",
        "`/uyar` `/uyarilar` `/uyari-sil` `/temizle`",
        "`/kilitle` `/kilit-ac` `/yavasmod` `/rol-ver` `/rol-al`",
    ],
    "⛓️ Cezalı": ["`/cezali rol|ver|kaldir|sure|liste`"],
    "🤖 Otomoderasyon": ["`/otomod filtre|ceza|kelime-ekle|kelime-sil|muaf-kanal|muaf-rol|durum`"],
    "📈 Seviye": [
        "`/rank` (yazı + ses) `/siralama` (tür: yazı/ses)",
        "`/seviye ayarlar|ac-kapat|ses-xp|ses-afk|xp-miktari|kanal|mesaj|duyuru|ses-duyuru|resim|arkaplan|test`",
        "`/seviye yoksay-kanal|yoksay-ses|ozelses-xp|yoksay-rol|yoksay-onek|xp|ayarla|sifirla|rol-ekle|rol-sil|roller`",
    ],
    "🎭 Roller": ["`/tepkirol ekle|sil|liste` • `/davetrol ekle|sil|liste`"],
    "💬 Otomatik yanıt": ["`/otoyanit ekle|sil|liste`"],
    "💰 Sosyal": ["`/profil` `/hakkimda` `/kredi` `/kredi-gonder` `/gunluk` `/itibar` `/zenginler`"],
    "⭐ Ekstra": ["`/yildiz kanal|esik|kapat` • `/ozelses kur|kapat` • `/ses-limit`"],
    "ℹ️ Genel": ["`/surum` `/guncelle` `/yardim` `/ping` `/avatar` `/kullanici` `/sunucu` `/embed` `/yaz`"],
}


class EmbedModal(discord.ui.Modal, title="Embed oluştur"):
    baslik = discord.ui.TextInput(label="Başlık", required=False, max_length=256)
    aciklama = discord.ui.TextInput(label="Açıklama", style=discord.TextStyle.paragraph, max_length=4000)
    renk = discord.ui.TextInput(label="Renk (örn: #5865F2)", required=False, max_length=7, placeholder="#5865F2")
    resim = discord.ui.TextInput(label="Resim linki (isteğe bağlı)", required=False)
    alt_yazi = discord.ui.TextInput(label="Alt yazı (isteğe bağlı)", required=False, max_length=2048)

    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, i: discord.Interaction):
        color = RENK
        if self.renk.value:
            try:
                color = discord.Color.from_str(self.renk.value if self.renk.value.startswith("#") else "#" + self.renk.value)
            except ValueError:
                pass
        e = discord.Embed(title=self.baslik.value or None, description=self.aciklama.value, color=color)
        if self.resim.value.startswith("http"):
            e.set_image(url=self.resim.value)
        if self.alt_yazi.value:
            e.set_footer(text=self.alt_yazi.value)
        try:
            await self.channel.send(embed=e)
        except discord.HTTPException:
            return await i.response.send_message(embed=err("Gönderilemedi. Resim linkini ve botun kanal yetkisini kontrol et."),
                                                 ephemeral=True)
        await i.response.send_message(embed=ok(f"Embed {self.channel.mention} kanalına gönderildi."), ephemeral=True)


class Genel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="yardim", description="Tüm komutları göster")
    async def yardim(self, i: discord.Interaction):
        e = discord.Embed(title="📖 Komutlar", color=RENK,
                          description="Ayar komutlarını sadece yetkililer görür. Mesajlarda `{kullanici}`, `{isim}`, "
                                      "`{sunucu}`, `{uye_sayisi}` değişkenlerini kullanabilirsin.")
        for name, lines in YARDIM.items():
            e.add_field(name=name, value="\n".join(lines), inline=False)
        await i.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="ping", description="Botun gecikmesi")
    async def ping(self, i: discord.Interaction):
        await i.response.send_message(f"🏓 Pong! **{round(self.bot.latency * 1000)} ms**")

    @app_commands.command(name="avatar", description="Profil resmini büyük göster")
    async def avatar(self, i: discord.Interaction, uye: discord.User | None = None):
        uye = uye or i.user
        e = discord.Embed(title=f"{uye.display_name} avatarı", color=RENK)
        e.set_image(url=uye.display_avatar.replace(size=1024).url)
        await i.response.send_message(embed=e)

    @app_commands.command(name="kullanici", description="Kullanıcı bilgisi")
    @app_commands.guild_only()
    async def kullanici(self, i: discord.Interaction, uye: discord.Member | None = None):
        uye = uye or i.user
        e = discord.Embed(title=str(uye), color=uye.color if uye.color.value else RENK)
        e.set_thumbnail(url=uye.display_avatar.url)
        e.add_field(name="ID", value=uye.id)
        e.add_field(name="Hesap", value=f"<t:{int(uye.created_at.timestamp())}:R>")
        if uye.joined_at:
            e.add_field(name="Katılma", value=f"<t:{int(uye.joined_at.timestamp())}:R>")
        roles = [r.mention for r in reversed(uye.roles[1:])]
        e.add_field(name=f"Roller ({len(roles)})", value=" ".join(roles)[:1000] or "Yok", inline=False)
        await i.response.send_message(embed=e)

    @app_commands.command(name="sunucu", description="Sunucu bilgisi")
    @app_commands.guild_only()
    async def sunucu(self, i: discord.Interaction):
        g = i.guild
        e = discord.Embed(title=g.name, color=RENK)
        if g.icon:
            e.set_thumbnail(url=g.icon.url)
        e.add_field(name="Sahip", value=f"<@{g.owner_id}>")
        e.add_field(name="Oluşturulma", value=f"<t:{int(g.created_at.timestamp())}:R>")
        e.add_field(name="Üye", value=g.member_count)
        e.add_field(name="Kanallar", value=f"💬 {len(g.text_channels)} • 🔊 {len(g.voice_channels)}")
        e.add_field(name="Roller", value=len(g.roles))
        e.add_field(name="Takviye", value=f"Seviye {g.premium_tier} ({g.premium_subscription_count})")
        e.set_footer(text=f"ID: {g.id}")
        await i.response.send_message(embed=e)

    @app_commands.command(name="embed", description="Bir kanala güzel görünümlü (embed) mesaj gönder")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def embed(self, i: discord.Interaction, kanal: discord.TextChannel | None = None):
        await i.response.send_modal(EmbedModal(kanal or i.channel))

    @app_commands.command(name="yaz", description="Botun ağzından mesaj yaz")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def yaz(self, i: discord.Interaction, mesaj: str, kanal: discord.TextChannel | None = None):
        kanal = kanal or i.channel
        await kanal.send(mesaj.replace("\\n", "\n"), allowed_mentions=discord.AllowedMentions(everyone=False, roles=False))
        await i.response.send_message(embed=ok("Gönderildi."), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Genel(bot))
