# Railway'da ishga tushirish

1. Railway'da GitHub'dagi `Adxamjonsv/Arxiv` repozitoriysini ulang.
2. **Variables** bo'limiga quyidagi o'zgaruvchilarni kiriting:
   - `BOT_TOKEN` — BotFather bergan to'liq bot tokeni. O'zgaruvchi nomi aynan `BOT_TOKEN`, token esa uning qiymati bo'ladi.
   - `ADMIN_IDS` — admin Telegram ID raqamlari, masalan `123456789`. Bir nechta bo'lsa vergul bilan: `123456789,987654321`.
   - `DATABASE_PATH` — `/data/archive.db`
   - `STORAGE_DIR` — `/data/storage`
   - `MINI_APP_URL` — Railway'da yaratilgan domenning HTTPS manzili, masalan `https://your-service.up.railway.app`
3. **Settings → Networking** bo'limidan public domain yarating.
4. **Volumes** bo'limidan persistent volume qo'shib, mount path sifatida `/data` kiriting. Bu SQLite ma'lumotlar bazasi va arxivlangan fayllarni qayta deploydan keyin ham saqlaydi.
5. Railway build uchun `requirements.txt` faylini o'zi aniqlaydi; ishga tushirish buyrug'i `Procfile` ichida `python main.py` deb berilgan.
6. Deploy tugagach, Telegram'da botga `/start`, keyin admin sifatida `/admin` yuboring.

## "secret ... not found" build xatosi

Bu xabar repozitoriydagi Python kodidan kelmaydi. Railway **Variables** yoki deploy/build sozlamalarida o'sha nomdagi secret reference topilmayapti. Variables ichida `BOT_TOKEN` nomli variable yarating va BotFather tokenini uning **qiymati** maydoniga kiriting. Tokenni variable nomi sifatida yozmang. Keyin qayta deploy qiling.

Bot tokeni chat yoki ommaviy skrinshotda ko'ringan bo'lsa, BotFather orqali uni yangilang va Railway'dagi `BOT_TOKEN` qiymatini ham almashtiring.
