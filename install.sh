#!/usr/bin/env bash
# ==============================================================================
# GreatOS - Script d'Installation Universel (Linux / macOS / WSL)
# ==============================================================================
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================================="
echo "         INSTALLATION & INITIALISATION DE GREATOS         "
echo "=========================================================="
echo "Emplacement : $PROJECT_ROOT"
echo "Utilisateur : $(whoami)"

# 1. Vérification de Python 3.10+
if ! command -v python3 &> /dev/null; then
    echo "[ERREUR] python3 n'a pas été détecté sur ce système."
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[OK] Python $PY_VERSION détecté."

# 2. Création de l'environnement virtuel .venv
VENV_DIR="$PROJECT_ROOT/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "Création de l'environnement virtuel..."
    python3 -m venv "$VENV_DIR"
    echo "[OK] Environnement virtuel créé."
else
    echo "[OK] Environnement virtuel existant détecté."
fi

# 3. Installation des dépendances
echo "[3/4] Installation des dépendances (requirements.txt)..."
"$VENV_PYTHON" -m pip install --upgrade pip --quiet
"$VENV_PYTHON" -m pip install -r "$PROJECT_ROOT/requirements.txt" --quiet
echo "[OK] Dépendances installées avec succès."

# 4. Génération des clés de sécurité souveraines (DataShield AES-256)
echo "[4/4] Initialisation de la sécurité DataShield..."
"$VENV_PYTHON" "$PROJECT_ROOT/scripts/setup_production.py"

echo "=========================================================="
echo "   🎉 Félicitations ! GreatOS est installé avec succès !  "
echo "=========================================================="
echo "• Pour démarrer : $VENV_PYTHON -m uvicorn interface_morphique.server:app --port 8000"
echo "• Interface Web  : http://127.0.0.1:8000/web/"
