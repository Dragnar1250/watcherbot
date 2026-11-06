"""TürkBot - ana dosya. Çalıştırmak için: python main.py"""
import logging
import os
import sys

import discord
from discord import app_commands
from discord.ext import commands

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import updater
from utils.db import Database
from utils.helpers import err

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("bot.log", encoding="utf-8")],
)
log = logging.getLogger("turkbot")

COGS = [
    "cogs.karsilama",
    "cogs.davet",
    "cogs.log",
    "cogs.moderasyon",
    "cogs.cezali",
    "cogs.otomod",
    "cogs.seviye",
    "cogs.roller",
    "cogs.otoyanit",
    "cogs.sosyal",
    "cogs.genel",
    "cogs.ekstra",
    "cogs.guncelleme",
]


class TurkBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True          # Geliştirici portalında "Server Members Intent" açık olmalı
        intents.message_content = True  # Geliştirici portalında "Message Content Intent" açık olmalı
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, help_command=None)
        self.db = Database("data/bot.db")
        self.failed_cogs: list[str] = []
        self.exit_code = 0   # 3 = güncelleme için yeniden başlat

    async def setup_hook(self):
        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info("Modül yüklendi: %s", cog)
            except Exception:
                log.exception("Modül yüklenemedi: %s", cog)
                self.failed_cogs.append(cog)
        test_guild = os.getenv("TEST_SUNUCU_ID")
        if test_guild:
            # Test sunucusunda komutlar anında görünür
            guild = discord.Object(id=int(test_guild))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()
        log.info("%d slash komutu Discord'a kaydedildi.", len(synced))

    async def restart(self, code: int = 3):
        """Botu kapatır; baslat.bat güncelleyiciyi çalıştırıp yeniden açar."""
        self.exit_code = code
        await self.close()

    async def on_ready(self):
        log.info("Giriş yapıldı: %s (%s) | %d sunucu", self.user, self.user.id, len(self.guilds))
        state = updater.load_state()
        if self.failed_cogs and state["bekleyen"]:
            # Yeni kurulan sürümde bir modül bozuk: hemen eski sürüme dön
            log.error("Yeni sürümde yüklenemeyen modüller var (%s). Eski sürüme dönülüyor.", ", ".join(self.failed_cogs))
            updater.rollback("bazı modülleri yüklenemedi: " + ", ".join(self.failed_cogs))
            await self.restart(3)
            return
        updater.mark_ok()
        await self.change_presence(activity=discord.Game(name="/yardim"))


bot = TurkBot()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "Bu komut için yetkin yok."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "Botun bu işlem için yetkisi yok: " + ", ".join(error.missing_permissions)
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = f"Biraz yavaş! {error.retry_after:.0f} saniye sonra tekrar dene."
    elif isinstance(error, app_commands.NoPrivateMessage):
        msg = "Bu komut sadece sunucularda kullanılabilir."
    elif isinstance(error, app_commands.TransformerError):
        if error.type == discord.AppCommandOptionType.channel:
            msg = ("Bot seçtiğin kanalı göremiyor. Kanal ayarları → İzinler'den bot rolüne **Kanalı Görüntüle** "
                   "ve **Mesaj Gönder** ver ya da botu Administrator yetkisiyle yeniden davet et.")
        elif error.type == discord.AppCommandOptionType.user:
            msg = "Bu kullanıcı bulunamadı ya da artık sunucuda değil."
        elif error.type == discord.AppCommandOptionType.role:
            msg = "Bu rol bulunamadı."
        else:
            msg = "Girdiğin değer anlaşılamadı, tekrar dene."
    elif isinstance(error, app_commands.CommandInvokeError) and isinstance(error.original, discord.Forbidden):
        msg = "Botun bunu yapmaya yetkisi yok. Bot rolünün yetkilerini ve sırasını kontrol et."
    else:
        log.exception("Komut hatası", exc_info=error)
        original = getattr(error, "original", error)
        msg = (f"Beklenmeyen bir hata oluştu (`{type(original).__name__}`). "
               "Ayrıntılar bot.log dosyasında.")
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=err(msg), ephemeral=True)
        else:
            await interaction.response.send_message(embed=err(msg), ephemeral=True)
    except discord.HTTPException:
        pass


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token or token == "BURAYA_TOKEN":
        print("HATA: .env dosyasına DISCORD_TOKEN yazılmamış. KURULUM.md dosyasına bak.")
        sys.exit(2)
    os.makedirs("data/arkaplanlar", exist_ok=True)
    if sys.platform == "win32" and os.getenv("UYKU_ENGELLE", "0") == "1":
        # Bot açık kaldığı sürece Windows'un uyku moduna geçmesini engelle (ekran yine kapanabilir)
        try:
            import ctypes
            ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            log.info("Uyku modu engellendi (bot açık olduğu sürece).")
        except Exception:
            log.warning("Uyku modu engellenemedi.")
    try:
        bot.run(token, log_handler=None)
        if bot.exit_code:
            sys.exit(bot.exit_code)
    except discord.LoginFailure:
        print("HATA: Token geçersiz. Geliştirici portalından yeni token alıp .env dosyasına yapıştır.")
        sys.exit(2)
    except discord.PrivilegedIntentsRequired:
        print("HATA: Geliştirici portalında 'Server Members Intent' ve 'Message Content Intent' açık değil.")
        sys.exit(2)
