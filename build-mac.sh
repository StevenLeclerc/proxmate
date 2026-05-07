#!/bin/bash
# build-mac.sh - Build ProxMate pour macOS et l'installer dans /usr/local/bin/
#
# Usage: ./build-mac.sh
#
# Ce script fait l'équivalent de la CI GitHub pour macOS:
# 1. Crée un environnement virtuel temporaire
# 2. Installe les dépendances
# 3. Build le binaire avec PyInstaller
# 4. Supprime l'attribut de quarantaine macOS
# 5. Installe le binaire dans /usr/local/bin/

set -e  # Arrêter en cas d'erreur

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║           🔨 Build ProxMate pour macOS                     ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
echo

# Vérifier qu'on est sur macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo -e "${RED}❌ Ce script est uniquement pour macOS${NC}"
    exit 1
fi

# Vérifier Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3 n'est pas installé${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
echo -e "${GREEN}✓${NC} Python: ${PYTHON_VERSION}"

# Répertoire du script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${GREEN}✓${NC} Répertoire: ${SCRIPT_DIR}"
echo

# Étape 1: Créer un environnement virtuel temporaire pour le build
echo -e "${YELLOW}📦 Étape 1/5: Création de l'environnement de build...${NC}"
BUILD_VENV=".build-venv"
if [ -d "$BUILD_VENV" ]; then
    rm -rf "$BUILD_VENV"
fi
python3 -m venv "$BUILD_VENV"
source "$BUILD_VENV/bin/activate"
echo -e "${GREEN}✓${NC} Environnement virtuel créé"

# Étape 2: Installer les dépendances
echo
echo -e "${YELLOW}📦 Étape 2/5: Installation des dépendances...${NC}"
pip install --upgrade pip --quiet
pip install pyinstaller --quiet
pip install -e . --quiet
echo -e "${GREEN}✓${NC} Dépendances installées"

# Étape 3: Build avec PyInstaller
echo
echo -e "${YELLOW}🔨 Étape 3/5: Build du binaire avec PyInstaller...${NC}"
rm -rf dist build *.spec 2>/dev/null || true
pyinstaller --onedir --name proxmate --clean --collect-all rich --collect-all proxmoxer proxmate/cli/main.py --noconfirm 2>&1 | grep -E "(Building|INFO|WARNING|ERROR)" || true
echo -e "${GREEN}✓${NC} Build terminé"

# Vérifier que le binaire existe
if [ ! -f "dist/proxmate/proxmate" ]; then
    echo -e "${RED}❌ Le binaire n'a pas été créé${NC}"
    deactivate
    exit 1
fi

# Étape 4: Supprimer l'attribut de quarantaine macOS
echo
echo -e "${YELLOW}🔓 Étape 4/5: Suppression de l'attribut de quarantaine...${NC}"
xattr -rd com.apple.quarantine dist/proxmate/ 2>/dev/null || true
chmod +x dist/proxmate/proxmate
echo -e "${GREEN}✓${NC} Attribut de quarantaine supprimé"

# Étape 5: Installer dans /usr/local/bin/
echo
echo -e "${YELLOW}📥 Étape 5/5: Installation dans /usr/local/bin/...${NC}"

# Créer le répertoire d'installation
INSTALL_DIR="/usr/local/bin/proxmate-app"

# Supprimer l'ancienne installation si elle existe
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${CYAN}   Suppression de l'ancienne installation...${NC}"
    sudo rm -rf "$INSTALL_DIR"
fi
if [ -L "/usr/local/bin/proxmate" ] || [ -f "/usr/local/bin/proxmate" ]; then
    sudo rm -f "/usr/local/bin/proxmate"
fi

# Copier le dossier complet (PyInstaller --onedir crée un dossier avec les libs)
sudo cp -R dist/proxmate "$INSTALL_DIR"
sudo chmod +x "$INSTALL_DIR/proxmate"

# Créer un lien symbolique
sudo ln -sf "$INSTALL_DIR/proxmate" /usr/local/bin/proxmate

echo -e "${GREEN}✓${NC} Installé dans /usr/local/bin/proxmate"

# Nettoyage
echo
echo -e "${CYAN}🧹 Nettoyage...${NC}"
deactivate
rm -rf "$BUILD_VENV"
rm -rf dist build *.spec 2>/dev/null || true
echo -e "${GREEN}✓${NC} Nettoyage terminé"

# Vérification
echo
echo -e "${CYAN}════════════════════════════════════════════════════════════${NC}"
if command -v proxmate &> /dev/null; then
    VERSION=$(proxmate version 2>/dev/null || echo "?")
    echo -e "${GREEN}✅ ProxMate installé avec succès!${NC}"
    echo -e "   Version: ${VERSION}"
    echo -e "   Chemin:  $(which proxmate)"
else
    echo -e "${RED}❌ L'installation a échoué${NC}"
    exit 1
fi
echo -e "${CYAN}════════════════════════════════════════════════════════════${NC}"
echo
echo -e "Utilisez ${CYAN}proxmate --help${NC} pour commencer."

