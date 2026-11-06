"""Seviye sistemi: ayrı yazı ve ses seviyeleri, seviye kartları, sıralama, seviye rolleri."""
import io
import os
import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.helpers import RENK, err, format_message, ok
from utils.images import levelup_card, rank_card

VARSAYILAN_MESAJ = "🎉 Tebrikler {kullanici}, yazı seviyen **{seviye}** oldu!"
VARSAYILAN_SES_MESAJ = "🎙️ Tebrikler {kullanici}, ses seviyen **{seviye}** oldu!"
MESAJ_BEKLEME = 60  # aynı kişi 60 saniyede bir yazı XP'si kazanır
VARSAYILAN_AFK_DK = 10  # mikrofonu kapalı + ses sohbetine yazmayan kişi bu kadar dakika sonra XP alamaz

# Tür → (xp sütunu, seviye sütunu). Sütun adları sabit, kullanıcıdan gelmez.
COLS = {"yazi": ("xp", "level"), "ses": ("voice_xp", "voice_level")}
TUR_ADI = {"yazi": "Yazı", "ses": "Ses"}
VARSAYILAN_ARALIK = {"yazi": (15, 25), "ses": (5, 10)}
TUR_SECENEK = [app_commands.Choice(name="Yazı", value="yazi"), app_commands.Choice(name="Ses", value="ses")]


def levelup_bg(guild_id: int) -> str:
    return os.path.join("data", "arkaplanlar", f"{guild_id}_seviye.png")


def needed_xp(level: int) -> int:
    """Bir sonraki seviye için gereken XP."""
    return 5 * level * level + 50 * level + 100


def recalc(level: int, xp: int, delta: int) -> tuple[int, int]:
    """Toplam XP'ye çevirip delta ekler/çıkarır, (seviye, xp) döner."""
    total = max(0, sum(needed_xp(l) for l in range(level)) + xp + delta)
    level = 0
    while total >= needed_xp(level):
        total -= needed_xp(level)
        level += 1
    return level, total


