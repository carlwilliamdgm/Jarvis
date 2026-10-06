# core_intellect/intent_router.py

"""Intent Router - Routage sémantique et optimisation des flux pour Core Intellect.

Permet à Core Intellect d'adapter son raisonnement, de choisir la bonne température
et d'éviter d'injecter l'inventaire complet des 75+ capacités d'outils quand la
demande relève d'une simple conversation ou d'un diagnostic direct.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class IntentCategory(str, Enum):
    CONVERSATION = "conversation"
    ACTION = "action"
    PLANIFICATION = "planification"
    DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True)
class IntentRoute:
    category: IntentCategory
    needs_tool_signatures: bool
    temperature: float
    confidence: float
    reason: str


# Mots-clés et expressions conversationnelles pures (pas d'outil nécessaire)
_SALUTATIONS = {
    "bonjour", "salut", "hello", "bonsoir", "coucou", "hey", "hi", "ça va",
    "ca va", "comment vas-tu", "comment tu vas", "qui es-tu", "qui est tu",
    "présente-toi", "presente toi", "merci", "parfait", "ok", "super",
}

_QUESTIONS_CONVERSATIONNELLES = [
    r"(?i)^(qui|qu'est-ce que|qu'est ce que|pourquoi|comment|raconte|explique|dis-moi)\b",
    r"(?i)\b(blague|poème|histoire|citation|philosophie)\b",
    r"(?i)\b(sens de la vie|théorie|avis sur)\b",
]

# Verbes et motifs déclencheurs d'actions concrètes
_MOTS_ACTION = [
    r"(?i)\b(exécute|execute|lance|démarre|demarre|ouvre|ferme|kill|arrête|arrete)\b",
    r"(?i)\b(crée|creer|créer|supprime|efface|renomme|déplace|deplace|copie)\b",
    r"(?i)\b(liste|lis|affiche le contenu|recherche sur le web|scrape|cherche)\b",
    r"(?i)\b(note|ajoute une note|mémorise|memorise|rappelle-moi|oublie)\b",
    r"(?i)\b(nettoie|vide la corbeille|vide les temp|optimise le stockage)\b",
    r"(?i)\b(snapshot|sauvegarde|restaure|chiffre|déchiffre|dechiffre)\b",
    r"(?i)\b(powershell|terminal|cmd|ping|curl|git)\b",
    r"(?i)\b(regarde|vois|écran|ecran|capture|musique|volume|pause|play|fenêtre|fenetre|redimensionne)\b",
]


# Motifs de planification complexe
_MOTS_PLANIFICATION = [
    r"(?i)\b(planifie|organise un plan|élabore une stratégie|décompose|graphe d'étapes)\b",
    r"(?i)\b(prépare le projet|feuille de route|roadmap)\b",
]

# Motifs de diagnostic & introspection système
_MOTS_DIAGNOSTIC = [
    r"(?i)\b(statut|état du système|etat systeme|niveau defcon|defcon|espace disque)\b",
    r"(?i)\b(cpu|ram|processus|charge système|santé du système|audit)\b",
    r"(?i)\b(état de la maison|etat de la maison|qui tourne|layout actif|quoi de neuf)\b",
    r"(?i)\b(architecture|modules greatos|historique du projet|dernières sessions|dernieres sessions)\b",
]


def router_intention(message: str, historique_recent: list[dict] | None = None) -> IntentRoute:
    """Analyse la requête utilisateur et détermine la route cognitive optimale.

    Permet d'économiser de la latence, des tokens et d'éviter les hallucinations
    d'outils lors des requêtes purement conversationnelles.
    """
    texte = (message or "").strip().lower()

    if not texte:
        return IntentRoute(
            category=IntentCategory.CONVERSATION,
            needs_tool_signatures=False,
            temperature=0.7,
            confidence=1.0,
            reason="Message vide, repli conversationnel",
        )

    # 1. Vérification salutations / acquittements directs
    tokens = re.findall(r"\w+", texte)
    premier_mot = tokens[0] if tokens else ""
    mots_salutation_purs = {"bonjour", "salut", "hello", "bonsoir", "coucou", "hey", "hi", "merci", "parfait", "ok", "super"}
    interlocuteur = {"jarvis", "sir", "ami", "ia", "assistant", "comment", "vas", "tu", "allez", "vous", "ca", "va"}
    est_salutation = (
        texte in _SALUTATIONS
        or (premier_mot in mots_salutation_purs and set(tokens[1:]).issubset(interlocuteur))
        or any(texte.startswith(s) and len(tokens) <= 4 for s in _SALUTATIONS)
        or any(s in texte for s in ("comment vas-tu", "comment tu vas", "ça va", "ca va"))
    )
    if est_salutation:
        # Vérifier qu'il n'y a pas un verbe d'action accolé (ex: "salut, supprime mon dossier")
        if not any(re.search(p, texte) for p in _MOTS_ACTION):
            return IntentRoute(
                category=IntentCategory.CONVERSATION,
                needs_tool_signatures=False,
                temperature=0.7,
                confidence=0.95,
                reason="Salutation ou acquittement pur",
            )

    # 2. Vérification planification explicite
    for pattern in _MOTS_PLANIFICATION:
        if re.search(pattern, texte):
            return IntentRoute(
                category=IntentCategory.PLANIFICATION,
                needs_tool_signatures=True,
                temperature=0.2,
                confidence=0.9,
                reason=f"Détection de motif de planification ({pattern})",
            )

    # 3. Vérification actions système
    for pattern in _MOTS_ACTION:
        if re.search(pattern, texte):
            return IntentRoute(
                category=IntentCategory.ACTION,
                needs_tool_signatures=True,
                temperature=0.1,
                confidence=0.9,
                reason=f"Détection de verbe d'action ({pattern})",
            )

    # 4. Vérification diagnostic
    for pattern in _MOTS_DIAGNOSTIC:
        if re.search(pattern, texte):
            return IntentRoute(
                category=IntentCategory.DIAGNOSTIC,
                needs_tool_signatures=True,
                temperature=0.2,
                confidence=0.85,
                reason="Demande de diagnostic ou statut",
            )

    # 5. Détection questions conversationnelles pures
    for pattern in _QUESTIONS_CONVERSATIONNELLES:
        if re.search(pattern, texte):
            # Si aucune action n'est demandée
            if not any(re.search(p, texte) for p in _MOTS_ACTION):
                return IntentRoute(
                    category=IntentCategory.CONVERSATION,
                    needs_tool_signatures=False,
                    temperature=0.7,
                    confidence=0.8,
                    reason="Question explicative ou conversationnelle",
                )

    # Par défaut : besoin des signatures d'outils par précaution (mode mixte)
    return IntentRoute(
        category=IntentCategory.CONVERSATION,
        needs_tool_signatures=True,
        temperature=0.5,
        confidence=0.6,
        reason="Intention indéterminée, chargement sécuritaire de l'inventaire",
    )
