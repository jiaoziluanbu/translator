#!/bin/bash
# Local Translator 一键安装脚本
# 用法: bash install.sh

set -e

echo ""
echo "========================================="
echo "  Local Translator Installer"
echo "========================================="
echo ""

# 检查 Python3
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python3 not found. Please install Python3 first."
    echo "  macOS:   xcode-select --install"
    echo "  Linux:   sudo apt install python3 python3-pip"
    echo "  Windows: https://www.python.org/downloads/"
    exit 1
fi

PY_VERSION=$(python3 --version)
echo "[OK] Found $PY_VERSION"

# 检查 pip3
if ! command -v pip3 &>/dev/null; then
    echo "[INFO] pip3 not found, installing..."
    python3 -m ensurepip --upgrade 2>/dev/null || {
        echo "[ERROR] Failed to install pip. Please install manually."
        exit 1
    }
fi
echo "[OK] Found pip3"

# 升级 pip
echo "[INFO] Upgrading pip..."
python3 -m pip install --upgrade pip 2>/dev/null || pip3 install --upgrade pip 2>/dev/null || true

# 安装依赖
echo ""
echo "[INFO] Installing pywebview and argostranslate..."
pip3 install pywebview argostranslate rumps pynput pyobjc-framework-ApplicationServices 2>&1 | tail -5
echo "[OK] Dependencies installed"

# 下载语言包
echo ""
echo "[INFO] Downloading language packs (this may take a few minutes)..."
python3 -c "
import argostranslate.package as pkg

pkg.update_package_index()
available = pkg.get_available_packages()

pairs = [
    ('en','zh'), ('zh','en'),
    ('en','ja'), ('ja','en'),
    ('en','ko'), ('ko','en'),
    ('en','fr'), ('fr','en'),
    ('en','de'), ('de','en'),
    ('en','es'), ('es','en'),
    ('en','ru'), ('ru','en'),
    ('en','pt'), ('pt','en'),
    ('en','it'), ('it','en'),
    ('en','ar'), ('ar','en'),
]

installed = 0
for src, tgt in pairs:
    for p in available:
        if p.from_code == src and p.to_code == tgt:
            print(f'  Downloading {src} -> {tgt}...')
            pkg.install_from_path(p.download())
            installed += 1
            break

print(f'  Done. {installed} language packs installed.')
"
echo "[OK] Language packs ready"

# macOS: 创建 .app
if [[ "$(uname)" == "Darwin" ]]; then
    echo ""
    echo "[INFO] Creating macOS apps..."
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    SITE_PACKAGES=$(python3 -c "import site; print(site.getusersitepackages())")

    # 原有翻译器窗口应用
    APP_PATH="$SCRIPT_DIR/Local Translator.app"
    rm -rf "$APP_PATH"
    osacompile -o "$APP_PATH" -e "do shell script \"export PYTHONPATH=$SITE_PACKAGES && /usr/bin/python3 $SCRIPT_DIR/app.py &> /tmp/translator.log &\""
    echo "[OK] Created 'Local Translator.app'"

    # 选中即翻译后台服务
    DAEMON_PATH="$SCRIPT_DIR/Translate Daemon.app"
    rm -rf "$DAEMON_PATH"
    osacompile -o "$DAEMON_PATH" -e "do shell script \"export PYTHONPATH=$SITE_PACKAGES && /usr/bin/python3 $SCRIPT_DIR/daemon.py &> /tmp/translator-daemon.log &\""
    echo "[OK] Created 'Translate Daemon.app'"
fi

# ===== 安装右键菜单服务 =====
echo ""
echo "[INFO] Installing right-click Translate service..."
SERVICES_DIR="$HOME/Library/Services"
WORKFLOW_PATH="$SERVICES_DIR/Translate.workflow"
mkdir -p "$WORKFLOW_PATH/Contents"

cat > "$WORKFLOW_PATH/Contents/Info.plist" << 'INFOEOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>NSServices</key>
	<array>
		<dict>
			<key>NSMenuItem</key>
			<dict>
				<key>default</key>
				<string>Translate</string>
			</dict>
			<key>NSMessage</key>
			<string>runWorkflowAsService</string>
			<key>NSSendTypes</key>
			<array>
				<string>NSStringPboardType</string>
			</array>
		</dict>
	</array>
</dict>
</plist>
INFOEOF

SITE_PKG=$(python3 -c "import site; print(site.getusersitepackages())")
TRANSLATE_CMD="export PYTHONPATH=$SITE_PKG\n/usr/bin/python3 $SCRIPT_DIR/translate_cli.py --dialog"

cat > "$WORKFLOW_PATH/Contents/document.wflow" << WFEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>AMApplicationBuild</key><string>523</string>
	<key>AMApplicationVersion</key><string>2.10</string>
	<key>AMDocumentVersion</key><string>2</string>
	<key>actions</key>
	<array>
		<dict>
			<key>action</key>
			<dict>
				<key>AMAccepts</key><dict><key>Container</key><string>List</string><key>Optional</key><true/><key>Types</key><array><string>com.apple.cocoa.string</string></array></dict>
				<key>AMActionVersion</key><string>2.0.3</string>
				<key>AMApplication</key><array><string>Automator</string></array>
				<key>AMLargeIconName</key><string>RunShellScript</string>
				<key>AMParameterProperties</key><dict><key>COMMAND_STRING</key><dict/><key>CheckedForUserDefaultShell</key><dict/><key>inputMethod</key><dict/><key>shell</key><dict/><key>source</key><dict/></dict>
				<key>AMProvides</key><dict><key>Container</key><string>List</string><key>Types</key><array><string>com.apple.cocoa.string</string></array></dict>
				<key>ActionBundlePath</key><string>/System/Library/Automator/Run Shell Script.action</string>
				<key>ActionName</key><string>Run Shell Script</string>
				<key>ActionParameters</key>
				<dict>
					<key>COMMAND_STRING</key><string>export PYTHONPATH=$SITE_PKG