class Seviye(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cooldown: dict[tuple[int, int], float] = {}
        # Seste son "aktiflik" anı: mikrofonu açması, ses durumunu değiştirmesi, ses sohbetine yazması
        self.voice_active: dict[tuple[int, int], float] = {}
        self.voice_xp.start()

    def cog_unload(self):
        self.voice_xp.cancel()

    grup = app_commands.Group(name="seviye", description="Seviye sistemi ayarları",
                              default_permissions=discord.Permissions(manage_guild=True), guild_only=True)

    # ================= yardımcılar =================
    def is_on(self, guild_id: int) -> bool:
        return self.bot.db.get(guild_id, "level_enabled", True)

    def is_blocked(self, member: discord.Member) -> bool:
        """Üyede XP almasını engelleyen bir rol (ör. Cezalı) var mı?"""
        blocked = set(self.bot.db.get(member.guild.id, "level_ignored_roles", []))
        return any(r.id in blocked for r in member.roles)

    def xp_range(self, guild_id: int, tur: str) -> tuple[int, int]:
        r = self.bot.db.get(guild_id, f"xp_range_{tur}")
        return tuple(r) if r else VARSAYILAN_ARALIK[tur]

    def rank_of(self, guild_id: int, row, tur: str) -> int:
        xc, lc = COLS[tur]
        return self.bot.db.one(
            f"SELECT COUNT(*)+1 c FROM levels WHERE guild_id=? AND ({lc}>? OR ({lc}=? AND {xc}>?))",
            (guild_id, row[lc], row[lc], row[xc]))["c"]

    async def change_xp(self, member: discord.Member, tur: str, delta: int, channel=None, announce: bool = True):
        """XP ekler (+) veya çıkarır (-). Seviye değişirse rolleri ayarlar, yükselişte duyurur."""
        db = self.bot.db
        xc, lc = COLS[tur]
        row = db.level_row(member.guild.id, member.id)
        old_level = row[lc]
        if delta >= 0:
            xp, level = row[xc] + delta, old_level
            while xp >= needed_xp(level):
                xp -= needed_xp(level)
                level += 1
        else:
            level, xp = recalc(old_level, row[xc], delta)
        db.execute(f"UPDATE levels SET {xc}=?, {lc}=? WHERE guild_id=? AND user_id=?",
                   (xp, level, member.guild.id, member.id))
        if level != old_level:
            await self.sync_roles(member)
            if level > old_level and announce:
                await self.announce(member, tur, old_level, level, channel)
        return old_level, level

    async def sync_roles(self, member: discord.Member):
        """Seviye rolleri: yazı ve ses seviyesinden YÜKSEK olana göre verilir/alınır."""
        db = self.bot.db
        g = member.guild
        row = db.level_row(g.id, member.id)
        best = max(row["level"], row["voice_level"])
        add, remove = [], []
        for r in db.all("SELECT * FROM level_roles WHERE guild_id=?", (g.id,)):
            role = g.get_role(r["role_id"])
            if role is None or role >= g.me.top_role:
                continue
            if r["level"] <= best and role not in member.roles:
                add.append(role)
            elif r["level"] > best and role in member.roles:
                remove.append(role)
        try:
            if add:
                await member.add_roles(*add, reason=f"Seviye ödülü (seviye {best})")
            if remove:
                await member.remove_roles(*remove, reason=f"Seviye düştü (seviye {best})")
        except discord.HTTPException:
            pass

    async def announce(self, member: discord.Member, tur: str, old: int, new: int, fallback_channel):
        db = self.bot.db
        g = member.guild
        if tur == "yazi":
            if db.get(g.id, "level_announce", True) is False:
                return
            ch_id = db.get(g.id, "level_channel")
            template = db.get(g.id, "level_message", VARSAYILAN_MESAJ)
        else:
            if db.get(g.id, "voice_announce", True) is False:
                return
            ch_id = db.get(g.id, "voice_level_channel") or db.get(g.id, "level_channel")
            template = db.get(g.id, "voice_level_message", VARSAYILAN_SES_MESAJ)
        target = g.get_channel(ch_id) if ch_id else fallback_channel
        if target is None:
            return
        text = self.render_text(template, member, tur, new)
        try:
            if db.get(g.id, "level_image", False):
                await target.send(content=text, file=await self.make_card(member, tur, old, new))
            else:
                await target.send(text)
        except discord.HTTPException:
            pass

    def render_text(self, template: str, member: discord.Member, tur: str, level: int, xp: int | None = None) -> str:
        if xp is None:
            xp = self.bot.db.level_row(member.guild.id, member.id)[COLS[tur][0]]
        need = needed_xp(level)
        text = format_message(template, member, seviye=level, xp=xp, gereken_xp=need, kalan_xp=max(0, need - xp),
                              tur=TUR_ADI[tur].lower())
        # Mesaj nasıl yazılmış olursa olsun, altta tür ve XP durumu her zaman görünür
        icon = "💬" if tur == "yazi" else "🎙️"
        fmt = lambda n: f"{n:,}".replace(",", ".")  # noqa: E731
        info = (f"-# {icon} {TUR_ADI[tur]} seviyesi {level} • {fmt(xp)} / {fmt(need)} XP • "
                f"{level + 1}. seviyeye {fmt(max(0, need - xp))} XP kaldı")
        return f"{text}\n{info}"

    async def make_card(self, member: discord.Member, tur: str, old: int, new: int,
                        xp: int | None = None) -> discord.File:
        avatar = await member.display_avatar.replace(size=256, format="png").read()
        color = member.color.to_rgb() if member.color.value else (88, 101, 242)
        title = "YAZI SEVİYESİ ATLADI!" if tur == "yazi" else "SES SEVİYESİ ATLADI!"
        if xp is None:
            xp = self.bot.db.level_row(member.guild.id, member.id)[COLS[tur][0]]
        img = levelup_card(avatar, member.display_name, old, new, levelup_bg(member.guild.id), color, title,
                           xp=xp, needed=needed_xp(new))
        return discord.File(img, filename="seviye.png")

    # ================= ses AFK takibi =================
    def mark_active(self, member: discord.Member):
        self.voice_active[(member.guild.id, member.id)] = time.monotonic()

    def afk_limit(self, guild_id: int) -> int:
        """Dakika cinsinden AFK sınırı. 0 = kontrol kapalı."""
        return self.bot.db.get(guild_id, "voice_afk_minutes", VARSAYILAN_AFK_DK)

    def voice_eligible(self, m: discord.Member) -> bool:
        """Seste XP alabilir mi? Sağır olan hiç alamaz; mikrofonu kapalı olan bir süre sonra alamaz."""
        v = m.voice
        if v is None or v.self_deaf or v.deaf:
            return False
        if not (v.self_mute or v.mute):
            return True                      # mikrofon açık
        if v.self_video or v.self_stream:
            return True                      # kamera / yayın açık
        limit = self.afk_limit(m.guild.id)
        if limit <= 0:
            return True
        last = self.voice_active.setdefault((m.guild.id, m.id), time.monotonic())
        return time.monotonic() - last < limit * 60

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState):
        if member.bot:
            return
        if after.channel is None:
            self.voice_active.pop((member.guild.id, member.id), None)
            return
        # Kanala girmek, kanal değiştirmek, mikrofon/kulaklık/kamera/yayın açıp kapatmak = aktiflik
        self.mark_active(member)

    # ================= XP kazanma =================
    @commands.Cog.listener()
    async def on_message(self, m: discord.Message):
        if m.guild is None or m.author.bot or not isinstance(m.author, discord.Member):
            return
        # Bulunduğu ses kanalının sohbetine yazdıysa seste aktif sayılır
        if m.author.voice and m.author.voice.channel and m.channel.id == m.author.voice.channel.id:
            self.mark_active(m.author)
        if not self.is_on(m.guild.id):
            return
        if m.channel.id in self.bot.db.get(m.guild.id, "level_ignored_channels", []):
            return
        if self.is_blocked(m.author):
            return
        prefixes = self.bot.db.get(m.guild.id, "level_ignored_prefixes", [])
        if prefixes and m.content.lower().startswith(tuple(prefixes)):
            return
        key = (m.guild.id, m.author.id)
        now = time.monotonic()
        if now - self.cooldown.get(key, 0) < MESAJ_BEKLEME:
            return
        self.cooldown[key] = now
        lo, hi = self.xp_range(m.guild.id, "yazi")
        await self.change_xp(m.author, "yazi", random.randint(lo, hi), m.channel)

    @tasks.loop(minutes=1)
    async def voice_xp(self):
        """Seste olanlara dakikada XP verir. Yalnız olanlar, sağırlar, AFK kanalı ve uzun süre
        mikrofonu kapalı kalıp ses sohbetine de yazmayanlar XP alamaz."""
        for g in self.bot.guilds:
            if not self.is_on(g.id) or not self.bot.db.get(g.id, "voice_xp", True):
                continue
            lo, hi = self.xp_range(g.id, "ses")
            for vc in g.voice_channels:
                if vc == g.afk_channel or self.voice_ignored(vc):
                    continue
                humans = [m for m in vc.members if not m.bot]
                # Kanalda en az 2 kişi kulaklığı açık olmalı (tek başına ya da sağır yan hesapla farm olmasın)
                listening = [m for m in humans if m.voice and not (m.voice.self_deaf or m.voice.deaf)]
                if len(listening) < 2:
                    continue
                for m in listening:
                    if not self.voice_eligible(m):
                        continue
                    if self.is_blocked(m):
                        continue
                    # Duyuru kanalı ayarlanmamışsa ses kanalının kendi sohbetine yazılır
                    await self.change_xp(m, "ses", random.randint(lo, hi), vc)

    @voice_xp.before_loop
    async def before_voice(self):
        await self.bot.wait_until_ready()

    # ================= herkese açık komutlar =================
    @app_commands.command(name="rank", description="Yazı ve ses seviye kartını göster")
    @app_commands.guild_only()
    async def rank(self, i: discord.Interaction, uye: discord.Member | None = None):
        uye = uye or i.user
        if uye.bot:
            return await i.response.send_message(embed=err("Botların seviyesi yok."), ephemeral=True)
        await i.response.defer()
        row = self.bot.db.level_row(i.guild_id, uye.id)
        rows = []
        for tur, label in (("yazi", "YAZI"), ("ses", "SES")):
            xc, lc = COLS[tur]
            rows.append((label, row[lc], row[xc], needed_xp(row[lc]), self.rank_of(i.guild_id, row, tur)))
        avatar = await uye.display_avatar.replace(size=256, format="png").read()
        color = uye.color.to_rgb() if uye.color.value else (88, 101, 242)
        img = rank_card(avatar, uye.display_name, rows, color)
        await i.followup.send(file=discord.File(img, filename="rank.png"))

    @app_commands.command(name="siralama", description="Sunucudaki en yüksek seviyeler")
    @app_commands.guild_only()
    @app_commands.choices(tur=TUR_SECENEK)
    async def siralama(self, i: discord.Interaction, tur: app_commands.Choice[str] | None = None,
                       sayfa: app_commands.Range[int, 1, 100] = 1):
        t = tur.value if tur else "yazi"
        xc, lc = COLS[t]
        rows = self.bot.db.all(
            f"SELECT user_id, {lc} lv, {xc} x FROM levels WHERE guild_id=? AND ({lc}>0 OR {xc}>0) "
            f"ORDER BY {lc} DESC, {xc} DESC LIMIT 10 OFFSET ?", (i.guild_id, (sayfa - 1) * 10))
        if not rows:
            return await i.response.send_message(embed=err("Bu sayfada kimse yok."), ephemeral=True)
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = [f"{medals.get(n, f'`#{n}`')} <@{r['user_id']}> • Seviye **{r['lv']}** ({r['x']} XP)"
                 for n, r in enumerate(rows, start=(sayfa - 1) * 10 + 1)]
        icon = "💬" if t == "yazi" else "🎙️"
        e = discord.Embed(title=f"{icon} {TUR_ADI[t]} sıralaması • {i.guild.name}", description="\n".join(lines),
                          color=RENK)
        e.set_footer(text=f"Sayfa {sayfa} • Diğer sıralama için tur seçeneğini kullan")
        await i.response.send_message(embed=e)

    # ================= genel ayarlar =================
    @grup.command(name="ac-kapat", description="Seviye sistemini aç veya kapat")
    async def ac_kapat(self, i: discord.Interaction, acik: bool):
        self.bot.db.set(i.guild_id, "level_enabled", acik)
        await i.response.send_message(embed=ok(f"Seviye sistemi {'açıldı' if acik else 'kapatıldı'}."))

    @grup.command(name="ses-xp", description="Seste durana XP verilsin mi?")
    async def ses_xp(self, i: discord.Interaction, acik: bool):
        self.bot.db.set(i.guild_id, "voice_xp", acik)
        await i.response.send_message(embed=ok(f"Ses XP'si {'açıldı' if acik else 'kapatıldı'}."))

    @grup.command(name="ses-afk", description="Mikrofonu kapalı ve ses sohbetine yazmayan kişi kaç dakika sonra XP alamasın (0 = kapalı)")
    async def ses_afk(self, i: discord.Interaction, dakika: app_commands.Range[int, 0, 600]):
        self.bot.db.set(i.guild_id, "voice_afk_minutes", dakika)
        if dakika == 0:
            msg = "Ses AFK kontrolü kapatıldı. Mikrofonu kapalı olanlar da XP almaya devam eder (sağırlar hariç)."
        else:
            msg = (f"Mikrofonu kapalı olup **{dakika} dakika** boyunca ses kanalının sohbetine yazmayan kişi XP alamayacak.\n"
                   "-# Mikrofonu açınca, ses sohbetine yazınca ya da kamera/yayın açınca tekrar XP almaya başlar. "
                   "Kulaklığı kapalı olan hiç XP alamaz.")
        await i.response.send_message(embed=ok(msg))

    @grup.command(name="xp-miktari", description="Yazı (mesaj başına) veya ses (dakika başına) kazanılan XP aralığını ayarla")
    @app_commands.choices(tur=TUR_SECENEK)
    @app_commands.describe(en_az="En az kaç XP", en_cok="En çok kaç XP (sabit miktar için en_az ile aynı yaz)")
    async def xp_miktari(self, i: discord.Interaction, tur: app_commands.Choice[str],
                         en_az: app_commands.Range[int, 0, 10000], en_cok: app_commands.Range[int, 0, 10000]):
        if en_az > en_cok:
            en_az, en_cok = en_cok, en_az
        self.bot.db.set(i.guild_id, f"xp_range_{tur.value}", [en_az, en_cok])
        birim = "her mesajda (60 saniyede bir)" if tur.value == "yazi" else "seste her dakika"
        miktar = f"{en_az}" if en_az == en_cok else f"{en_az}–{en_cok}"
        await i.response.send_message(embed=ok(f"{tur.name} XP'si: {birim} **{miktar} XP**."))

    @grup.command(name="ayarlar", description="Seviye sisteminin tüm ayarlarını göster")
    async def ayarlar(self, i: discord.Interaction):
        db, gid = self.bot.db, i.guild_id
        ch = lambda k: f"<#{c}>" if (c := db.get(gid, k)) else None  # noqa: E731
        y_lo, y_hi = self.xp_range(gid, "yazi")
        s_lo, s_hi = self.xp_range(gid, "ses")
        onoff = lambda v: "🟢 açık" if v else "🔴 kapalı"  # noqa: E731
        e = discord.Embed(title="📈 Seviye ayarları", color=RENK)
        e.add_field(name="Sistem", value=onoff(self.is_on(gid)))
        e.add_field(name="Resimli kart", value=onoff(db.get(gid, "level_image", False)))
        e.add_field(name="Rol kuralı", value="Yazı/ses seviyesinden yüksek olan")
        e.add_field(name="💬 Yazı", inline=False, value=(
            f"XP: {y_lo}–{y_hi} / mesaj • Duyuru: {onoff(db.get(gid, 'level_announce', True))}\n"
            f"Kanal: {ch('level_channel') or 'mesajın yazıldığı kanal'}"))
        e.add_field(name="🎙️ Ses", inline=False, value=(
            f"XP: {s_lo}–{s_hi} / dakika • Ses XP: {onoff(db.get(gid, 'voice_xp', True))} • "
            f"Duyuru: {onoff(db.get(gid, 'voice_announce', True))}\n"
            f"AFK sınırı: {f'{a} dk mikrofon kapalı + sohbete yazmazsa' if (a := self.afk_limit(gid)) else 'kapalı'}\n"
            f"Özel ses odalarında XP: {onoff(db.get(gid, 'tempvoice_xp', True))} • XP verilmeyen: "
            f"{', '.join(f'<#{c}>' for c in db.get(gid, 'level_ignored_voice', [])) or 'yok'}\n"
            f"Kanal: {ch('voice_level_channel') or ch('level_channel') or 'ses kanalının kendi sohbeti'}"))
        await i.response.send_message(embed=e, ephemeral=True)

    # ================= duyurular =================
    @grup.command(name="kanal", description="Yazı seviyesi duyurusunun kanalı (boş = mesajın yazıldığı kanal)")
    async def kanal(self, i: discord.Interaction, kanal: discord.TextChannel | None = None):
        self.bot.db.set(i.guild_id, "level_channel", kanal.id if kanal else None)
        await i.response.send_message(embed=ok(f"Yazı seviyesi duyuruları: {kanal.mention if kanal else 'mesajın yazıldığı kanal'}"))

    @grup.command(name="mesaj", description="Yazı seviyesi mesajı. Değişkenler: {kullanici} {seviye} {xp} {gereken_xp} {kalan_xp}")
    async def mesaj(self, i: discord.Interaction, mesaj: str):
        self.bot.db.set(i.guild_id, "level_message", mesaj.replace("\\n", "\n"))
        await i.response.send_message(embed=ok("Yazı seviyesi mesajı güncellendi. `/seviye test` ile deneyebilirsin."))

    @grup.command(name="duyuru", description="Yazı seviyesi atlayınca duyuru yapılsın mı?")
    async def duyuru(self, i: discord.Interaction, acik: bool):
        self.bot.db.set(i.guild_id, "level_announce", acik)
        await i.response.send_message(embed=ok(f"Yazı seviyesi duyuruları {'açıldı' if acik else 'kapatıldı'}."))

    @grup.command(name="ses-duyuru", description="Ses seviyesi duyurusunu ayarla (sadece değiştirmek istediklerini doldur)")
    @app_commands.describe(acik="Duyuru yapılsın mı?",
                           kanal="Duyuru kanalı (boş = yazı seviyesi kanalı, o da yoksa ses kanalının sohbeti)",
                           mesaj="Değişkenler: {kullanici} {isim} {seviye} {xp} {gereken_xp} {kalan_xp}",
                           kanali_sifirla="Kanal ayarını kaldır")
    async def ses_duyuru(self, i: discord.Interaction, acik: bool | None = None, kanal: discord.TextChannel | None = None,
                         mesaj: str | None = None, kanali_sifirla: bool = False):
        db, gid = self.bot.db, i.guild_id
        changes = []
        if acik is not None:
            db.set(gid, "voice_announce", acik)
            changes.append(f"Duyuru {'açık' if acik else 'kapalı'}")
        if kanali_sifirla:
            db.set(gid, "voice_level_channel", None)
            changes.append("Kanal ayarı kaldırıldı")
        elif kanal:
            db.set(gid, "voice_level_channel", kanal.id)
            changes.append(f"Kanal: {kanal.mention}")
        if mesaj:
            db.set(gid, "voice_level_message", mesaj.replace("\\n", "\n"))
            changes.append("Mesaj güncellendi")
        if not changes:
            return await i.response.send_message(embed=err("Hiçbir seçenek doldurmadın."), ephemeral=True)
        await i.response.send_message(embed=ok(" • ".join(changes)))

    @grup.command(name="resim", description="Seviye atlama duyurularına resimli kart eklensin mi?")
    async def resim(self, i: discord.Interaction, acik: bool):
        self.bot.db.set(i.guild_id, "level_image", acik)
        await i.response.send_message(embed=ok(f"Seviye kartı {'açıldı' if acik else 'kapatıldı'}. "
                                               "`/seviye test` ile görebilirsin."))

    @grup.command(name="arkaplan", description="Seviye kartının arka planını yükle (boş bırakırsan varsayılana döner)")
    async def arkaplan(self, i: discord.Interaction, resim: discord.Attachment | None = None):
        path = levelup_bg(i.guild_id)
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
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            Image.open(io.BytesIO(await resim.read())).convert("RGB").save(path, "PNG")
        except Exception:
            return await i.followup.send(embed=err("Bu resim açılamadı."))
        await i.followup.send(embed=ok("Arka plan kaydedildi. `/seviye test` ile görebilirsin."))

    @grup.command(name="test", description="Seviye atlama duyurusunu kendinle dene (seviyeni değiştirmez)")
    @app_commands.choices(tur=TUR_SECENEK)
    async def test(self, i: discord.Interaction, tur: app_commands.Choice[str] | None = None):
        await i.response.defer()
        t = tur.value if tur else "yazi"
        db = self.bot.db
        level = db.level_row(i.guild_id, i.user.id)[COLS[t][1]] + 1
        key, default = ("level_message", VARSAYILAN_MESAJ) if t == "yazi" else ("voice_level_message", VARSAYILAN_SES_MESAJ)
        text = self.render_text(db.get(i.guild_id, key, default), i.user, t, level, xp=0)
        if db.get(i.guild_id, "level_image", False):
            await i.followup.send(content=text, file=await self.make_card(i.user, t, level - 1, level, xp=0))
        else:
            await i.followup.send(content=text + "\n-# Resimli kart kapalı. Açmak için: `/seviye resim acik:True`")

    # ================= XP engelleri =================
    @grup.command(name="yoksay-kanal", description="Bu kanalda XP verilmesin / tekrar verilsin")
    async def yoksay(self, i: discord.Interaction, kanal: discord.TextChannel):
        chans = set(self.bot.db.get(i.guild_id, "level_ignored_channels", []))
        if kanal.id in chans:
            chans.remove(kanal.id)
            msg = f"{kanal.mention} kanalında tekrar XP verilecek."
        else:
            chans.add(kanal.id)
            msg = f"{kanal.mention} kanalında artık XP verilmeyecek."
        self.bot.db.set(i.guild_id, "level_ignored_channels", list(chans))
        await i.response.send_message(embed=ok(msg))

    def voice_ignored(self, vc) -> bool:
        """Bu ses kanalında XP verilmesin mi? (seçilen kanal/kategori ya da kapalıysa özel ses odaları)"""
        db = self.bot.db
        ignored = set(db.get(vc.guild.id, "level_ignored_voice", []))
        if vc.id in ignored or (vc.category_id and vc.category_id in ignored):
            return True
        if not db.get(vc.guild.id, "tempvoice_xp", True):
            if db.one("SELECT 1 FROM temp_channels WHERE channel_id=?", (vc.id,)):
                return True
        return False

    @grup.command(name="yoksay-ses", description="Bu ses kanalında veya kategorideki tüm ses kanallarında XP verilmesin / tekrar verilsin")
    @app_commands.describe(kanal="Ses kanalı ya da kategori (kategori seçersen içindeki tüm ses kanalları)")
    async def yoksay_ses(self, i: discord.Interaction,
                         kanal: discord.VoiceChannel | discord.StageChannel | discord.CategoryChannel):
        ids = set(self.bot.db.get(i.guild_id, "level_ignored_voice", []))
        tur = "kategorideki ses kanallarında" if isinstance(kanal, discord.CategoryChannel) else "kanalında"
        if kanal.id in ids:
            ids.remove(kanal.id)
            msg = f"**{kanal.name}** {tur} tekrar ses XP'si verilecek."
        else:
            ids.add(kanal.id)
            msg = f"**{kanal.name}** {tur} artık ses XP'si verilmeyecek."
        self.bot.db.set(i.guild_id, "level_ignored_voice", list(ids))
        liste = ", ".join(f"<#{c}>" for c in ids) or "yok"
        await i.response.send_message(embed=ok(f"{msg}\nXP verilmeyen ses kanalları/kategoriler: {liste}"))

    @grup.command(name="ozelses-xp", description="/ozelses ile açılan kişiye özel ses odalarında XP verilsin mi?")
    async def ozelses_xp(self, i: discord.Interaction, acik: bool):
        self.bot.db.set(i.guild_id, "tempvoice_xp", acik)
        await i.response.send_message(embed=ok(
            f"Özel ses odalarında XP {'verilecek' if acik else 'verilmeyecek'}."))

    @grup.command(name="yoksay-rol", description="Bu role sahip olanlar XP alamasın (ör. Cezalı) / tekrar alsın")
    async def yoksay_rol(self, i: discord.Interaction, rol: discord.Role):
        roles = set(self.bot.db.get(i.guild_id, "level_ignored_roles", []))
        if rol.id in roles:
            roles.remove(rol.id)
            msg = f"{rol.mention} rolündekiler tekrar XP alabilecek."
        else:
            roles.add(rol.id)
            msg = f"{rol.mention} rolündekiler artık yazı ve ses XP'si alamayacak."
        self.bot.db.set(i.guild_id, "level_ignored_roles", list(roles))
        await i.response.send_message(embed=ok(msg))

    @grup.command(name="yoksay-onek", description="Bu işaretle başlayan mesajlar XP vermesin (ör. ! veya m!). Tekrar yazarsan kaldırılır")
    @app_commands.describe(onek="Başka botların komut ön eki, örn: !  .  m!  p!")
    async def yoksay_onek(self, i: discord.Interaction, onek: app_commands.Range[str, 1, 10]):
        onek = onek.strip().lower()
        prefixes = set(self.bot.db.get(i.guild_id, "level_ignored_prefixes", []))
        if onek in prefixes:
            prefixes.remove(onek)
            msg = f"`{onek}` ile başlayan mesajlar tekrar XP verecek."
        else:
            prefixes.add(onek)
            msg = f"`{onek}` ile başlayan mesajlar artık XP vermeyecek."
        self.bot.db.set(i.guild_id, "level_ignored_prefixes", sorted(prefixes))
        liste = " ".join(f"`{p}`" for p in sorted(prefixes)) or "yok"
        await i.response.send_message(embed=ok(f"{msg}\nYoksayılan ön ekler: {liste}"))

    # ================= elle düzenleme =================
    @grup.command(name="xp", description="Üyeye elle yazı veya ses XP'si ekle/çıkar")
    @app_commands.choices(islem=[app_commands.Choice(name="Ekle", value="ekle"),
                                 app_commands.Choice(name="Çıkar", value="cikar")],
                          tur=TUR_SECENEK)
    async def xp_komut(self, i: discord.Interaction, uye: discord.Member, islem: app_commands.Choice[str],
                       miktar: app_commands.Range[int, 1, 10_000_000], tur: app_commands.Choice[str] | None = None):
        if uye.bot:
            return await i.response.send_message(embed=err("Botların seviyesi yok."), ephemeral=True)
        await i.response.defer()
        t = tur.value if tur else "yazi"
        delta = miktar if islem.value == "ekle" else -miktar
        old, new = await self.change_xp(uye, t, delta, i.channel)
        row = self.bot.db.level_row(i.guild_id, uye.id)
        xc, _ = COLS[t]
        verb = "eklendi" if delta > 0 else "çıkarıldı"
        await i.followup.send(embed=ok(
            f"{uye.mention} kullanıcısına **{miktar}** {TUR_ADI[t].lower()} XP'si {verb}.\n"
            f"{TUR_ADI[t]} seviyesi: **{old} → {new}** • Şu anki XP: {row[xc]} / {needed_xp(new)}"))

    @grup.command(name="ayarla", description="Üyenin yazı veya ses seviyesini doğrudan ayarla")
    @app_commands.choices(tur=TUR_SECENEK)
    async def ayarla(self, i: discord.Interaction, uye: discord.Member, seviye: app_commands.Range[int, 0, 1000],
                     tur: app_commands.Choice[str] | None = None):
        t = tur.value if tur else "yazi"
        xc, lc = COLS[t]
        self.bot.db.level_row(i.guild_id, uye.id)
        self.bot.db.execute(f"UPDATE levels SET {lc}=?, {xc}=0 WHERE guild_id=? AND user_id=?", (seviye, i.guild_id, uye.id))
        await self.sync_roles(uye)
        await i.response.send_message(embed=ok(f"{uye.mention} {TUR_ADI[t].lower()} seviyesi artık **{seviye}**."))

    @grup.command(name="sifirla", description="Bir üyenin ya da herkesin seviyelerini sıfırla")
    @app_commands.choices(tur=[app_commands.Choice(name="Hepsi", value="hepsi")] + TUR_SECENEK)
    async def sifirla(self, i: discord.Interaction, uye: discord.Member | None = None,
                      tur: app_commands.Choice[str] | None = None):
        t = tur.value if tur else "hepsi"
        if t == "hepsi":
            sql_set = "xp=0, level=0, voice_xp=0, voice_level=0"
            adi = "yazı ve ses seviyeleri"
        else:
            sql_set = f"{COLS[t][0]}=0, {COLS[t][1]}=0"
            adi = f"{TUR_ADI[t].lower()} seviyesi"
        if uye:
            self.bot.db.execute(f"UPDATE levels SET {sql_set} WHERE guild_id=? AND user_id=?", (i.guild_id, uye.id))
            await self.sync_roles(uye)
            return await i.response.send_message(embed=ok(f"{uye.mention} {adi} sıfırlandı."))
        view = Onay(i.user.id)
        await i.response.send_message(f"⚠️ **Herkesin** {adi} silinecek. Emin misin?", view=view, ephemeral=True)
        await view.wait()
        if view.value:
            self.bot.db.execute(f"UPDATE levels SET {sql_set} WHERE guild_id=?", (i.guild_id,))
            await i.followup.send(embed=ok(f"Herkesin {adi} sıfırlandı. (Seviye rolleri üyelerde kalır.)"), ephemeral=True)

    # ================= seviye rolleri =================
    @grup.command(name="rol-ekle", description="Bir seviyeye ulaşınca verilecek rol (yazı/ses seviyesinden yüksek olana bakılır)")
    async def rol_ekle(self, i: discord.Interaction, seviye: app_commands.Range[int, 1, 1000], rol: discord.Role):
        if rol >= i.guild.me.top_role or rol.managed:
            return await i.response.send_message(embed=err("Bu rolü veremem (botun rolünden yüksek ya da özel bir rol)."),
                                                 ephemeral=True)
        self.bot.db.execute("INSERT OR REPLACE INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?)",
                            (i.guild_id, seviye, rol.id))
        await i.response.send_message(embed=ok(
            f"Yazı **veya** ses seviyesi **{seviye}** olanlara {rol.mention} verilecek.\n"
            "-# Mevcut üyeler rolü bir sonraki seviye değişiminde alır."))

    @grup.command(name="rol-sil", description="Seviye rolünü kaldır")
    async def rol_sil(self, i: discord.Interaction, seviye: int):
        self.bot.db.execute("DELETE FROM level_roles WHERE guild_id=? AND level=?", (i.guild_id, seviye))
        await i.response.send_message(embed=ok(f"{seviye}. seviye rolü kaldırıldı."))

    @grup.command(name="roller", description="Seviye rollerini listele")
    async def roller(self, i: discord.Interaction):
        rows = self.bot.db.all("SELECT * FROM level_roles WHERE guild_id=? ORDER BY level", (i.guild_id,))
        text = "\n".join(f"Seviye **{r['level']}** → <@&{r['role_id']}>" for r in rows) or "Henüz seviye rolü yok."
        e = discord.Embed(title="Seviye rolleri", description=text, color=RENK)
        e.set_footer(text="Yazı ve ses seviyesinden hangisi yüksekse ona göre verilir.")
        await i.response.send_message(embed=e)


class Onay(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.value = None

    async def interaction_check(self, i: discord.Interaction) -> bool:
        return i.user.id == self.user_id

    @discord.ui.button(label="Evet, sıfırla", style=discord.ButtonStyle.danger)
    async def yes(self, i: discord.Interaction, _):
        self.value = True
        await i.response.edit_message(content="Sıfırlanıyor...", view=None)
        self.stop()

    @discord.ui.button(label="Vazgeç", style=discord.ButtonStyle.secondary)
    async def no(self, i: discord.Interaction, _):
        self.value = False
        await i.response.edit_message(content="İptal edildi.", view=None)
        self.stop()


async def setup(bot):
    await bot.add_cog(Seviye(bot))
