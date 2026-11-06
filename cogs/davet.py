"""Davet takibi: üyenin hangi davet linkiyle geldiğini bulur, o linke bağlı rolleri verir."""
import asyncio
import re

import discord
from discord import app_commands
from discord.ext import commands

from utils.helpers import RENK, err, mark_action, ok

KOD = re.compile(r"(?:https?://)?(?:www\.)?(?:discord(?:app)?\.com/invite|discord\.gg)/([\w-]+)|^([\w-]+)$", re.I)
VANITY = "__vanity__"  # sunucunun özel URL'si (discord.gg/sunucuadi) için kayıt anahtarı


def parse_code(text: str) -> str | None:
    m = KOD.search(text.strip())
    if not m:
        return None
    return m.group(1) or m.group(2)


def find_used(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> str | None:
    """Önceki ve şimdiki davet kullanım sayılarına bakıp hangi davetin kullanıldığını bulur.
    before/after: {kod: (kullanım, en_fazla_kullanım)}"""
    used = [code for code, (uses, _) in after.items() if uses > before.get(code, (0, 0))[0]]
    if len(used) == 1:
        return used[0]
    if len(used) > 1:
        return None  # aynı anda birden fazla kişi girdi, emin olamayız
    # Tek kullanımlık / son hakkı kullanılan davet silinmiş olabilir
    gone = [code for code, (uses, max_uses) in before.items()
            if code not in after and max_uses and uses == max_uses - 1]
    return gone[0] if len(gone) == 1 else None


class Davet(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # {sunucu_id: {kod: (kullanım, en_fazla)}}
        self.cache: dict[int, dict[str, tuple[int, int]]] = {}
        self.inviters: dict[int, dict[str, int | None]] = {}
        self.join_info: dict[tuple[int, int], asyncio.Future] = {}

    grup = app_commands.Group(name="davetrol", description="Belirli bir davet linkiyle gelenlere rol ver",
                              default_permissions=discord.Permissions(manage_roles=True), guild_only=True)

    # ================= önbellek =================
    async def snapshot(self, guild: discord.Guild) -> dict[str, tuple[int, int]] | None:
        """Sunucunun davetlerini okur. Bot 'Sunucuyu Yönet' yetkisine sahip değilse None döner."""
        try:
            invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return None
        data = {inv.code: (inv.uses or 0, inv.max_uses or 0) for inv in invites}
        self.inviters[guild.id] = {inv.code: (inv.inviter.id if inv.inviter else None) for inv in invites}
        if guild.vanity_url_code:
            try:
                vanity = await guild.vanity_invite()
                if vanity:
                    data[VANITY] = (vanity.uses or 0, 0)
            except (discord.Forbidden, discord.HTTPException):
                pass
        return data

    async def refresh(self, guild: discord.Guild):
        snap = await self.snapshot(guild)
        if snap is not None:
            self.cache[guild.id] = snap

    @commands.Cog.listener()
    async def on_ready(self):
        for g in self.bot.guilds:
            await self.refresh(g)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self.refresh(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild and invite.guild.id in self.cache:
            self.cache[invite.guild.id][invite.code] = (invite.uses or 0, invite.max_uses or 0)
            self.inviters.setdefault(invite.guild.id, {})[invite.code] = invite.inviter.id if invite.inviter else None

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        # Silinmeyi hemen işlemiyoruz: tek kullanımlık davet, üye girişinden ÖNCE silinmiş olarak gelebilir.
        # Bir sonraki girişte önbellek zaten yenileniyor.
        pass

    # ================= üye girişi =================
    def _future(self, key) -> asyncio.Future:
        fut = self.join_info.get(key)
        if fut is None:
            fut = asyncio.get_running_loop().create_future()
            self.join_info[key] = fut
        return fut

    async def wait_info(self, member: discord.Member, timeout: float = 6) -> dict | None:
        """Log modülü, giriş logunu atmadan önce davet bilgisini buradan bekler."""
        key = (member.guild.id, member.id)
        try:
            return await asyncio.wait_for(asyncio.shield(self._future(key)), timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self.join_info.pop(key, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        key = (member.guild.id, member.id)
        fut = self._future(key)
        info = None
        try:
            info = await self._process_join(member)
        finally:
            if not fut.done():
                fut.set_result(info)
            # Log modülü hiç sormazsa birikmesin
            if len(self.join_info) > 500:
                for k in [k for k, f in self.join_info.items() if f.done()]:
                    self.join_info.pop(k, None)

    async def _process_join(self, member: discord.Member) -> dict | None:
        """Kullanılan daveti bulur, rolleri verir. Log için bilgi döner (bilgi yoksa None)."""
        g = member.guild
        before = self.cache.get(g.id)
        # Davet edenleri önbellek yenilenmeden ÖNCE al: tek kullanımlık davet silinince bilgisi kaybolmasın
        inviters = dict(self.inviters.get(g.id, {}))
        after = await self.snapshot(g)
        if after is None:
            return None  # yetki yok
        inviters.update(self.inviters.get(g.id, {}))
        self.cache[g.id] = after
        if before is None:
            return None
        code = find_used(before, after)

        given = []
        if code and not member.bot:
            rows = self.bot.db.all("SELECT role_id FROM invite_roles WHERE guild_id=? AND code=?", (g.id, code))
            roles = [r for row in rows if (r := g.get_role(row["role_id"])) and r < g.me.top_role and not r.managed]
            if roles:
                mark_action(self.bot, "roles", g.id, member.id)
                try:
                    await member.add_roles(*roles, reason=f"Davet rolü ({code_text(code, g)})")
                    given = roles
                except discord.HTTPException:
                    pass
        return {
            "code": code_text(code, g) if code else None,
            "inviter": inviters.get(code) if code and code != VANITY else None,
            "roles": [r.mention for r in given],
        }

    # ================= komutlar =================
    async def resolve_code(self, i: discord.Interaction, text: str) -> str | None:
        t = text.strip().lower()
        if t in ("ozel", "özel", "vanity", "ozel-url", "özel-url"):
            if not i.guild.vanity_url_code:
                await i.response.send_message(embed=err("Bu sunucunun özel URL'si (discord.gg/isim) yok."), ephemeral=True)
                return None
            return VANITY
        code = parse_code(text)
        if code is None:
            await i.response.send_message(embed=err("Davet linki anlaşılamadı. Örnek: `discord.gg/AbC123` ya da `AbC123`"),
                                          ephemeral=True)
            return None
        if i.guild.vanity_url_code and code.lower() == i.guild.vanity_url_code.lower():
            return VANITY
        snap = await self.snapshot(i.guild)
        if snap is None:
            await i.response.send_message(embed=err("Davetleri göremiyorum. Bota **Sunucuyu Yönet** yetkisi ver."),
                                          ephemeral=True)
            return None
        self.cache[i.guild_id] = snap
        if code not in snap:
            await i.response.send_message(embed=err(f"`{code}` bu sunucuya ait geçerli bir davet değil."), ephemeral=True)
            return None
        return code

    @grup.command(name="ekle", description="Bu davet linkiyle gelenlere rol ver (aynı linke birden fazla rol eklenebilir)")
    @app_commands.describe(davet="Davet linki ya da kodu (örn: discord.gg/AbC123). Özel URL için: ozel")
    async def ekle(self, i: discord.Interaction, davet: str, rol: discord.Role):
        if rol.managed or rol.is_default():
            return await i.response.send_message(embed=err("Bu rol elle verilemez."), ephemeral=True)
        if rol >= i.guild.me.top_role:
            return await i.response.send_message(embed=err("Bu rol botun rolünden yüksek. Bot rolünü üste taşı."),
                                                 ephemeral=True)
        code = await self.resolve_code(i, davet)
        if code is None:
            return
        self.bot.db.execute("INSERT OR IGNORE INTO invite_roles (guild_id, code, role_id) VALUES (?, ?, ?)",
                            (i.guild_id, code, rol.id))
        await i.response.send_message(embed=ok(
            f"`{code_text(code, i.guild)}` linkiyle gelenlere {rol.mention} verilecek.\n"
            "-# Bu daveti silersen ya da süresi dolarsa rol verilmez. Süresiz ve sınırsız davet kullanman önerilir."))

    @grup.command(name="sil", description="Davet rolünü kaldır (rol boşsa o davetin tüm rolleri kaldırılır)")
    @app_commands.describe(davet="Davet linki ya da kodu. Özel URL için: ozel")
    async def sil(self, i: discord.Interaction, davet: str, rol: discord.Role | None = None):
        t = davet.strip().lower()
        code = VANITY if t in ("ozel", "özel", "vanity", "ozel-url", "özel-url") else parse_code(davet)
        if code and i.guild.vanity_url_code and code.lower() == i.guild.vanity_url_code.lower():
            code = VANITY
        if code is None:
            return await i.response.send_message(embed=err("Davet linki anlaşılamadı."), ephemeral=True)
        if rol:
            cur = self.bot.db.execute("DELETE FROM invite_roles WHERE guild_id=? AND code=? AND role_id=?",
                                      (i.guild_id, code, rol.id))
        else:
            cur = self.bot.db.execute("DELETE FROM invite_roles WHERE guild_id=? AND code=?", (i.guild_id, code))
        if cur.rowcount == 0:
            return await i.response.send_message(embed=err("Bu davete bağlı böyle bir rol yok."), ephemeral=True)
        await i.response.send_message(embed=ok(f"`{code_text(code, i.guild)}` için {cur.rowcount} davet rolü kaldırıldı."))

    @grup.command(name="liste", description="Davet rollerini ve davetlerin kullanım sayısını göster")
    async def liste(self, i: discord.Interaction):
        rows = self.bot.db.all("SELECT code, role_id FROM invite_roles WHERE guild_id=? ORDER BY code", (i.guild_id,))
        if not rows:
            return await i.response.send_message(embed=ok("Henüz davet rolü yok. Eklemek için: `/davetrol ekle`"))
        snap = self.cache.get(i.guild_id, {})
        grouped: dict[str, list[int]] = {}
        for r in rows:
            grouped.setdefault(r["code"], []).append(r["role_id"])
        lines = []
        for code, role_ids in grouped.items():
            if code in snap:
                uses, mx = snap[code]
                durum = f"{uses} kullanım" + (f" / {mx}" if mx else "")
            else:
                durum = "⚠️ davet artık yok"
            lines.append(f"`{code_text(code, i.guild)}` → {' '.join(f'<@&{rid}>' for rid in role_ids)} • {durum}")
        e = discord.Embed(title="📨 Davet rolleri", description="\n".join(lines)[:4000], color=RENK)
        await i.response.send_message(embed=e)


def code_text(code: str, guild: discord.Guild) -> str:
    if code == VANITY:
        return f"discord.gg/{guild.vanity_url_code}" if guild.vanity_url_code else "özel URL"
    return f"discord.gg/{code}"


async def setup(bot):
    await bot.add_cog(Davet(bot))
