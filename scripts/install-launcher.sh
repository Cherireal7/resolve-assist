#!/bin/zsh
# Installs the one-word command (`studio`) and the clickable Studio.app. Safe to run again.
set -eu
REPO="${0:A:h:h}"
mkdir -p "$HOME/.local/bin" "$HOME/Applications"
ln -sf "$REPO/scripts/studio" "$HOME/.local/bin/studio"
ln -sf "$REPO/scripts/studio" "$HOME/.local/bin/tibeb"
rm -rf "$HOME/Applications/Studio.app"
APP="$HOME/Applications/Tibeb.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$REPO/scripts/app/Studio.icns" "$APP/Contents/Resources/Studio.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Tibeb</string>
<key>CFBundleIdentifier</key><string>local.tibeb.launcher</string>
<key>CFBundleExecutable</key><string>Studio</string>
<key>CFBundleIconFile</key><string>Studio</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.1</string>
<key>LSUIElement</key><true/>
</dict></plist>
PLIST
# The app only opens a Terminal window that runs `studio` (interactive shell, so your PATH applies).
cat > "$APP/Contents/Resources/Start.command" <<CMD
#!/bin/zsh -i
exec "\$HOME/.local/bin/studio"
CMD
cat > "$APP/Contents/MacOS/Studio" <<'RUN'
#!/bin/zsh
exec open -a Terminal "${0:A:h:h}/Resources/Start.command"
RUN
chmod +x "$APP/Contents/MacOS/Studio" "$APP/Contents/Resources/Start.command"
touch "$APP"
print "Installed: type 'tibeb' (or 'studio') in a terminal, or open $APP (drag it to the Dock)."
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) print "Note: add ~/.local/bin to your PATH.";; esac
