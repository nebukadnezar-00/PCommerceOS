# CommerceOS

Alışveriş uygulaması: kendi e-ticaret sitelerin (logolu kutucuklar) ve ürün fiyat karşılaştırma.
FastAPI + SQLite + vanilla JS, `127.0.0.1:8002`. Tek başına çalışır.

> Bu depo CommerceOS'un herkese açık, sabit bir sürümüdür: güncellenmez, issue ve PR kabul edilmez.
> İndirip kullanabilir, dilediğin gibi değiştirebilirsin (MIT lisansı, `LICENSE`).

**İndir:** GitHub'da **Code › Download ZIP** (ya da `git clone https://github.com/nebukadnezar-00/PCommerceOS.git`),
klasörü aç ve aşağıdaki gibi başlat. Kendi verilerin yalnızca senin bilgisayarında, klasördeki `data/` içinde tutulur.

## Başlatma
- **Windows:** Python 3.13'ü kur (https://www.python.org/downloads/, kurulumda "Add python.exe to PATH" işaretli olsun),
  sonra klasördeki **CommerceOS.bat**'a çift tıkla. İlk açılışta gerekli paketler kurulur (bir kez, birkaç dakika),
  tarayıcı http://localhost:8002 adresinde açılır. Kapatmak için açılan siyah pencereyi kapat.
- **Mac:** **CommerceOS.command**'a çift tıkla (aynı işi yapar). Terminal'den: `python3 launch.py` ya da `./run.sh`.
- Testler: `./test.sh` (ağa çıkmaz). Her push'ta GitHub'da Windows ve macOS üzerinde de çalışır (`.github/workflows/test.yml`).
- Anahtarlar ve şifreler Mac'te Anahtar Zinciri'nde, Windows'ta Kimlik Bilgisi Yöneticisi'nde durur; dosyaya yazılmaz.

## Yerleşim
- **Geniş ekran (≥ 1000 px):** solda arama (altında son aramalar), Sitelerim logo rafı ve sonuçlar; sağda kaydırırken sabit
  duran panelde Sepet (Bölerek al özeti) ve Fiyat takibi. Header'daki 🛒 hapı ürün sayısını ve sepet toplamını gösterir.
- **Sonuçlar:** en ucuz üç teklif büyük kart (en ucuzu yeşil), kalanlar altta kompakt liste; filtreler ikisine de uygulanır.
- **Site yönetimi ve tüm geçmiş** sağdan açılan çekmecede: raftaki "Düzenle" / aramadaki "Geçmiş →".
- **Telefon ve dikey tablet (< 1000 px):** altta Ara · Takip · Sepet · Siteler sekmeleri (rozetler: düşen fiyat, ürün sayısı);
  seçili sekme cihazda hatırlanır.

## Sitelerim (token harcamaz)
- İlk açılışta Trendyol, Hepsiburada, Amazon TR, n11, MediaMarkt, Teknosa eklenir; hepsi silinebilir.
- **Site ekle**: adres yazılır; isim, logo ve sitenin arama sayfası otomatik bulunur. Site botları
  engelliyorsa (Trendyol, Hepsiburada) bilinen değerler ve Google'ın favicon servisi kullanılır.
  Arama sayfası bulunamayan sitede "Sitelerde ara" Google `site:` aramasını açar.
- Logolar `data/logos/` içinde saklanır; tarayıcı yalnızca CommerceOS'tan ister.
- **Sıralama**: kutucuğu sürükle-bırak. Fareyle doğrudan; dokunmatikte basılı tut, sonra sürükle
  (Düzenle açıkken basılı tutmadan sürüklenir; klavyede ok tuşları). Sıra kaydedilir, "Sitelerde ara" da bu sırayı izler.
- **Düzenle**: ad değiştir, logoyu yenile, kaldır.
- **Gruplar**: **+ Grup** ile Elektronik, Market, Seyahat gibi gruplar açılır. Siteler sürükle-bırakla gruplar arasında
  taşınır: bir kutucuğun arasına ya da grubun başlığına bırakılır (kapalı gruba da). Grup başlığına dokununca grup
  açılır/kapanır (bu durum sunucuda saklanır). Üstteki çiplerle tek grup gösterilir. Grupsuz siteler **Diğer**'de durur;
  grup silinince siteleri Diğer'e geçer. Site eklerken grup seçilebilir.

## Ürün ara
- Kapsam her aramada seçilir: **Sitelerim** (yalnızca eklediğin sitelerin teklifleri) / **Tüm internet**. Grup varsa
  "Sitelerim" yanında grup seçilir (ör. yalnızca Elektronik); hızlı sonuç, derin arama ve sepet bu gruba göre daralır.
  Fiyat takibi grup yerine "Sitelerim" olarak kaydedilir.
