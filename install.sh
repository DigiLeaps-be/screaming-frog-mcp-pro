#!/bin/bash
#
# Installer voor screaming-frog-mcp-pro op macOS
# Gebaseerd op de Digileaps installer v3.1, aangepast voor de Pro-fork.
#
# Werkwijze:
#   1. Inventariseer wat al geïnstalleerd is (Java 21, Python 3.12, Ant, etc.)
#   2. Installeer wat ontbreekt
#   3. Clone deze repo (of gebruik lokale kopie)
#   4. Maak venv en installeer
#   5. Configureer Claude Desktop
#

set -e

# === Configuratie ===
INSTALL_DIR="${SF_MCP_PRO_INSTALL_DIR:-$HOME/tools/screaming-frog-mcp-pro}"

# Pas dit aan naar je eigen GitHub-repo na het pushen.
# Of laat leeg om vanuit de huidige directory te installeren.
REPO_URL="${SF_MCP_PRO_REPO_URL:-https://github.com/DigiLeaps-be/screaming-frog-mcp-pro.git}"

CLAUDE_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
SERVER_NAME="screaming-frog-pro"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

cat <<'EOF'

============================================================
 screaming-frog-mcp-pro Installer
 Enhanced MCP server for Screaming Frog SEO Spider
============================================================

EOF

# === Inventaris ===
echo "Inventariseren wat er op je systeem staat..."
echo

declare -A status

# Xcode CLT
if xcode-select -p >/dev/null 2>&1; then
    status[xcode]="aanwezig"
else
    status[xcode]="ONTBREEKT"
fi

# Homebrew
if command -v brew >/dev/null 2>&1; then
    status[brew]="aanwezig"
    BREW_PREFIX=$(brew --prefix)
else
    status[brew]="ONTBREEKT"
fi

# Python 3.12
if command -v python3.12 >/dev/null 2>&1; then
    status[python]="aanwezig ($(python3.12 --version 2>&1))"
else
    status[python]="ONTBREEKT"
fi

# Git
if command -v git >/dev/null 2>&1; then
    status[git]="aanwezig"
else
    status[git]="ONTBREEKT"
fi

# OpenJDK 21
if /usr/libexec/java_home -v 21 >/dev/null 2>&1; then
    JAVA21_HOME=$(/usr/libexec/java_home -v 21)
    status[java21]="aanwezig ($JAVA21_HOME)"
else
    status[java21]="ONTBREEKT"
fi

# Ant
if command -v ant >/dev/null 2>&1; then
    status[ant]="aanwezig"
else
    status[ant]="ONTBREEKT"
fi

# Toon tabel
printf "  %-20s %s\n" "Component" "Status"
printf "  %-20s %s\n" "--------------------" "----------------------------------------"
for k in xcode brew python git java21 ant; do
    color="$GREEN"
    [[ "${status[$k]}" == ONTBREEKT* ]] && color="$YELLOW"
    printf "  %-20s ${color}%s${NC}\n" "$k" "${status[$k]}"
done
echo

# === Plan ===
echo "Plan:"
to_install=()
for k in xcode brew python git java21 ant; do
    if [[ "${status[$k]}" == ONTBREEKT* ]]; then
        to_install+=("$k")
        echo "  - Installeren: $k"
    fi
