#!/usr/bin/env bash
# Asistan for Claude Code'u kurar ya da günceller (bu klasörden çalışır, dosyaları kopyalamaz):
#   - eksik gerekenleri paket yöneticisiyle kurar: tmux, PySide6 (QtWebEngine ile)
#   - başlatıcı: ~/.local/bin/asistan (ve eski adıyla claude-arka)
#   - uygulama menüsü kaydı ve oturum açılışında sistem tepsisinde başlatma
#   - masaüstü widget'ı (yalnızca KDE Plasma 6'da)
# Claude Code (claude) kurulu değilse resmî kurulum betiğiyle kurar. Konuşarak yazma için Dikte isteğe bağlıdır.
# Seçenekler: --widget-yok (widget'ı kurma), --otomatik-baslatma-yok
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
DIR="$PWD"
WIDGET=1
AUTOSTART=1
for a in "$@"; do
    case "$a" in
        --widget-yok) WIDGET=0 ;;
        --otomatik-baslatma-yok) AUTOSTART=0 ;;
    esac
done

ok() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
say() { printf '  %s\n' "$1"; }

echo
echo "Asistan for Claude Code kuruluyor"
echo "───────────────────────────────────"

need_py=0
python3 -c 'import PySide6.QtWebEngineWidgets, PySide6.QtQuickWidgets, PySide6.QtWebChannel' 2>/dev/null || need_py=1
need_tmux=0
command -v tmux >/dev/null || need_tmux=1
if ((need_py || need_tmux)); then
    say "Eksikler kuruluyor (yönetici parolası istenebilir)…"
    if command -v pacman >/dev/null; then
        pkgs=()
        ((need_tmux)) && pkgs+=(tmux)
        ((need_py)) && pkgs+=(pyside6 qt6-webengine)
        sudo pacman -S --needed --noconfirm "${pkgs[@]}"
    elif command -v apt-get >/dev/null; then
        pkgs=()
        ((need_tmux)) && pkgs+=(tmux)
        ((need_py)) && pkgs+=(python3-pyside6.qtwebenginewidgets python3-pyside6.qtquickwidgets python3-pyside6.qtwebchannel)
        sudo apt-get install -y "${pkgs[@]}"
    elif command -v dnf >/dev/null; then
        pkgs=()
        ((need_tmux)) && pkgs+=(tmux)
        ((need_py)) && pkgs+=(python3-pyside6)
        sudo dnf install -y "${pkgs[@]}"
    elif command -v zypper >/dev/null; then
        pkgs=()
        ((need_tmux)) && pkgs+=(tmux)
        ((need_py)) && pkgs+=(python3-pyside6)
        sudo zypper install -y "${pkgs[@]}"
    else
        ((need_tmux)) && { echo "tmux kurulamadı: paket yöneticisi tanınmadı"; exit 1; }
        python3 -m pip install --user PySide6
    fi
fi
ok "tmux ve PySide6 hazır"

if ! command -v claude >/dev/null && [[ ! -x "$HOME/.local/bin/claude" ]]; then
    say "Claude Code kuruluyor (resmî kurulum betiği)…"
    curl -fsSL https://claude.ai/install.sh | bash
fi
ok "Claude Code hazır"

mkdir -p "$HOME/.local/bin"
ln -sf "$DIR/bin/asistan" "$HOME/.local/bin/asistan"
ln -sf "$DIR/bin/claude-arka" "$HOME/.local/bin/claude-arka"
ok "başlatıcı: ~/.local/bin/asistan"

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
cat > "$APPS/asistan.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Asistan for Claude Code
Comment=Claude Code oturumlarını arka planda çalıştırır; gerçek terminal, projeler, testler, işlem tahminleri
Exec=$HOME/.local/bin/asistan
Icon=utilities-terminal
Terminal=false
Categories=Development;Utility;
StartupWMClass=asistan
EOF
ok "uygulama menüsüne eklendi"

AUTO="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
if ((AUTOSTART)); then
    mkdir -p "$AUTO"
    sed -e "s|^Exec=.*|Exec=$HOME/.local/bin/asistan --arka-planda|" -e "s|^Name=.*|Name=Asistan for Claude Code (arka planda)|" \
        "$APPS/asistan.desktop" > "$AUTO/asistan.desktop"
    ok "oturum açılınca sistem tepsisinde başlar"
fi

if ((WIDGET)) && command -v kpackagetool6 >/dev/null; then
    kpackagetool6 -t Plasma/Applet -u plasmoid/claude >/dev/null 2>&1 || kpackagetool6 -t Plasma/Applet -i plasmoid/claude >/dev/null
    ok "masaüstü widget'ı kuruldu: masaüstüne sağ tıkla → Widget ekle → \"Asistan for Claude Code\""
    if command -v nvidia-smi >/dev/null; then  # NVIDIA kartın sıcaklığı (üst çubuk için; kart uyurken uyandırmaz)
        kpackagetool6 -t Plasma/Applet -u plasmoid/gpu >/dev/null 2>&1 || kpackagetool6 -t Plasma/Applet -i plasmoid/gpu >/dev/null
        ok "ekran kartı göstergesi kuruldu (üst çubuğa eklenebilir: \"Ekran kartı sıcaklığı\")"
    fi
fi

if ! python3 -c "import sys; sys.path.insert(0, '$DIR/scripts'); import sesli_istem; sys.exit(0 if sesli_istem.available() else 1)"; then
    say "Konuşarak yazma için Dikte kurulabilir: https://github.com/yusufipk/dikte (kurulunca mikrofon kendiliğinden görünür)"
fi

echo
echo "Bitti. Açmak için: asistan  (ya da uygulama menüsünden Asistan for Claude Code)"
