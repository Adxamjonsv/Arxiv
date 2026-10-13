from __future__ import annotations

from io import BytesIO

from aiogram.types import BufferedInputFile
from PIL import Image, ImageDraw, ImageFont


def make_onboarding_image(language: str) -> BufferedInputFile:
    """Create a localized setup guide without relying on external image assets."""
    language = "ru" if language == "ru" else "uz"
    if language == "ru":
        title = "Подключение архива"
        subtitle = "Telegram Business · Chat Automation"
        steps = [
            ("1", "Откройте Telegram → Настройки", "Перейдите в раздел Telegram Business."),
            ("2", "Откройте Chat Automation", "Найдите настройки автоматизации чатов."),
            ("3", "Выберите этого бота", "Подключите его и разрешите нужные чаты."),
        ]
        footer = "Архив начнет работать после подключения и команды /resume"
    else:
        title = "Arxivni ulash"
        subtitle = "Telegram Business · Chat Automation"
        steps = [
            ("1", "Telegram → Sozlamalarni oching", "Telegram Business bo‘limiga o‘ting."),
            ("2", "Chat Automation’ni oching", "Chatlarni avtomatlashtirish bo‘limini toping."),
            ("3", "Shu botni tanlang", "Ulang va kerakli chatlarga ruxsat bering."),
        ]
        footer = "Ulangandan so‘ng arxivni /resume bilan yoqing"

    width, height = 1000, 1200
    image = Image.new("RGB", (width, height), "#08111f")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 24, 976, 1176), radius=44, fill="#101c30", outline="#384f79", width=3)
    draw.ellipse((760, -120, 1120, 240), fill="#29205c")

    font_paths = [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf"]
    def font(size: int):
        for path in font_paths:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
        return ImageFont.load_default()

    draw.rounded_rectangle((66, 70, 164, 168), radius=28, fill="#763cff")
    draw.text((94, 83), "◈", font=font(58), fill="#ffffff")
    draw.text((194, 76), title, font=font(47), fill="#f3f6ff")
    draw.text((194, 137), subtitle, font=font(27), fill="#91a9d2")

    top = 230
    for number, heading, detail in steps:
        draw.rounded_rectangle((66, top, 934, top + 245), radius=28,
                               fill="#0b1423", outline="#263a58", width=2)
        draw.ellipse((96, top + 40, 176, top + 120), fill="#246ce8")
        draw.text((122, top + 50), number, font=font(43), fill="#ffffff")
        draw.text((204, top + 45), heading, font=font(32), fill="#f5f7fc")
        draw.text((204, top + 112), detail, font=font(25), fill="#aabbd5")
        if number == "1":
            path_label = "Profil → Business → Chat Automation" if language == "ru" else "Profil → Business → Chat Automation"
            draw.rounded_rectangle((204, top + 164, 865, top + 218), radius=15, fill="#162744")
            draw.text((224, top + 175), path_label, font=font(23), fill="#82b8ff")
        elif number == "2":
            draw.rounded_rectangle((204, top + 164, 865, top + 218), radius=15, fill="#162744")
            hint = "Разрешите доступ только к нужным чатам" if language == "ru" else "Faqat kerakli chatlarga ruxsat bering"
            draw.text((224, top + 175), hint, font=font(22), fill="#82b8ff")
        top += 270

    draw.rounded_rectangle((66, 1060, 934, 1134), radius=22, fill="#1c1740", outline="#7540da", width=2)
    draw.text((94, 1080), footer, font=font(24), fill="#d9c4ff")
    stream = BytesIO()
    image.save(stream, format="PNG", optimize=True)
    return BufferedInputFile(stream.getvalue(), filename=f"archive-connect-{language}.png")
