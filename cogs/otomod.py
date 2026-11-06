"""Otomatik moderasyon: reklam, link, spam, büyük harf, küfür, toplu etiket."""
import re
import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from utils.helpers import mark_action, RENK, TURUNCU, err, ok, send_log

DAVET = re.compile(r"(discord\.gg|discord(app)?\.com/invite|dsc\.gg)/\S+", re.I)
LINK = re.compile(r"https?://\S+|www\.\S+", re.I)

FILTRELER = {
    "davet": "Discord davet linkleri",
    "link": "Tüm linkler",
    "spam": "Hızlı mesaj spamı (5 saniyede 5+ mesaj)",
    "buyukharf": "Çok fazla büyük harf (%70+)",
    "kufur": "Yasaklı kelimeler",
    "etiket": "Toplu etiket (5+ kişi)",
}

TR_LOWER = str.maketrans("Iİ", "ıi")


def tr_lower(s: str) -> str:
    return s.translate(TR_LOWER).lower()


class Otomod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recent: dict[tuple[int, int], deque] = defaultdict(lambda: deque(maxlen=10))

    grup = app_commands.Group(name="otomod", description="Otomatik moderasyon ayarları",
                              default_permissions=discord.Permissions(manage_guild=True), guild_only=True)

    def enabled(self, guild_id: int) -> dict:
        return self.bot.db.get(guild_id, "automod", {})

    @grup.command(name="filtre", description="Bir filtreyi aç/kapat")
    @app_commands.choices(filtre=[app_commands.Choice(name=v, value=k) for k, v in FILTRELER.items()])
    async def filtre(self, i: discord.Interaction, filtre: app_commands.Choice[str], acik: bool):
        conf = self.enabled(i.guild_id)
        conf[filtre.value] = acik
        self.bot.db.set(i.guild_id, "automod", conf)
        await i.response.send_message(embed=ok(f"**{filtre.name}** filtresi {'açıldı' if acik else 'kapatıldı'}."))

    @grup.command(name="ceza", description="Filtreye takılınca ne olsun?")
    @app_commands.choices(ceza=[
        app_commands.Choice(name="Sadece mesajı sil", value="sil"),
        app_commands.Choice(name="Sil + uyarı ver", value="uyar"),
        app_commands.Choice(name="Sil + 5 dakika sustur", value="sustur"),
    ])
    async def ceza(self, i: discord.Interaction, ceza: app_commands.Choice[str]):
        self.bot.db.set(i.guild_id, "automod_action", ceza.value)
        await i.response.send_message(embed=ok(f"Ceza: **{ceza.name}**"))

    @grup.command(name="kelime-ekle", description="Yasaklı kelime ekle (virgülle birden fazla)")
    async def kelime_ekle(self, i: discord.Interaction, kelimeler: str):
        words = set(self.bot.db.get(i.guild_id, "badwords", []))
        words |= {tr_lower(w.strip()) for w in kelimeler.split(",") if w.strip()}
        self.bot.db.set(i.guild_id, "badwords", sorted(words))
        await i.response.send_message(embed=ok(f"Yasaklı kelime sayısı: {len(words)}. Filtreyi açmayı unutma: `/otomod filtre`"),
                                      ephemeral=True)

    @grup.command(name="kelime-sil", description="Yasaklı kelimeyi kaldır")
    async def kelime_sil(self, i: discord.Interaction, kelime: str):
        words = set(self.bot.db.get(i.guild_id, "badwords", []))
        words.discard(tr_lower(kelime.strip()))
        self.bot.db.set(i.guild_id, "badwords", sorted(words))
        await i.response.send_message(embed=ok("Kelime kaldırıldı."), ephemeral=True)

    @grup.command(name="muaf-kanal", description="Bir kanalı otomoderasyondan muaf tut / muafiyeti kaldır")
    async def muaf_kanal(self, i: discord.Interaction, kanal: discord.TextChannel):
        chans = set(self.bot.db.get(i.guild_id, "automod_exempt_channels", []))
        if kanal.id in chans:
            chans.remove(kanal.id)
            msg = f"{kanal.mention} artık denetleniyor."
        else:
            chans.add(kanal.id)
            msg = f"{kanal.mention} otomoderasyondan muaf."
        self.bot.db.set(i.guild_id, "automod_exempt_channels", list(chans))
        await i.response.send_message(embed=ok(msg))

    @grup.command(name="muaf-rol", description="Bir rolü otomoderasyondan muaf tut / muafiyeti kaldır")
    async def muaf_rol(self, i: discord.Interaction, rol: discord.Role):
        roles = set(self.bot.db.get(i.guild_id, "automod_exempt_roles", []))
        if rol.id in roles:
            roles.remove(rol.id)
            msg = f"{rol.mention} artık denetleniyor."
        else:
            roles.add(rol.id)
            msg = f"{rol.mention} otomoderasyondan muaf."
        self.bot.db.set(i.guild_id, "automod_exempt_roles", list(roles))
        await i.response.send_message(embed=ok(msg))

    @grup.command(name="durum", description="Otomoderasyon ayarlarını göster")
    async def durum(self, i: discord.Interaction):
        conf = self.enabled(i.guild_id)
        db = self.bot.db
        e = discord.Embed(title="Otomoderasyon", color=RENK)
        e.description = "\n".join(f"{'🟢' if conf.get(k) else '🔴'} {v}" for k, v in FILTRELER.items())
        e.add_field(name="Ceza", value=db.get(i.guild_id, "automod_action", "sil"))
        e.add_field(name="Yasaklı kelime", value=str(len(db.get(i.guild_id, "badwords", []))))
        chans = db.get(i.guild_id, "automod_exempt_channels", [])
        roles = db.get(i.guild_id, "automod_exempt_roles", [])
        e.add_field(name="Muaf", value=(" ".join(f"<#{c}>" for c in chans) + " " + " ".join(f"<@&{r}>" for r in roles)).strip()
                    or "Yok", inline=False)
        e.set_footer(text="Mesajları Yönet yetkisi olanlar her zaman muaftır.")
        await i.response.send_message(embed=e, ephemeral=True)

    # ---------- denetim ----------
    def check(self, m: discord.Message, conf: dict) -> str | None:
        content = m.content
        if conf.get("davet") and DAVET.search(content):
            return "Davet linki paylaşmak yasak."
        if conf.get("link") and LINK.search(content):
            return "Link paylaşmak yasak."
        if conf.get("etiket") and len(set(m.raw_mentions)) >= 5:
            return "Toplu etiket atmak yasak."
        if conf.get("kufur"):
            words = self.bot.db.get(m.guild.id, "badwords", [])
            low = tr_lower(content)
            tokens = set(re.findall(r"\w+", low))
            for w in words:
                if (" " in w and w in low) or w in tokens:
                    return "Mesajında yasaklı kelime var."
        if conf.get("buyukharf"):
            letters = [c for c in content if c.isalpha()]
            if len(letters) >= 10 and sum(c.isupper() for c in letters) / len(letters) >= 0.7:
                return "Çok fazla büyük harf kullanma."
        if conf.get("spam"):
            q = self.recent[(m.guild.id, m.author.id)]
            now = time.monotonic()
            q.append(now)
            if len([t for t in q if now - t < 5]) >= 5:
                q.clear()
                return "Spam yapma."
        return None

    @commands.Cog.listener()
    async def on_message(self, m: discord.Message):
        if m.guild is None or m.author.bot or not isinstance(m.author, discord.Member):
            return
        conf = self.enabled(m.guild.id)
        if not any(conf.values()):
            return
        if m.author.guild_permissions.manage_messages:
            return
        db = self.bot.db
        if m.channel.id in db.get(m.guild.id, "automod_exempt_channels", []):
            return
        exempt_roles = set(db.get(m.guild.id, "automod_exempt_roles", []))
        if any(r.id in exempt_roles for r in m.author.roles):
            return

        reason = self.check(m, conf)
        if reason is None:
            return
        try:
            mark_action(self.bot, "msgdel", m.guild.id, m.id)
            await m.delete()
        except discord.HTTPException:
            pass
        try:
            await m.channel.send(f"{m.author.mention}, {reason}", delete_after=5)
        except discord.HTTPException:
            pass

        action = db.get(m.guild.id, "automod_action", "sil")
        if action == "uyar":
            db.execute("INSERT INTO warnings (guild_id, user_id, mod_id, reason, ts) VALUES (?, ?, ?, ?, ?)",
                       (m.guild.id, m.author.id, self.bot.user.id, f"Otomod: {reason}", time.time()))
        elif action == "sustur":
            try:
                mark_action(self.bot, "timeout", m.guild.id, m.author.id)
                await m.author.timeout(timedelta(minutes=5), reason=f"Otomod: {reason}")
            except discord.HTTPException:
                pass

        e = discord.Embed(title="🤖 Otomod", color=TURUNCU, timestamp=discord.utils.utcnow())
        e.add_field(name="Üye", value=m.author.mention)
        e.add_field(name="Kanal", value=m.channel.mention)
        e.add_field(name="Sebep", value=reason, inline=False)
        e.add_field(name="Mesaj", value=(m.content[:1000] or "*(boş)*"), inline=False)
        await send_log(self.bot, m.guild, e)


async def setup(bot):
    await bot.add_cog(Otomod(bot))