- **Hızlı arama** (varsayılan, token yok): Akakçe'nin arama ve ürün sayfaları okunur, satıcı teklifleri
  fiyata göre sıralanır. Genel aramada bulunan ürünler üstte listelenir, birine dokununca o ürünün
  teklifleri gelir. Akakçe, Python'un isteklerini Cloudflare ile engellediği için istekler macOS'un
  `/usr/bin/curl`'ü ile yapılır.
- **Yedek kaynak** (token yok): Akakçe'ye ulaşılamazsa ya da ürün orada yoksa hızlı arama Amazon TR'nin kendi
  aramasını okur (tek mağaza; "uyumlu", "kılıf" gibi aksesuar ilanları ayıklanır, fiyata göre sıralanır). Cimri, Epey
  ve çoğu mağaza otomatik istekleri engellediği için yedek olarak Amazon TR seçildi.
- **Derin ara** (⚙ Ayarlar'da seçilen yapay zekâ + web araması — Gemini, Claude, OpenAI…; ana sağlayıcı hata verirse yedek; token harcar — bir aramada ~1-5 bin): Akakçe'de olmayan ürünler
  ya da ikinci görüş için. Yapay zekânın verdiği bağlantılar kontrol edilir; açılmayan bağlantı mağazanın
  arama sayfasıyla değiştirilir. Fiyatlar Akakçe kadar güvenilir değildir, satın almadan önce sayfada
  doğrula. Bu ayın toplam token'ı sağlık göstergesinin ayrıntı kutusunda görünür.
- **Arama geçmişi**: her arama saklanır, geçmişten açmak token harcamaz. Aynı arama hızlıda 1 saat,
  derinde 6 saat içinde tekrarlanırsa kayıttan gelir (`Yenile` ile zorla).

## Fiyat takibi ve alarm (token harcamaz)
- Hızlı aramada bir ürün açıp **🔔 Takibe al**: isteğe bağlı hedef fiyat ve kapsam (Sitelerim / Tüm internet).
- Fiyat her gün `TRACK_SCHEDULE` saatlerinde (varsayılan 09:00 ve 18:00) Akakçe'den kontrol edilir; Mac uykudaysa
  uyanınca kaçırılan kontrol yapılır. **Şimdi kontrol et** ile elle.
- Alarm: hedef fiyat varsa fiyat hedefin altına **ilk indiğinde**; yoksa önceki kontrole göre en az `DROP_MIN_PCT`
  (%1) düşünce. Alarmlar header'daki 🔔'de görünür.
- Her kontrol fiyat geçmişine eklenir; kartta küçük grafik (kesikli çizgi = hedef), en düşük fiyat ve eklenenden beri değişim.

## Alışveriş listesi — "Bölerek al" (token harcamaz)
- Hızlı aramada ürün açıp **🛒 Listeye ekle** (takip kartlarında 🛒); aynı ürün tekrar eklenirse adet artar, −/+ ile değişir.
- **Bölerek al** sonucu ürün eklenir eklenmez görünür: her ürünün teklifleri eklendiği aramadan alınır (gerekirse ekleme
  anında bir kez okunur) ve saklanır. Seçili kapsamda en ucuz teklif seçilir, mağaza mağaza siparişlere ayrılır: toplam,
  kaç ayrı sipariş, her siparişte hangi ürünler. Adet ya da kapsam değişince istek atmadan yeniden hesaplanır.
- **Fiyatları güncelle**: listedeki her ürünün Akakçe sayfasını yeniden okur (ürün başına bir sayfa, aralarında kısa
  bekleme); başlıkta fiyatların ne zaman okunduğu yazar.
- **Tek siparişte**: siparişler birden fazla mağazaya bölünüyorsa, listenin tamamını satan mağazalar en ucuzdan
  (en fazla 3) ve bölerek almaya göre farkı (+… TL) gösterilir; hiçbir mağazada hepsi yoksa en çoğunu satan mağaza ve eksikler.
- Akakçe kargo ücretini vermez, yalnızca ücretsiz olup olmadığını söyler: ücretli kargolu sipariş **+ kargo** diye
  işaretlenir ve toplam "kargo hariç" yazar. Fiyatı okunamayan ürün ayrıca listelenir; diğerleri hesaplanır.

## Teklif filtreleri
Hızlı arama sonuçlarında: **Stokta**, **Ücretsiz kargo**, **Hızlı kargo** (bugün/yarın), **Puanı düşükleri gizle**
(Akakçe mağaza puanı 7'nin altı; puanı olmayanlar kalır). Seçim bu cihazda hatırlanır. Mağaza puanı satırda ★ ile görünür.

## Sağlık göstergesi (header)
FinanceOS'taki kalp atışı çizgisi: yeşil **Sağlıklı**, turuncu **uyarı var** (Akakçe'ye ulaşılamıyor ya da yapay zekâ
anahtarı yok), mavi **aranıyor**, kırmızı düz çizgi **bağlantı yok**. Akakçe her 5 dakikada bir token'sız kontrol edilir
(hata varken her dakika). Ayrıca 6 saatte bir bilinen bir arama ve ürün sayfası okunarak **sayfa yapısı** kontrol edilir;
gerçek aramalar ve fiyat kontrolleri de sonucu bildirir. Akakçe sayfa yapısını değiştirip fiyatlar okunamaz hale gelirse
gösterge turuncuya döner ve "sayfa yapısı değişmiş olabilir" uyarısı çıkar. Ayrıntılar ve **bu ayın yapay zekâ token'ı** göstergenin üstüne gelince (tablette dokununca)
açılan kutuda görünür; header'da ayrıca token yazısı yoktur.

## Rehber
- Beş adımlık animasyonlu rehber: **Sitelerin · Yapay zekâ anahtarı · İlk arama · Takip ve sepet · Siparişlerin**.
  Yeni kurulumda açılış ekranından sonra bir kez kendiliğinden açılır (daha önce arama yapılmışsa açılmaz).
- Header'ın sağında, ayarların solundaki **🤖 Yardıma mı ihtiyacın var?** düğmesi rehberi her zaman ilk adımdan açar
  (telefonda yalnızca robot). İlerleme çubuğunun parçalarına tıklayarak (ya da ← →) adımlar arasında geçilir.
  Yapılmış adımlar "✓ Tamam" gösterir (`/api/guide`). Düğme hep yerinde kalır; yalnızca rehber penceresi kapatılır.
- **Göster**: pencere kapanır, ilgili yer çerçeveyle vurgulanır ve kısa bir ipucu çıkar. İpucundaki **Tamam** (ya da Esc)
  ve Ayarlar penceresinin kapanması rehberi aynı adımda yeniden açar.

## Giriş ekranı
FinanceOS'taki açılış ekranı, CommerceOS mavisiyle: her satır gerçek bir yükleme adımına bağlı (sunucu, sitelerim,
fiyat takibi, geçmiş, Akakçe, yapay zekâ). Sekme başına bir kez çıkar (yenilemede atlanır); tıklama ya da Esc
ile geçilir. Kod: `frontend/boot.js` (FinanceOS `js/boot.js`'nin modülsüz hali).

## Sürüm ve yedek
- `.env` ve `data/` git'e girmez (`.gitignore`). Kendi kopyanda geliştirirken `git config core.hooksPath .githooks`
  ile `.githooks/pre-commit` anahtara benzeyen değerleri commit'ten önce durdurur.
- Veritabanı: her gün 08:50'de `data/backups/` (son 14 gün).
- Bulut kopyası isteğe bağlıdır: ⚙ Ayarlar › **Yedek**'te **Bulut kopyasını aç** ile bir yedek şifresi belirlenince her gün
  **CommerceOS Yedek** klasörüne AES-256 şifreli kopya gider: Mac'te iCloud Drive, Windows'ta OneDrive (ya da oradan
  seçilen klasör). `CommerceOS Yedek` şifresi yoksa FinanceOS'un yedek şifresi (`FinanceOS Yedek`) kullanılır. Şifre
  yokken buluta bir şey gitmez ve uyarı da çıkmaz; header yalnızca açılmış bulut kopyası başarısız olursa uyarır.
  Şifreli dosyalar iki işletim sisteminde de açılır.
- Açmak için (şifreyi sorar): `.venv/bin/python -m backend.backup <dosya>.db.enc commerce.db`
  (Windows: `.venv\Scripts\python -m backend.backup ...`). Mac'te openssl de olur:
  `openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -in <dosya>.enc -out commerce.db`

## Notlar
- Eski yöntem: Gemini anahtarı `CommerceOS/.env` boşsa `FinanceOS/.env`'den okunur.
- Dışarıya giden her istekte adres kontrol edilir: yalnızca genel internet adresleri (yerel ağ, Mac'in
  kendisi ve router'a istek atılmaz), her yönlendirme yeniden kontrol edilir.
- Tema: koyu / açık, `frontend/theme.js` (seçim tarayıcı çerezinde saklanır).
- Akakçe sayfa yapısını değiştirirse hızlı arama "okunamadı, Derin ara?" der; ayrıştırıcı `backend/akakce.py`,
  örnek sayfalar `tests/fixtures/`.

## Yapay zekâ anahtarı (⚙ Ayarlar)

Sağ üstteki ⚙ **Ayarlar**'dan ana ve yedek yapay zekâ sağlayıcısı seçilir, anahtar girilip **Test et** (token harcamaz) ile denenir. Anahtarlar Mac'te Anahtar Zinciri'nde, Windows'ta Kimlik Bilgisi Yöneticisi'nde durur. Seçim `data/ai.json` dosyasındadır; üst klasörde `os-suite-ai.json` varsa (diğer OS Suite uygulamalarıyla aynı klasörde) o dosya ve anahtarlar onlarla ortak kullanılır. `backend/providers.py` ve `frontend/aisettings.js` FinanceOS'takilerle aynı dosyalardır (orada değiştirilip buraya kopyalanır).

## Lisans
MIT — ayrıntılar `LICENSE` dosyasında.
