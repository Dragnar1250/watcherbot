"""Karşılama resmi ve seviye kartı üretimi (Pillow)."""
import io
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Windows fontları önce denenir, yoksa Linux fontları, en son Pillow'un kendi fontu.
_BOLD = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
_REGULAR = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size: int, bold: bool = False):
    for path in _BOLD if bold else _REGULAR:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _gradient(w: int, h: int, c1=(35, 39, 92), c2=(88, 101, 242)) -> Image.Image:
    img = Image.new("RGB", (w, h), c1)
    draw = ImageDraw.Draw(img)
    for x in range(w):
        t = x / max(w - 1, 1)
        color = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
        draw.line([(x, 0), (x, h)], fill=color)
    return img


def _circle_avatar(avatar_bytes: bytes, size: int) -> Image.Image:
    av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4, size * 4), fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    av.putalpha(mask)
    return av


def _fit_text(draw, text, max_w, start_size, bold=True):
    size = start_size
    while size > 14:
        f = _font(size, bold)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return _font(14, bold)


def _cover(bg: Image.Image, w: int, h: int) -> Image.Image:
    ratio = max(w / bg.width, h / bg.height)
    bg = bg.resize((int(bg.width * ratio) + 1, int(bg.height * ratio) + 1), Image.LANCZOS)
    left = (bg.width - w) // 2
    top = (bg.height - h) // 2
    return bg.crop((left, top, left + w, top + h))


def welcome_card(avatar_bytes: bytes, name: str, guild_name: str, member_count: int,
                 background_path: str | None = None, title: str = "HOŞ GELDİN") -> io.BytesIO:
    W, H = 1024, 450
    if background_path and os.path.exists(background_path):
        bg = _cover(Image.open(background_path).convert("RGB"), W, H)
    else:
        bg = _gradient(W, H)
    # Okunabilirlik için hafif karartma
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 90))
    img = Image.alpha_composite(bg.convert("RGBA"), overlay)

    av_size = 200
    av = _circle_avatar(avatar_bytes, av_size)
    ring = Image.new("RGBA", (av_size + 16, av_size + 16), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, av_size + 15, av_size + 15), fill=(255, 255, 255, 255))
    ax, ay = (W - av_size) // 2, 40
    img.alpha_composite(ring, (ax - 8, ay - 8))
    img.alpha_composite(av, (ax, ay))

    d = ImageDraw.Draw(img)
    f_title = _font(52, True)
    d.text((W / 2, 290), title, font=f_title, fill="white", anchor="mm")
    f_name = _fit_text(d, name, W - 80, 40)
    d.text((W / 2, 345), name, font=f_name, fill=(230, 230, 255), anchor="mm")
    f_small = _font(26)
    d.text((W / 2, 395), f"{guild_name} • {member_count}. üye", font=f_small, fill=(200, 200, 220), anchor="mm")

    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG")
    out.seek(0)
    return out


