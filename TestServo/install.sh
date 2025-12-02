#!/usr/bin/env bash
set -e

APP_NAME="Servo Tester"
APP_ID="servo-tester"
INSTALL_DIR="$HOME/.local/share/$APP_ID"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"

echo "==> Menyalin berkas ke $INSTALL_DIR"
mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$DESKTOP_DIR"
cp -f testServo.py requirements.txt "$INSTALL_DIR"/
[ -f icon.png ] && cp -f icon.png "$INSTALL_DIR"/

echo "==> Membuat virtualenv"
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "$INSTALL_DIR/requirements.txt"

# pastikan Tkinter ada (kalau belum, install via apt)
python - <<'PY' || (echo "==> Menginstall python3-tk (butuh sudo)"; sudo apt-get update && sudo apt-get install -y python3-tk)
import tkinter
print("tk ok")
PY
deactivate

echo "==> Membuat launcher CLI di $BIN_DIR/$APP_ID"
cat > "$BIN_DIR/$APP_ID" <<WRAP
#!/usr/bin/env bash
exec "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/testServo.py" "\$@"
WRAP
chmod +x "$BIN_DIR/$APP_ID"

echo "==> Membuat desktop entry"
ICON_PATH="$INSTALL_DIR/icon.png"
[ -f "$ICON_PATH" ] || ICON_PATH=utilities-terminal
cat > "$DESKTOP_DIR/$APP_ID.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=$APP_NAME
Exec=$BIN_DIR/$APP_ID
Icon=$ICON_PATH
Terminal=false
Categories=Utility;Development;
StartupNotify=true
DESK

# tambah PATH jika belum
if ! echo ":$PATH:" | grep -q ":$HOME/.local/bin:"; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.profile"
  echo "==> Menambahkan \$HOME/.local/bin ke PATH (buka terminal baru sesudah ini)"
fi

# akses serial
if ! groups "$USER" | grep -q dialout; then
  echo "==> Menambahkan $USER ke grup dialout (logout/login agar aktif)"
  sudo usermod -aG dialout "$USER" || true
fi

update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
echo "==> Selesai. Jalankan: servo-tester (atau via menu: \"$APP_NAME\")"
