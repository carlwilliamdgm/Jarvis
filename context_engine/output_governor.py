#context_engine/output_governor.py

"""
Gouverneur de Sortie (Output Governor / Anti-Dump) - Jalon 3.

Ce module intercepte et filtre la réponse finale avant qu'elle ne soit renvoyée
à l'utilisateur ou ajoutée à l'historique. Il assure que :
- Les dumps d'URLs brutes sont nettoyés ou condensés selon le profil
- Les scories techniques interdites sont épurées
- Le format de réponse respecte les préférences du profil utilisateur
"""

import re
from typing import Literal


def _detecter_dump_urls(texte: str) -> bool:
    """
    Détecte si le texte contient un dump d'URLs brutes.
    
    Considère comme dump s'il y a plus de 2 URLs longues listées à la suite.
    
    Args:
        texte: Le texte à analyser.
        
    Returns:
        True si un dump d'URLs est détecté, False sinon.
    """
    # Pattern pour détecter les URLs http/https
    pattern_url = r'https?://[^\s<>"{}|\\^`\[\]]{20,}'
    urls = re.findall(pattern_url, texte)
    
    # Si plus de 2 URLs longues, c'est un dump
    return len(urls) > 2


def _nettoyer_dump_urls(texte: str, mode_synthese: bool = True) -> str:
    """
    Nettoie ou condense les dumps d'URLs brutes.
    
    Si mode_synthese est True, transforme les URLs brutes en liens Markdown
    propres ou les supprime si trop nombreuses.
    
    Args:
        texte: Le texte contenant potentiellement des URLs brutes.
        mode_synthese: Si True, mode synthèse (condensation active).
        
    Returns:
        Le texte nettoyé.
    """
    lignes = texte.split('\n')
    lignes_nettoyees = []
    
    for ligne in lignes:
        # Détecter si la ligne est principalement une URL brute
        urls_dans_ligne = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]{20,}', ligne)
        
        if len(urls_dans_ligne) > 0 and len(ligne.strip()) < len(urls_dans_ligne[0]) + 10:
            # Ligne dominée par une URL brute
            if mode_synthese:
                # En mode synthèse, on peut soit formater proprement soit supprimer
                # Ici on supprime pour éviter le dump
                continue
            else:
                # En mode détaillé, on garde mais on formate proprement si possible
                lignes_nettoyees.append(ligne.strip())
        else:
            lignes_nettoyees.append(ligne)
    
    # Nettoyer les doubles sauts de ligne générés
    resultat = '\n'.join(lignes_nettoyees)
    resultat = re.sub(r'\n{3,}', '\n\n', resultat)
    
    return resultat.strip()


def _epurer_scories_techniques(texte: str) -> str:
    """
    Élimine les mentions administratives de bas niveau qui auraient fui d'un outil brut.
    
    Nettoie :
    - Codes d'erreur hexadécimaux (0x...)
    - Mentions "Exception: "
    - Mentions "CapabilityResult status="
    - Stack traces brutes
    
    Args:
        texte: Le texte à épurer.
        
    Returns:
        Le texte épuré des scories techniques.
    """
    lignes = texte.split('\n')
    lignes_epurees = []
    
    # Patterns de scories à éliminer
    patterns_scories = [
        r'CapabilityResult\s+status=',
        r'CapabilityStatus\.',
        r'0x[0-9a-fA-F]{8,}',  # Codes d'erreur hexadécimaux
        r'Traceback \(most recent call last\):',
        r'File "[^"]+", line \d+',
        r'^\s*at\s+[^:]+:\d+',  # Stack traces JavaScript/Python
    ]
    
    for ligne in lignes:
        ligne_epuree = ligne
        est_scorie = False
        
        # Vérifier si la ligne contient une scorie technique
        for pattern in patterns_scories:
            if re.search(pattern, ligne):
                est_scorie = True
                break
        
        # Si la ligne commence par "Exception: " ou similaire, c'est une scorie
        if re.match(r'^\s*(Exception|Error|Traceback)\s*:', ligne):
            est_scorie = True
        
        if not est_scorie:
            lignes_epurees.append(ligne)
    
    # Nettoyer les doubles sauts de ligne
    resultat = '\n'.join(lignes_epurees)
    resultat = re.sub(r'\n{3,}', '\n\n', resultat)
    
    return resultat.strip()


def _appliquer_concision(texte: str, concis: bool = True) -> str:
    """
    Applique la concision selon le profil utilisateur.
    
    Si concis est True, évite les répétitions inutiles et les redondances.
    
    Args:
        texte: Le texte à condenser.
        concis: Si True, applique la concision.
        
    Returns:
        Le texte éventuellement condensé.
    """
    if not concis:
        return texte
    
    lignes = texte.split('\n')
    lignes_uniques = []
    derniere_ligne = None
    
    for ligne in lignes:
        ligne_strip = ligne.strip()
        
        # Ignorer les lignes vides répétées
        if not ligne_strip:
            if derniere_ligne == "":
                continue
            lignes_uniques.append(ligne)
            derniere_ligne = ""
        # Ignorer les lignes identiques à la précédente
        elif ligne_strip == derniere_ligne:
            continue
        else:
            lignes_uniques.append(ligne)
            derniere_ligne = ligne_strip
    
    resultat = '\n'.join(lignes_uniques)
    resultat = re.sub(r'\n{3,}', '\n\n', resultat)
    
    return resultat.strip()


def gouverner_sortie(
    reponse: str,
    user_id: str | None = None,
) -> str:
    """
    Interception et filtrage de la réponse finale avant renvoi à l'utilisateur.
    
    Contrôles mécaniques :
    1. Règle Anti-Dump d'URLs brutes : détecte et nettoie les dumps d'URLs
       selon le format_prefere du profil utilisateur.
    2. Épuration des scories techniques : élimine les mentions administratives
       de bas niveau qui auraient fui d'un outil brut.
    3. Respect du format de réponse : applique la concision si le profil le demande.
    
    Args:
        reponse: La réponse brute à gouverner.
        user_id: Identifiant utilisateur optionnel pour charger le profil.
                 Si None, résolu dynamiquement via user_profile.resoudre_utilisateur_actif().
        
    Returns:
        La réponse gouvernée et assainie.
    """
    if not reponse or not reponse.strip():
        return reponse
    
    reponse_gouvernee = reponse
    
    # Charger le profil utilisateur pour connaître les préférences
    try:
        from context_engine.user_profile import charger_profil
        profil = charger_profil(user_id)
        
        style_cognitif = profil.get("style_cognitif", {})
        format_prefere = style_cognitif.get("format_prefere", "synthese")
        concis = style_cognitif.get("concis", True)
        
        mode_synthese = format_prefere == "synthese"
    except Exception:
        # En cas d'erreur de chargement du profil, utiliser des valeurs par défaut sécurisées
        mode_synthese = True
        concis = True
    
    # 1. Épuration des scories techniques (toujours active)
    reponse_gouvernee = _epurer_scories_techniques(reponse_gouvernee)
    
    # 2. Anti-Dump d'URLs brutes (conditionnel au profil)
    if _detecter_dump_urls(reponse_gouvernee):
        reponse_gouvernee = _nettoyer_dump_urls(reponse_gouvernee, mode_synthese=mode_synthese)
    
    # 3. Application de la concision (conditionnelle au profil)
    reponse_gouvernee = _appliquer_concision(reponse_gouvernee, concis=concis)
    
    return reponse_gouvernee
