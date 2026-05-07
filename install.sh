#!/bin/bash
#
# Installer voor screaming-frog-mcp-pro op macOS
# Bash 3.2 compatibel (zoals geleverd door Apple op alle moderne Macs).
#

set -e

# === Configuratie ===
INSTALL_DIR="${SF_MCP_PRO_INSTALL_DIR:-$HOME/tools/screaming-frog-mcp-pro}"
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

# === Inventaris (geen associative arrays, voor bash 3.2 compatibiliteit) ===
echo "Inventariseren wat er op je systeem staat..."
echo

# Statussen als losse variabelen
xcode_status=""
brew_status=""
python_status=""
git_status=""
java21_status=""
ant_status=""
JAVA21_HOME=""
BREW_PREFIX=""

# Xcode CLT
if xcode-select -p >/dev/null 2>&1; then
    xcode_status="aanwezig"
else
    xcode_status="ONTBREEKT"
fi

# Homebrew
if command -v brew >/dev/null 2>&1; then
    BREW_PREFIX=$(brew --prefix)
    brew_status="aanwezig"
else
    brew_status="ONTBREEKT"
fi

# Python 3.12
if command -v python3.12 >/dev/null 2>&1; then
    python_status="aanwezig ($(python3.12 --version 2>&1))"
else
    python_status="ONTBREEKT"
fi

# Git
if command -v git >/dev/null 2>&1; then
    git_status="aanwezig"
else
    git_status="ONTBREEKT"
fi

# OpenJDK 21
if /usr/libexec/java_home -v 21 >/dev/null 2>&1; then
    JAVA21_HOME=$(/usr/libexec/java_home -v 21)
    java21_status="aanwezig ($JAVA21_HOME)"
else
    java21_status="ONTBREEKT"
fi

# Ant
if command -v ant >/dev/null 2>&1; then
    ant_status="aanwezig"
else
    ant_status="ONTBREEKT"
fi

# Tabel (printf werkt in bash 3.2)
print_status() {
    local name="$1"
    local value="$2"
    local color="$GREEN"
    case "$value" in
        ONTBREEKT*) color="$YELLOW" ;;
    esac
    printf "  %-20s ${color}%s${NC}\n" "$name" "$value"
}

printf "  %-20s %s\n" "Component" "Status"
printf "  %-20s %s\n" "--------------------" "----------------------------------------"
print_status "xcode" "$xcode_status"
print_status "brew" "$brew_status"
print_status "python" "$python_status"
print_status "git" "$git_status"
print_status "java21" "$java21_status"
print_status "ant" "$ant_status"
echo

# === Plan ===
echo "Plan:"
to_install=""
add_to_install() {
    if [ -z "$to_install" ]; then
        to_install="$1"
    else
        to_install="$to_install $1"
    fi
}
needs_install() {
    case "$1" in
        ONTBREEKT*) return 0 ;;
        *) return 1 ;;
    esac
}

needs_install "$xcode_status"  && add_to_install "xcode"  && echo "  - Installeren: Xcode Command Line Tools"
needs_install "$brew_status"   && add_to_install "brew"   && echo "  - Installeren: Homebrew"
needs_install "$python_status" && add_to_install "python" && echo "  - Installeren: Python 3.12"
needs_install "$git_status"    && add_to_install "git"    && echo "  - Installeren: Git"
needs_install "$java21_status" && add_to_install "java21" && echo "  - Installeren: OpenJDK 21"
needs_install "$ant_status"    && add_to_install "ant"    && echo "  - Installeren: Apache Ant"

if [ -z "$to_install" ]; then
    echo "  Alle dependencies zijn aanwezig."
fi
echo "  - Clone of update screaming-frog-mcp-pro in $INSTALL_DIR"
echo "  - Maak Python virtual environment"
echo "  - Installeer screaming-frog-mcp-pro met pip install -e ."
echo "  - Voeg '$SERVER_NAME' toe aan Claude Desktop config"
echo

read -p "Doorgaan? [y/N] " -n 1 -r
echo
[[ $REPLY =~ ^[Yy]$ ]] || { echo "Geannuleerd."; exit 0; }

# Helper om te checken of een component in de install-lijst zit
in_install_list() {
    case " $to_install " in
        *" $1 "*) return 0 ;;
        *) return 1 ;;
    esac
}

# === Installaties ===
if in_install_list "xcode"; then
    echo "Installeer Xcode Command Line Tools..."
    xcode-select --install || true
    echo "Volg de GUI-prompt en re-run dit script wanneer klaar."
    exit 0
fi

if in_install_list "brew"; then
    echo "Installeer Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    BREW_PREFIX=$(brew --prefix)
fi

if in_install_list "python"; then
    echo "Installeer Python 3.12..."
    brew install python@3.12
fi

if in_install_list "git"; then
    echo "Installeer Git..."
    brew install git
fi

if in_install_list "java21"; then
    echo "Installeer OpenJDK 21..."
    brew install openjdk@21
    echo "Symlink openjdk@21 zodat macOS Java 21 vindt (sudo nodig)..."
    sudo ln -sfn "$(brew --prefix)/opt/openjdk@21/libexec/openjdk.jdk" \
        /Library/Java/JavaVirtualMachines/openjdk-21.jdk
    JAVA21_HOME=$(/usr/libexec/java_home -v 21)
fi

if in_install_list "ant"; then
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

# Merge entry via python (export vars zodat python ze kan lezen)
export CLAUDE_CONFIG_PATH="$CLAUDE_CONFIG"
export INSTALL_DIR_PATH="$INSTALL_DIR"
export JAVA21_HOME_PATH="$JAVA21_HOME"
export SERVER_NAME_VAL="$SERVER_NAME"

python3 <<'PYEOF'
import json
import os
from pathlib import Path

config_path = Path(os.environ["CLAUDE_CONFIG_PATH"])
install_dir = Path(os.environ["INSTALL_DIR_PATH"])
java_home = os.environ["JAVA21_HOME_PATH"]
server_name = os.environ["SERVER_NAME_VAL"]

entry = {
    "command": str(install_dir / ".venv" / "bin" / "screaming-frog-mcp-pro"),
    "env": {
        "JAVA_HOME": java_home,
    },
}

if config_path.exists():
    with open(config_path) as f:
        config = json.load(f)
else:
    config = {}

config.setdefault("mcpServers", {})
config["mcpServers"][server_name] = entry

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print(f"  Toegevoegd: mcpServers.{server_name}")
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
