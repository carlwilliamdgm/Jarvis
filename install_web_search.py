#!/usr/bin/env python3
"""
Script d'installation pour duckduckgo-search (solution gratuite de recherche web pour Jarvis)

Ce script tente d'installer la bibliothèque duckduckgo-search de manière sécurisée.
"""

import subprocess
import sys
import os

def install_duckduckgo_search():
    """Tente d'installer duckduckgo-search avec différentes méthodes."""
    
    print("🔍 Installation de duckduckgo-search pour Jarvis...")
    print("Cette bibliothèque permet une recherche web GRATUITE sans carte de crédit.\n")
    
    methods = [
        # Méthode 1: Installation standard
        ["pip", "install", "duckduckgo-search"],
        # Méthode 2: Installation utilisateur (évite les problèmes de permissions)
        ["pip", "install", "--user", "duckduckgo-search"],
        # Méthode 3: Avec module Python explicite
        [sys.executable, "-m", "pip", "install", "--user", "duckduckgo-search"],
    ]
    
    for i, method in enumerate(methods, 1):
        print(f"📝 Tentative {i}/{len(methods)}: {' '.join(method)}")
        
        try:
            result = subprocess.run(
                method,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode == 0:
                print("✅ Installation réussie !")
                print(f"📋 Sortie: {result.stdout[:200]}")
                
                # Vérifier que l'installation fonctionne
                try:
                    import duckduckgo_search
                    print("✅ Bibliothèque importée avec succès !")
                    print("\n🎉 duckduckgo-search est maintenant installé pour Jarvis !")
                    print("   Redémarrez Jarvis pour que les changements prennent effet.")
                    return True
                except ImportError as e:
                    print(f"⚠️ Installation réussie mais import échoué: {e}")
                    continue
            else:
                print(f"❌ Échec: {result.stderr[:200]}")
                
        except subprocess.TimeoutExpired:
            print("⏱️ Timeout - installation trop longue")
        except Exception as e:
            print(f"❌ Erreur: {e}")
        
        print()
    
    print("❌ Toutes les méthodes d'installation automatique ont échoué.")
    print("\n📚 Installation manuelle suggérée :")
    print("1. Créez un environnement virtuel :")
    print("   python -m venv venv")
    print("   venv\\Scripts\\activate  (Windows)")
    print("   source venv/bin/activate  (Linux/Mac)")
    print("\n2. Installez la bibliothèque :")
    print("   pip install duckduckgo-search")
    print("\n3. Lancez Jarvis depuis l'environnement virtuel")
    
    return False

if __name__ == "__main__":
    success = install_duckduckgo_search()
    sys.exit(0 if success else 1)
