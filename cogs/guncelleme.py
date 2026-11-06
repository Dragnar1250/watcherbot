"""Otomatik güncelleme: belirli aralıklarla GitHub'a bakar, yeni sürüm varsa botu yeniden başlatır."""
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import updater
from utils.helpers import RENK, err, ok, send_log

log = logging.getLogger("turkbot.guncelleme")
KONTROL_DK = 10


class Guncelleme(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_check: str | None = None
        self.auto_check.start()

    def cog_unload(self):
        self.auto_check.cancel()

    async def announce_and_restart(self, info: dict, by: str):
        e = discord.Embed(title="🔄 Bot güncelleniyor", color=RENK, timestamp=discord.utils.utcnow(),
                          description=f"Yeni sürüm: `{info['sha'][:7]}` — {info.get('mesaj') or 'açıklama yok'}\n"
                                      "Bot birkaç saniye içinde yeniden açılacak.")
        e.set_footer(text=by)
        for g in self.bot.guilds:
            await send_log(self.bot, g, e)
        log.info("Güncelleme bulundu (%s), yeniden başlatılıyor.", info["sha"][:7])
        await self.bot.restart(3)

    @tasks.loop(minutes=KONTROL_DK)
    async def auto_check(self):
        cfg = updater.config()
        if not cfg["repo"] or not cfg["auto"]:
            return
        if updater.load_state()["bekleyen"]:
            return  # az önce kurulan sürüm henüz onaylanmadı
        info = await asyncio.to_thread(updater.update_available, cfg)
        self.last_check = discord.utils.format_dt(discord.utils.utcnow(), "R")
        if info:
            await self.announce_and_restart(info, "Otomatik güncelleme")

    @auto_check.before_loop
    async def before(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(60)  # açılışta zaten kontrol edildi

    # ================= komutlar =================
    @app_commands.command(name="surum", description="Botun sürümünü ve güncelleme ayarlarını göster")
    async def surum(self, i: discord.Interaction):
        cfg = updater.config()
        s = updater.load_state()
        e = discord.Embed(title="📦 Sürüm bilgisi", color=RENK)
        if s["sha"]:
            e.add_field(name="Kurulu sürüm", value=f"`{s['sha'][:7]}` — {s.get('mesaj') or 'açıklama yok'}", inline=False)
        else:
            e.add_field(name="Kurulu sürüm", value="Elle kurulmuş (henüz GitHub'dan güncellenmedi)", inline=False)
        if cfg["repo"]:
            e.add_field(name="Depo", value=f"`{cfg['repo']}` ({cfg['branch']})")
            e.add_field(name="Otomatik güncelleme",
                        value=f"🟢 açık, {KONTROL_DK} dakikada bir" if cfg["auto"] else "🔴 kapalı")
            if self.last_check:
                e.add_field(name="Son kontrol", value=self.last_check)
        else:
            e.add_field(name="Otomatik güncelleme", value="Ayarlı değil. Açmak için: `/guncelle depo:kullaniciadi/depoadi`")
        await i.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="guncelle", description="GitHub'da yeni sürüm var mı hemen kontrol et (sadece bot sahibi)")
    @app_commands.describe(depo="İlk kurulumda bir kez yaz: kullaniciadi/depoadi (ya da GitHub linki). Sonra boş bırak.")
    async def guncelle(self, i: discord.Interaction, depo: str | None = None):
        if not await self.bot.is_owner(i.user):
            return await i.response.send_message(embed=err("Bu komutu sadece botun sahibi kullanabilir."), ephemeral=True)
        if depo is not None:
            repo = updater.parse_repo(depo)
            if repo is None:
                return await i.response.send_message(embed=err(
                    "Depo adı anlaşılamadı. Şöyle yaz: `kullaniciadi/depoadi` ya da `github.com/kullaniciadi/depoadi`"),
                    ephemeral=True)
            env_repo = updater.read_env().get("GUNCELLEME_DEPO", "").strip()
            if env_repo and env_repo != repo:
                return await i.response.send_message(embed=err(
                    f"`.env` dosyasında başka bir depo yazılı (`{env_repo}`) ve o öncelikli. "
                    "Ya oradaki satırı sil ya da orayı değiştir."), ephemeral=True)
            updater.save_repo(repo)
        cfg = updater.config()
        if not cfg["repo"]:
            return await i.response.send_message(
                embed=err("Güncelleme ayarlı değil. Bir kez şöyle yaz: `/guncelle depo:kullaniciadi/depoadi`"),
                ephemeral=True)
        await i.response.defer(ephemeral=True)
        info = await asyncio.to_thread(updater.remote_info, cfg)
        self.last_check = discord.utils.format_dt(discord.utils.utcnow(), "R")
        if info is None:
            return await i.followup.send(embed=err(
                f"`{cfg['repo']}` deposuna ulaşılamadı. Depo adı doğru mu, depo **Public** mi, içinde kod var mı? "
                "Ayrıntılar bot penceresinde yazıyor."))
        s = updater.load_state()
        if info["sha"] == s["sha"]:
            return await i.followup.send(embed=ok(f"Bot zaten güncel (`{info['sha'][:7]}`)."))
        if info["sha"] in s["kotu"]:
            return await i.followup.send(embed=err(
                f"Son sürüm (`{info['sha'][:7]}`) daha önce bozuk olduğu için kurulmadı. Düzeltilmiş sürüm bekleniyor."))
        await i.followup.send(embed=ok(f"Yeni sürüm bulundu: `{info['sha'][:7]}` — {info.get('mesaj') or ''}\n"
                                       "Bot güncellenip yeniden başlatılıyor..."))
        await self.announce_and_restart(info, f"{i.user} tarafından")


async def setup(bot):
    await bot.add_cog(Guncelleme(bot))
