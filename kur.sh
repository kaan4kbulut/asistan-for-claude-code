#!/usr/bin/env bash
# Asistan for Claude Code'u kurar ya da günceller (bu klasörden çalışır, dosyaları kopyalamaz):
#   - eksik gerekenleri dağıtımın paket yöneticisiyle kurar: tmux, PySide6 (QtWebEngine ile)
#   - Claude Code kurulu değilse resmî kurulum betiğiyle kurar
#   - başlatıcı: ~/.local/bin/asistan (ve eski adıyla claude-arka)
#   - uygulama menüsü kaydı ve oturum açılışında sistem tepsisinde başlatma
#   - masaüstü widget'ı (yalnızca KDE Plasma 6'da)
#   - konuşarak yazma için Dikte'yi (github.com/yusufipk/dikte) gerekenleriyle indirip kurar; kuruluysa dokunmaz
# Kullanıcıdan elle bir şey kurması istenmez; yönetici parolası yalnızca sistem paketleri için sorulur.
# Seçenekler: --widget-yok, --otomatik-baslatma-yok, --dikte-yok
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
DIR="$PWD"
WIDGET=1
AUTOSTART=1
DIKTE=1
for a in "$@"; do
    case "$a" in
        --widget-yok) WIDGET=0 ;;
        --otomatik-baslatma-yok) AUTOSTART=0 ;;
        --dikte-yok) DIKTE=0 ;;
    esac
done
DIKTE_REPO="https://github.com/yusufipk/dikte"
DIKTE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/dikte"

ok() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
say() { printf '  %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }

# Paket yöneticisi ve mantıksal adların dağıtımdaki karşılıkları
PM=""
for p in pacman apt-get dnf zypper; do
    if command -v "$p" >/dev/null; then PM="$p"; break; fi
done
paket_adlari() {  # mantıksal ad → paket adları
    case "$PM:$1" in
        *:tmux) echo tmux ;;
        *:git) echo git ;;
        *:ffmpeg) case "$PM" in dnf) echo ffmpeg-free ;; *) echo ffmpeg ;; esac ;;
        pacman:pyside) echo pyside6 qt6-webengine ;;
        apt-get:pyside) echo python3-pyside6.qtwebenginewidgets python3-pyside6.qtquickwidgets python3-pyside6.qtwebchannel ;;
        dnf:pyside | zypper:pyside) echo python3-pyside6 ;;
        pacman:pyqt) echo python-pyqt6 ;;
        apt-get:pyqt | dnf:pyqt) echo python3-pyqt6 ;;
        zypper:pyqt) echo python3-PyQt6 ;;
        pacman:ses) echo pipewire-audio ;;
        apt-get:ses) echo pipewire-bin ;;
        dnf:ses) echo pipewire-utils ;;
        zypper:ses) echo pipewire-tools ;;
        *:pano) [[ "${XDG_SESSION_TYPE:-}" == "x11" ]] && echo xclip xdotool || echo wl-clipboard ydotool ;;
    esac
}
paket_kur() {  # mantıksal adlar
    local pkgs=()
    for n in "$@"; do
        read -r -a ad <<<"$(paket_adlari "$n")"
        pkgs+=("${ad[@]}")
    done
    ((${#pkgs[@]})) || return 0
    say "Kuruluyor: ${pkgs[*]} (yönetici parolası istenebilir)…"
    case "$PM" in
        pacman) sudo pacman -S --needed --noconfirm "${pkgs[@]}" ;;
        apt-get) sudo apt-get install -y "${pkgs[@]}" ;;
        dnf) sudo dnf install -y "${pkgs[@]}" ;;
        zypper) sudo zypper install -y "${pkgs[@]}" ;;
        *) return 1 ;;
    esac
}

echo
echo "Asistan for Claude Code kuruluyor"
echo "───────────────────────────────────"

eksik=()
command -v tmux >/dev/null || eksik+=(tmux)
python3 -c 'import PySide6.QtWebEngineWidgets, PySide6.QtQuickWidgets, PySide6.QtWebChannel' 2>/dev/null || eksik+=(pyside)
if ((${#eksik[@]})); then
    if [[ -n "$PM" ]]; then
        paket_kur "${eksik[@]}"
    elif [[ " ${eksik[*]} " == *" tmux "* ]]; then
        echo "tmux kurulamadı: paket yöneticisi tanınmadı"
        exit 1
    else
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

# Konuşarak yazma: Dikte (kendi deposundan, kendi kurulum betiğiyle). Kuruluysa (nereye kurulduysa) dokunulmaz.
dikte_kurulu() {
    python3 -c "import sys; sys.path.insert(0, '$DIR/scripts'); import sesli_istem; sys.exit(0 if sesli_istem.available() else 1)"
}
if ((DIKTE)) && ! dikte_kurulu; then
    say "Konuşarak yazma için Dikte kuruluyor…"
    gerek=()
    command -v git >/dev/null || gerek+=(git)
    command -v ffmpeg >/dev/null || gerek+=(ffmpeg)
    command -v pw-record >/dev/null || command -v parec >/dev/null || gerek+=(ses)
    if [[ "${XDG_SESSION_TYPE:-}" == "x11" ]]; then
        command -v xclip >/dev/null && command -v xdotool >/dev/null || gerek+=(pano)
    else
        command -v wl-copy >/dev/null && command -v ydotool >/dev/null || gerek+=(pano)
    fi
    python3 -c 'import PyQt6.QtWidgets' 2>/dev/null || gerek+=(pyqt)
    if ((${#gerek[@]})) && [[ -n "$PM" ]]; then
        paket_kur "${gerek[@]}" || warn "Dikte'nin gerekenlerinden bazıları kurulamadı"
    fi
    if [[ -d "$DIKTE_DIR/.git" ]]; then
        git -C "$DIKTE_DIR" pull --ff-only -q || true
    else
        git clone -q --depth 1 "$DIKTE_REPO" "$DIKTE_DIR"
    fi
    # Wayland'de otomatik yapıştırma ydotoold ister; paket kullanıcı servisi getiriyorsa aç
    if [[ "${XDG_SESSION_TYPE:-}" != "x11" ]] && systemctl --user cat ydotool.service >/dev/null 2>&1; then
        systemctl --user enable --now ydotool.service >/dev/null 2>&1 || true
    fi
    if bash "$DIKTE_DIR/install.sh" && dikte_kurulu; then
        ok "Dikte kuruldu: mikrofon düğmesi programda ve widget'ta görünür (ilk kayıtta ses modeli iner)"
    else
        warn "Dikte kurulamadı; Asistan onsuz da çalışır. Yeniden denemek için: ./kur.sh"
    fi
elif ((DIKTE)); then
    ok "Dikte zaten kurulu (konuşarak yazma hazır)"
fi

echo
echo "Bitti. Açmak için: asistan  (ya da uygulama menüsünden Asistan for Claude Code)"
