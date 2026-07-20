#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  macinstall.sh  -  Dogbox Mailman macOS Installer
#  Usage:  chmod +x macinstall.sh && ./macinstall.sh
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info()  { echo -e "${CYAN}[mailman]${RESET} $*"; }
ok()    { echo -e "${GREEN}[  OK  ]${RESET} $*"; }
warn()  { echo -e "${YELLOW}[ WARN ]${RESET} $*"; }
error() { echo -e "${RED}[ERROR ]${RESET} $*"; }

echo -e "${BOLD}Dogbox Mailman - AI Email Client - macOS Installer${RESET}"
echo "────────────────────────────────────────────────────"
echo ""

# ── 1. Find Python 3.9+ ───────────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python3.13 python3.12 python3.11 python3.10 python3.9; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(sys.version_info >= (3,9))" 2>/dev/null)
        if [ "$VER" = "True" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    error "Python 3.9 or later is required but was not found."
    echo ""
    echo "  Download it from:  https://www.python.org/downloads/"
    echo "  Or via Homebrew:   brew install python3"
    echo ""
    read -r -p "  Open python.org now? [Y/n] " REPLY
    if [[ ! "$REPLY" =~ ^[Nn]$ ]]; then
        open "https://www.python.org/downloads/"
    fi
    exit 1
fi

PY_VER=$("$PYTHON" --version 2>&1)
ok "Found $PY_VER  ($PYTHON)"

# ── 2. Install required packages ──────────────────────────────────────────────
MISSING_PKGS=()
"$PYTHON" -c "import flask"       2>/dev/null || MISSING_PKGS+=("flask")
"$PYTHON" -c "import imapclient"  2>/dev/null || MISSING_PKGS+=("imapclient")
"$PYTHON" -c "import keyring"     2>/dev/null || MISSING_PKGS+=("keyring")

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    warn "Missing packages: ${MISSING_PKGS[*]}"
    echo ""
    read -r -p "  Install all required packages now with pip? [Y/n] " REPLY
    echo ""
    if [[ ! "$REPLY" =~ ^[Nn]$ ]]; then
        info "Installing packages..."
        if "$PYTHON" -m pip install flask imapclient keyring google-auth-oauthlib msal anthropic bleach beautifulsoup4 google-auth --quiet; then
            ok "Packages installed."
        else
            warn "Some packages may not have installed. Try:"
            echo "     pip3 install flask imapclient keyring google-auth-oauthlib msal anthropic bleach beautifulsoup4"
        fi
    else
        warn "Skipping. Dogbox Mailman will not run until required packages are installed."
    fi
else
    ok "Required packages already installed."
fi

# ── 3. Create desktop launcher (.command file) ────────────────────────────────
LAUNCHER="$HOME/Desktop/Dogbox Mailman.command"
MAIL_PY="$SCRIPT_DIR/mail.py"

cat > "$LAUNCHER" <<LAUNCHER_EOF
#!/bin/bash
cd "$SCRIPT_DIR"
"$PYTHON" "$MAIL_PY"
LAUNCHER_EOF

chmod +x "$LAUNCHER"
ok "Desktop launcher created: ~/Desktop/Dogbox Mailman.command"
echo "     Double-click it (or right-click → Open) to launch."

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "  ────────────────────────────────────────────────────"
echo "   Installation complete!"
echo ""
echo "   Double-click 'Dogbox Mailman' on your Desktop"
echo "   to launch. It opens in your browser automatically."
echo ""
echo "   Or run from a terminal:"
echo "     python3 mail.py"
echo "  ────────────────────────────────────────────────────"
echo ""

read -r -p "  Launch Dogbox Mailman now? [Y/n] " REPLY
if [[ ! "$REPLY" =~ ^[Nn]$ ]]; then
    "$PYTHON" "$MAIL_PY" &
    echo ""
    ok "Dogbox Mailman is starting..."
fi