def rank_card(avatar_bytes: bytes, name: str, rows: list[tuple], accent=(88, 101, 242)) -> io.BytesIO:
    """rows: [(etiket, seviye, xp, gereken, sira), ...]  örn. [("YAZI", 5, 120, 475, 3), ("SES", 2, 40, 220, 8)]"""
    W = 934
    row_h = 105
    H = 110 + row_h * len(rows)
    img = Image.new("RGBA", (W, H), (35, 39, 42, 255))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, W - 12, H - 12), radius=24, fill=(24, 25, 28, 255))

    av_size = 190
    img.alpha_composite(_circle_avatar(avatar_bytes, av_size), (45, (H - av_size) // 2))

    x0, right = 270, W - 50
    d.text((x0, 80), name, font=_fit_text(d, name, right - x0, 40), fill="white", anchor="ls")

    f_lbl, f_num, f_small = _font(22), _font(34, True), _font(22)
    for n, (label, level, xp, needed, rank) in enumerate(rows):
        top = 110 + n * row_h
        # Sol: tür etiketi, sağ: sıra + seviye
        d.text((x0, top + 30), label, font=_font(24, True), fill=accent, anchor="ls")
        lvl = str(level)
        d.text((right, top + 32), lvl, font=f_num, fill=accent, anchor="rs")
        lx = right - d.textlength(lvl, font=f_num) - 8
        d.text((lx, top + 32), "SEVİYE", font=f_lbl, fill=accent, anchor="rs")
        rx = lx - d.textlength("SEVİYE", font=f_lbl) - 22
        rk = f"#{rank}"
        d.text((rx, top + 32), rk, font=f_num, fill="white", anchor="rs")
        d.text((rx - d.textlength(rk, font=f_num) - 8, top + 32), "SIRA", font=f_lbl, fill="white", anchor="rs")
        # Çubuk
        by0, by1 = top + 48, top + 80
        d.rounded_rectangle((x0, by0, right, by1), radius=16, fill=(72, 75, 78))
        ratio = max(0.0, min(1.0, xp / needed if needed else 0))
        fill_w = int((right - x0) * ratio)
        if fill_w >= 32:
            d.rounded_rectangle((x0, by0, x0 + fill_w, by1), radius=16, fill=accent)
        elif fill_w > 0:
            d.ellipse((x0, by0, x0 + 32, by1), fill=accent)
        xp_txt = f"{xp:,} / {needed:,} XP".replace(",", ".")
        d.text((right - 12, (by0 + by1) // 2), xp_txt, font=f_small, fill="white", anchor="rm")

    out = io.BytesIO()
    img.save(out, "PNG")
    out.seek(0)
    return out


def profile_card(avatar_bytes: bytes, name: str, credits: int, rep: int, level: int, bio: str | None) -> io.BytesIO:
    W, H = 800, 400
    img = _gradient(W, H, (24, 25, 28), (55, 60, 140)).convert("RGBA")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((20, 160, W - 20, H - 20), radius=20, fill=(24, 25, 28, 235))
    av = _circle_avatar(avatar_bytes, 150)
    ring = Image.new("RGBA", (162, 162), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, 161, 161), fill=(255, 255, 255, 255))
    img.alpha_composite(ring, (44, 64))
    img.alpha_composite(av, (50, 70))

    f_name = _fit_text(d, name, 520, 38)
    d.text((220, 140), name, font=f_name, fill="white", anchor="ls")

    f_lbl, f_val = _font(22), _font(34, True)
    cols = [("KREDİ", f"{credits:,}".replace(",", ".")), ("İTİBAR", str(rep)), ("SEVİYE", str(level))]
    for i, (lbl, val) in enumerate(cols):
        cx = 300 + i * 165
        d.text((cx, 205), lbl, font=f_lbl, fill=(185, 187, 190), anchor="mm")
        d.text((cx, 245), val, font=f_val, fill="white", anchor="mm")

    bio = (bio or "Henüz bir hakkımda yazısı yok. /hakkimda ile ekleyebilirsin.")[:120]
    f_bio = _font(22)
    # basit satır kaydırma
    words, lines, line = bio.split(), [], ""
    for w in words:
        test = (line + " " + w).strip()
        if d.textlength(test, font=f_bio) > W - 100:
            lines.append(line)
            line = w
        else:
            line = test
    lines.append(line)
    for i, ln in enumerate(lines[:3]):
        d.text((50, 300 + i * 28), ln, font=f_bio, fill=(220, 221, 222))

    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG")
    out.seek(0)
    return out


def levelup_card(avatar_bytes: bytes, name: str, old_level: int, new_level: int,
                 background_path: str | None = None, accent=(88, 101, 242),
                 title: str = "SEVİYE ATLADI!", xp: int | None = None, needed: int | None = None) -> io.BytesIO:
    """Seviye atlama kartı (Arcane tarzı). xp/needed verilirse altta ilerleme çubuğu çizilir."""
    W = 900
    H = 310 if needed else 260
    if background_path and os.path.exists(background_path):
        bg = _cover(Image.open(background_path).convert("RGB"), W, H)
    else:
        bg = _gradient(W, H, (24, 25, 28), (55, 60, 140))
    img = Image.alpha_composite(bg.convert("RGBA"), Image.new("RGBA", (W, H), (0, 0, 0, 110)))
    d = ImageDraw.Draw(img)

    av_size = 170
    ring = Image.new("RGBA", (av_size + 12, av_size + 12), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, av_size + 11, av_size + 11), fill=accent + (255,))
    ay = (H - av_size) // 2
    img.alpha_composite(ring, (40 - 6, ay - 6))
    img.alpha_composite(_circle_avatar(avatar_bytes, av_size), (40, ay))

    x0 = 250
    d.text((x0, 70), title, font=_font(30, True), fill=accent, anchor="ls")
    f_name = _fit_text(d, name, W - x0 - 40, 44)
    d.text((x0, 125), name, font=f_name, fill="white", anchor="ls")

    f_big = _font(64, True)
    old_t, new_t = str(old_level), str(new_level)
    d.text((x0, 215), old_t, font=f_big, fill=(185, 187, 190), anchor="ls")
    ax = x0 + d.textlength(old_t, font=f_big) + 25
    # ok işareti
    d.polygon([(ax, 180), (ax + 40, 180), (ax + 40, 168), (ax + 65, 193), (ax + 40, 218), (ax + 40, 206), (ax, 206)],
              fill="white")
    d.text((ax + 90, 215), new_t, font=f_big, fill="white", anchor="ls")

    if needed:
        bx0, by0, bx1, by1 = x0, 245, W - 40, 280
        d.rounded_rectangle((bx0, by0, bx1, by1), radius=17, fill=(72, 75, 78))
        ratio = max(0.0, min(1.0, (xp or 0) / needed))
        fw = int((bx1 - bx0) * ratio)
        if fw >= 34:
            d.rounded_rectangle((bx0, by0, bx0 + fw, by1), radius=17, fill=accent)
        elif fw > 0:
            d.ellipse((bx0, by0, bx0 + 34, by1), fill=accent)
        txt = f"{xp or 0:,} / {needed:,} XP".replace(",", ".")
        d.text((bx1 - 14, (by0 + by1) // 2), txt, font=_font(22, True), fill="white", anchor="rm")

    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG")
    out.seek(0)
    return out