done
if [ ${#to_install[@]} -eq 0 ]; then
    echo "  Alle dependencies zijn aanwezig."
fi
echo "  - Clone of kopieer screaming-frog-mcp-pro naar $INSTALL_DIR"
echo "  - Maak Python virtual environment"
echo "  - Installeer screaming-frog-mcp-pro met pip install -e ."
echo "  - Voeg '$SERVER_NAME' toe aan Claude Desktop config"
echo

read -p "Doorgaan? [y/N] " -n 1 -r
echo
[[ $REPLY =~ ^[Yy]$ ]] || { echo "Geannuleerd."; exit 0; }

# === Installaties ===
if [[ " ${to_install[@]} " =~ " xcode " ]]; then
    echo "Installeer Xcode Command Line Tools..."
    xcode-select --install || true
    echo "Volg de GUI-prompt en re-run dit script wanneer klaar."
    exit 0
fi

if [[ " ${to_install[@]} " =~ " brew " ]]; then
    echo "Installeer Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    BREW_PREFIX=$(brew --prefix)
fi

if [[ " ${to_install[@]} " =~ " python " ]]; then
    echo "Installeer Python 3.12..."
    brew install python@3.12
fi

if [[ " ${to_install[@]} " =~ " git " ]]; then
    echo "Installeer Git..."
    brew install git
fi

if [[ " ${to_install[@]} " =~ " java21 " ]]; then
    echo "Installeer OpenJDK 21..."
    brew install openjdk@21
    echo "Symlink openjdk@21 zodat macOS Java 21 vindt (sudo nodig)..."
    sudo ln -sfn "$(brew --prefix)/opt/openjdk@21/libexec/openjdk.jdk" \
        /Library/Java/JavaVirtualMachines/openjdk-21.jdk
    JAVA21_HOME=$(/usr/libexec/java_home -v 21)
fi

if [[ " ${to_install[@]} " =~ " ant " ]]; then
    echo "Installeer Apache Ant..."
    brew install ant
fi

# === Repo ===
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Update bestaande clone in $INSTALL_DIR..."
    cd "$INSTALL_DIR" && git pull
elif [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Map $INSTALL_DIR bestaat maar is geen git-clone.${NC}"
    read -p "Verwijderen en opnieuw installeren? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$INSTALL_DIR"
        git clone "$REPO_URL" "$INSTALL_DIR"
    else
        echo "Geannuleerd."
        exit 1
    fi
else
    echo "Clone repo naar $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# === Venv + install ===
cd "$INSTALL_DIR"
if [ ! -d ".venv" ]; then
    echo "Maak Python virtual environment..."
    "$BREW_PREFIX/bin/python3.12" -m venv .venv
fi

echo "Installeer screaming-frog-mcp-pro..."
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
deactivate

# === Claude Desktop config ===
echo "Configureer Claude Desktop..."
mkdir -p "$(dirname "$CLAUDE_CONFIG")"

# Backup
if [ -f "$CLAUDE_CONFIG" ]; then
    timestamp=$(date +%Y%m%d-%H%M%S)
    cp "$CLAUDE_CONFIG" "$CLAUDE_CONFIG.bak.$timestamp"
    echo "  Backup gemaakt: $CLAUDE_CONFIG.bak.$timestamp"
fi

# Merge entry via python
python3 <<PYEOF
import json
import os
from pathlib import Path

config_path = Path("$CLAUDE_CONFIG")
entry = {
    "command": str(Path("$INSTALL_DIR") / ".venv" / "bin" / "screaming-frog-mcp-pro"),
    "env": {
        "JAVA_HOME": "$JAVA21_HOME"
    }
}

if config_path.exists():
    with open(config_path) as f:
        config = json.load(f)
else:
    config = {}

config.setdefault("mcpServers", {})
config["mcpServers"]["$SERVER_NAME"] = entry

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print(f"  Toegevoegd: mcpServers.$SERVER_NAME")
PYEOF

cat <<'EOF'

============================================================
 Klaar.
============================================================

Volgende stappen:

  1. Sluit Claude Desktop volledig af met Cmd+Q (NIET enkel het
     venster sluiten).

  2. Heropen Claude Desktop.

  3. Test met een prompt zoals:
       "Lijst mijn Screaming Frog crawls."

  Als Claude antwoordt met een lijst van crawls, werkt het.

Documentatie:
  README.md             Hoe je het gebruikt
  CHANGELOG.md          Verschillen met upstream
  docs/derby-fixes.md   Technische uitleg

EOF
