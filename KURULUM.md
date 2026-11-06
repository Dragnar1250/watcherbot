# TürkBot Kurulumu (Windows)

Kurulum yaklaşık 15 dakika sürer ve sadece bir kez yapılır.

---

## 1. Python'u kur

1. https://www.python.org/downloads/ adresine git ve **Download Python 3.12** (ya da daha yeni) butonuna bas.
2. Kurulumun **ilk ekranında en alttaki "Add python.exe to PATH" kutusunu işaretle.** Bunu atlarsan bot çalışmaz.
3. **Install Now** butonuna bas ve kurulumun bitmesini bekle.

---

## 2. Discord'da bot hesabını oluştur

1. https://discord.com/developers/applications adresine git ve Discord hesabınla giriş yap.
2. Sağ üstten **New Application**'a tıkla, bir isim yaz (örneğin *TürkBot*) ve onayla.
3. Soldaki menüden **Bot** sekmesine gir.
   - İstersen burada botun resmini ve adını değiştirebilirsin.
   - **Reset Token** butonuna bas, çıkan uzun yazıyı **kopyala** ve bir yere not et. Bu botun şifresidir, **kimseyle paylaşma.**
   - Aşağı in, **Privileged Gateway Intents** bölümünde şu ikisini **aç**:
     - ✅ **Server Members Intent**
     - ✅ **Message Content Intent**
   - **Save Changes** butonuna bas.

## 3. Botu sunucuna davet et

1. Soldaki menüden **OAuth2** sekmesine gir ve **URL Generator** bölümünü bul.
2. **Scopes** listesinde **bot** ve **applications.commands** kutularını işaretle.
3. Aşağıda açılan **Bot Permissions** listesinde **Administrator** kutusunu işaretle.
4. En alttaki linki kopyala, tarayıcıda aç, sunucunu seç ve **Yetkilendir**'e bas.

---

## 4. Botu çalıştır

1. İndirdiğin `TurkBot.zip` dosyasına sağ tıklayıp **Tümünü ayıkla**'yı seç. Masaüstü ya da Belgeler gibi bir yere çıkar.
2. Klasörün içindeki **`baslat.bat`** dosyasına çift tıkla.
   - İlk açılışta gerekli dosyalar indirilir. Bu 1-2 dakika sürebilir.
   - Ardından **Not Defteri** açılır. `DISCORD_TOKEN=BURAYA_TOKEN` satırında `BURAYA_TOKEN` yazısını silip yerine 2. adımda kopyaladığın token'ı yapıştır, sonra **kaydet** ve kapat.
3. **`baslat.bat`** dosyasına tekrar çift tıkla. Pencerede şu satırı görüyorsan bot çalışıyor demektir:
   `Giriş yapıldı: TürkBot#1234`

> Pencereyi kapatırsan bot da kapanır. Bot bir hata yüzünden durursa 5 saniye sonra kendini yeniden başlatır.

> **Komutlar görünmüyorsa:** Discord'un yeni komutları göstermesi bazen birkaç dakika sürüyor. Hemen görünmelerini istersen `.env` dosyasındaki `TEST_SUNUCU_ID=` satırının yanına sunucunun ID'sini yaz ve botu yeniden başlat. ID'yi almak için önce Discord Ayarları → Gelişmiş → **Geliştirici Modu**'nu aç, sonra sunucu adına sağ tıklayıp **Sunucu ID'sini Kopyala**'yı seç.

---

## 5. Sunucuda iki önemli ayar

1. **Bot rolünü yukarı taşı:** Sunucu Ayarları → Roller listesinde botun rolünü, vermesini istediğin rollerin ve yöneteceği üyelerin rollerinin **üstüne** sürükle. Bot sadece kendi rolünün altındaki rolleri verebilir ve sadece o rollerdeki üyeleri yönetebilir.
2. **ProBot'u çıkar ya da özelliklerini kapat.** Aksi halde karşılama gibi mesajlar iki kez gönderilir.

---

## 6. Hızlı kurulum (ProBot'taki ayarların karşılıkları)

Tüm komutları görmek için Discord'da `/yardim` yaz.