/usr/bin/python3 $SCRIPT_DIR/translate_cli.py --dialog</string>
					<key>CheckedForUserDefaultShell</key><true/>
					<key>inputMethod</key><integer>0</integer>
					<key>shell</key><string>/bin/bash</string>
					<key>source</key><string></string>
				</dict>
				<key>BundleIdentifier</key><string>com.apple.RunShellScript</string>
				<key>CFBundleVersion</key><string>2.0.3</string>
				<key>CanShowSelectedItemsWhenRun</key><false/>
				<key>CanShowWhenRun</key><true/>
				<key>Category</key><array><string>AMCategoryUtilities</string></array>
				<key>Class Name</key><string>RunShellScriptAction</string>
				<key>InputUUID</key><string>D4D049FB-6D3C-4E0C-9B6A-1F53A0B5F45D</string>
				<key>Keywords</key><array><string>Shell</string><string>Script</string></array>
				<key>OutputUUID</key><string>E7F14A2B-8C5D-4F1A-B3E6-2A64C1D6F78E</string>
				<key>UUID</key><string>A1B2C3D4-E5F6-7890-ABCD-EF1234567890</string>
				<key>UnlocalizedApplications</key><array><string>Automator</string></array>
				<key>arguments</key>
				<dict>
					<key>0</key><dict><key>default value</key><integer>0</integer><key>name</key><string>inputMethod</string><key>required</key><string>0</string><key>type</key><string>0</string><key>uuid</key><string>0</string></dict>
					<key>1</key><dict><key>default value</key><string></string><key>name</key><string>source</string><key>required</key><string>0</string><key>type</key><string>0</string><key>uuid</key><string>1</string></dict>
					<key>2</key><dict><key>default value</key><false/><key>name</key><string>CheckedForUserDefaultShell</string><key>required</key><string>0</string><key>type</key><string>0</string><key>uuid</key><string>2</string></dict>
					<key>3</key><dict><key>default value</key><string></string><key>name</key><string>COMMAND_STRING</string><key>required</key><string>0</string><key>type</key><string>0</string><key>uuid</key><string>3</string></dict>
					<key>4</key><dict><key>default value</key><string>/bin/sh</string><key>name</key><string>shell</string><key>required</key><string>0</string><key>type</key><string>0</string><key>uuid</key><string>4</string></dict>
				</dict>
				<key>isViewVisible</key><true/>
				<key>location</key><string>529.000000:305.000000</string>
				<key>nibPath</key><string>/System/Library/Automator/Run Shell Script.action/Contents/Resources/Base.lproj/main.nib</string>
			</dict>
			<key>isViewVisible</key><true/>
		</dict>
	</array>
	<key>connectors</key><dict/>
	<key>workflowMetaData</key>
	<dict>
		<key>serviceInputTypeIdentifier</key><string>com.apple.Automator.text</string>
		<key>serviceOutputTypeIdentifier</key><string>com.apple.Automator.nothing</string>
		<key>serviceProcessesInput</key><integer>0</integer>
		<key>workflowTypeIdentifier</key><string>com.apple.Automator.servicesMenu</string>
	</dict>
</dict>
</plist>
WFEOF

/System/Library/CoreServices/pbs -flush 2>/dev/null || true
echo "[OK] Right-click 'Translate' service installed"

# ===== 快捷键引导（首次安装必读） =====
echo ""
echo "========================================="
echo "  Quick Start Guide"
echo "========================================="
echo ""
echo "  Local Translator provides TWO ways to translate:"
echo ""
echo "  [Method 1] Hotkey (needs Translate Daemon running)"
echo "    1. Select any text"
echo "    2. Press:  Cmd + Shift + Y  (Win + Shift + Y)"
echo "    3. Floating popup shows translation"
echo ""
echo "  [Method 2] Right-click menu (works immediately)"
echo "    1. Select any text"
echo "    2. Right-click -> Services -> Translate"
echo "    3. Dialog shows translation with Copy button"
echo ""
echo "  IMPORTANT: First launch requires Accessibility permission."
echo "    System Settings -> Privacy & Security -> Accessibility"
echo ""

# 让用户输入快捷键确认学会
while true; do
    printf "  Type the hotkey to confirm you learned it (e.g. cmd+shift+y): "
    read shortcut_input
    shortcut_lower=$(echo "$shortcut_input" | tr '[:upper:]' '[:lower:]' | tr -d ' ')
    if [[ "$shortcut_lower" == "cmd+shift+y" ]]; then
        echo ""
        echo "  Correct! You're all set."
        break
    else
        echo "  Not quite. The hotkey is: cmd+shift+y"
        echo "  (hold Command/Win and Shift, then tap Y)"
        echo ""
    fi
done

echo ""
echo "========================================="
echo "  Installation complete!"
echo "========================================="
echo ""
echo "  Usage:"
SCRIPT_DIR_FINAL="$(cd "$(dirname "$0")" && pwd)"
echo "    Translator window:   python3 $SCRIPT_DIR_FINAL/app.py"
echo "    Select-to-translate:  python3 $SCRIPT_DIR_FINAL/daemon.py"
if [[ "$(uname)" == "Darwin" ]]; then
echo "    macOS apps:  Double click 'Local Translator.app' or 'Translate Daemon.app'"
fi
echo "    Browser mode:  python3 $SCRIPT_DIR_FINAL/serve.py"
echo ""
