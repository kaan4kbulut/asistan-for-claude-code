# Asistan for Claude Code

Claude Code oturumlarını arka planda çalıştıran, onları gerçek bir terminalde gösteren ve masaüstünde canlı bir
önizlemesini tutan Linux programı (KDE Plasma 6 widget'ıyla birlikte).

- **Oturumlar arka planda yaşar.** Her sohbet görünmez bir tmux oturumunda çalışır. Programı kapatsan da Claude
  çalışmaya devam eder. Projeler ve sohbetler arasında geçiş yaparken hiçbir oturum kapanmaz.
- **Gerçek terminal.** Yazdığın anında gider, tekerlekle kaydırılır, seçilip kopyalanır (xterm.js). Claude'un
  kopyaladığı yazı panoya düşer.
- **İşlem takibi.** Bu turun ne kadardır sürdüğü ve önceki turlara göre tahmini kalan süresi, çalışan aracın tahmini,
  son 20 işlemin süre grafiği, projenin adımları ve eksikler (onay bekleyen Claude, kaydedilmemiş değişiklik, …).
- **Test sürümleri.** Projelerin son sürümünü ve üzerinde çalışılan önizlemesini (isteğe göre yan yana) terminalin
  yanında açar.
- **Masaüstü widget'ı.** Programın önizlemesi: Claude'un ne yaptığı, son konuşma, işlemler, eksikler, sistem.
  Seçeneği yoktur, tıklayınca programı açar.
- **Konuşarak yazma.** [Dikte](https://github.com/yusufipk/dikte) kuruluysa mikrofon düğmesi görünür.
- **Hafif.** Ölçümler programın içinde ve önbellekli toplanır (~20 ms/sn). Widget hiç süreç başlatmaz, veriyi
  yalnızca değişince alır. İki ekran kartlı dizüstülerde program tümleşik kartta çalışır, ayrı kartı uyandırmaz.

Görünüm Claude Code terminalininki: sıcak koyu zemin, Claude turuncusu, eş aralıklı yazı.

## Kurulum

```bash
git clone https://github.com/kaan4kbulut/asistan-for-claude-code.git ~/Uygulamalar/asistan-for-claude-code
cd ~/Uygulamalar/asistan-for-claude-code
./kur.sh
```

`kur.sh` eksik paketleri (tmux, PySide6 + QtWebEngine) dağıtımın paket yöneticisiyle kurar. Claude Code kurulu
değilse resmî kurulum betiğiyle kurar. Ardından şunları yapar:

- `asistan` komutunu oluşturur (`~/.local/bin`) ve programı uygulama menüsüne ekler;
- oturum açılınca sistem tepsisinde başlatmayı ayarlar (`--otomatik-baslatma-yok` ile kapatılır);
- KDE Plasma 6 varsa masaüstü widget'ını kurar (`--widget-yok` ile kapatılır). Eklemek için masaüstüne sağ tıkla,
  *Widget ekle* de, **Asistan for Claude Code**'ı seç.

Güncellemek için `git pull && ./kur.sh` yeterli.

## Kullanım

| Komut | Ne yapar |
|---|---|
| `asistan` | programı açar (açıksa öne getirir) |
| `asistan --arka-planda` | sistem tepsisinde başlatır |
| `asistan dikte` | konuşarak yazmayı başlatır / bitirir |
| `asistan arka liste` | arka plandaki oturumlar (json) |
| `asistan widget-kur` | masaüstü widget'ını kurar ya da günceller |

Terminalde: **Ctrl+Shift+C** kopyalar, **Ctrl+V** yapıştırır (panoda resim varsa Claude'a gider), **Shift+Enter**
yeni satır açar. Pencereyi kapatınca program tepside, oturumlar arka planda sürer.

## Ayarlar (isteğe bağlı)

Ayar dosyası olmadan da çalışır: ev klasöründe açılan sohbetler *Genel*'de, öteki her klasör kendi adıyla bir proje
olarak listelenir. Projeleri gruplamak ya da adlandırmak için `~/.config/asistan/ayarlar.json`:

```json
{
  "proje_koku": "~/Projeler",
  "yok_say": ["Arşiv"],
  "projeler": [
    {"id": "web", "ad": "Web sitesi", "klasor": "web-sitesi", "klasorler": ["web-sitesi"], "izler": ["web-sitesi/"]}
  ],
  "adlar": {"api-sunucu": "API"}
}
```

Test bölümü için `~/.config/asistan/testler.py` dosyasına bir `projects()` işlevi yaz. Biçimi
`scripts/testler.py`'nin başında anlatılıyor. Dosya yoksa bölüm görünmez.

## Gizlilik

Her şey bilgisayarında kalır. Widget veriyi programdan yalnızca `127.0.0.1` üzerinden alır. Program dışarıya bir
şey göndermez; Claude Code'un kendi bağlantısı dışında ağ kullanmaz.

## Kaldırma

```bash
rm ~/.local/bin/asistan ~/.local/bin/claude-arka ~/.local/share/applications/asistan.desktop ~/.config/autostart/asistan.desktop
kpackagetool6 -t Plasma/Applet -r local.claude.widget
```

## Gerekenler

Linux, Python 3.10+, PySide6 (QtWebEngine, QtQuickWidgets), tmux, Claude Code. Widget için KDE Plasma 6.

## Lisans

MIT. xterm.js ve eklentileri (`scripts/web/vendor`) kendi MIT lisanslarıyla gelir.