| Ne istiyorsun | Komut |
|---|---|
| Karşılama mesajı | `/karsilama kanal` → `/karsilama mesaj` → `/karsilama test` |
| Karşılama resmine kendi arka planın | `/karsilama arkaplan` (resim yükle, 1024x450 ideal) |
| Veda mesajı | `/veda kanal` |
| Gelene otomatik rol | `/otorol uye` |
| Loglar | `/log kanal` |
| Reklam/küfür/spam engeli | `/otomod filtre`, `/otomod kelime-ekle`, `/otomod ceza` |
| Seviye sistemi | Varsayılan olarak açık. Ödül rolü için `/seviye rol-ekle` |
| Tepki rolü | `/tepkirol ekle` |
| Otomatik cevap | `/otoyanit ekle` |
| Yıldız panosu | `/yildiz kanal` |
| Özel ses kanalı | `/ozelses kur` |

Mesajlarda şu değişkenleri kullanabilirsin: `{kullanici}` (etiket), `{isim}`, `{sunucu}`, `{uye_sayisi}`, `{seviye}` (sadece seviye mesajında). Mesajın içinde alt satıra geçmek için `\n` yaz.

---

## Sık karşılaşılan sorunlar

| Sorun | Çözüm |
|---|---|
| `'py' is not recognized` / `'python' is not recognized` | Python kurulurken "Add to PATH" kutusu işaretlenmemiş. Python'u yeniden kur ve kutuyu işaretle. |
| `Token geçersiz` | Geliştirici portalında **Reset Token** ile yeni bir token al ve `.env` dosyasına yapıştır. |
| `Intent açık değil` | 2. adımdaki iki intent'i aç ve kaydet. |
| Bot rol veremiyor veya üye yasaklayamıyor | Bot rolünü rol listesinde yukarı taşı (5. adım). |
| Başka bir hata | Klasördeki `bot.log` dosyasının son satırlarını bana gönder. |

## Veriler nerede?

Tüm ayarlar, seviyeler ve krediler `data/bot.db` dosyasında tutulur. Botu başka bir bilgisayara ya da sunucuya taşırken **`data` klasörünü ve `.env` dosyasını** da kopyala.

## 7/24 açık kalması için

Bot, bilgisayarın açık olduğu sürece çalışır. Sürekli açık kalmasını istersen kodu ayda birkaç dolarlık bir sunucuya (VPS) taşıyabiliriz. Kodda bir değişiklik gerekmez.

---

## Otomatik güncelleme (GitHub)

Bu ayar yapıldığında, kodda yapılan değişiklikleri bot kendisi indirip kurar. Eski bilgisayara gidip dosya kopyalamana gerek kalmaz.

**Nasıl çalışır:**
- Bot her açılışta ve açıkken **10 dakikada bir** GitHub'daki depoya bakar.
- Yeni sürüm varsa indirir, kodda hata olup olmadığını kontrol eder, yedek alır ve kurar. Sonra kendini yeniden başlatır. Log kanalına "Bot güncelleniyor" mesajı düşer.
- **Hiçbir zaman dokunmadığı dosyalar:** `.env` (token), `data` klasörü (seviyeler, ayarlar, cezalılar), `.venv`, `bot.log`, `baslat.bat`.
- Yeni sürümün kodu bozuksa kurulmaz. Kurulduktan sonra bot açılamazsa ya da bir modül yüklenemezse otomatik olarak **eski sürüme geri döner** ve o bozuk sürümü bir daha denemez.
- İnternet yoksa ya da GitHub'a ulaşılamazsa bot normal şekilde açılır, güncellemeyi sonra yeniden dener.

**Açmak için (dosya düzenlemeden):** Discord'da bir kez şunu yaz:
```
/guncelle depo:kullaniciadi/depoadi
```
Bu kadar. Ayar `data` klasörüne kaydedilir, bot yeniden açılsa da kalır.

**İstersen .env'den de ayarlayabilirsin** (.env'deki ayar önceliklidir):
```
GUNCELLEME_DEPO=kullaniciadi/depoadi
GUNCELLEME_DALI=main
GITHUB_TOKEN=            ← sadece depo gizliyse
OTOMATIK_GUNCELLEME=1    ← 0 yaparsan sadece /guncelle ile güncellenir
```

**Komutlar:**
- `/surum`: Kurulu sürümü ve güncelleme ayarlarını gösterir.
- `/guncelle`: GitHub'da yeni sürüm var mı hemen kontrol eder, varsa kurar. Sadece botun sahibi kullanabilir.

**Not:** `baslat.bat` bot çalışırken değiştirilemediği için güncellenmez. İleride yeni bir sürümü gelirse klasörde `baslat.bat.yeni` olarak durur. Botu kapatıp elle değiştirmen yeterli.
