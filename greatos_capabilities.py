"""Registre noyau des capacités détenues par les modules GreatOS.

`taskflow.tools.OUTILS` reste une façade de compatibilité pour Jarvis et les
prompts existants. Ce registre attribue néanmoins chaque entrée à son module
propriétaire et lui donne un nom canonique stable. Il évite de confondre la
façade d'orchestration avec la propriété métier pendant la migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable

from greatos_contracts import CapabilityResult, CapabilityStatus


@dataclass(frozen=True)
class CapabilityDescriptor:
    name: str
    owner: str
    legacy_tool: str
    description: str = ""


_EXPLICIT_CAPABILITIES = {
    # TaskFlow : actions et workflows sur la machine ou le web.
    "creer_dossier": ("taskflow", "filesystem.create_directory"),
    "creer_fichier": ("taskflow", "filesystem.create_file"),
    "lire_fichier": ("taskflow", "filesystem.read"),
    "lister_dossier": ("taskflow", "filesystem.list"),
    "supprimer": ("taskflow", "filesystem.delete"),
    "executer_commande": ("taskflow", "system.execute_command"),
    "executer_powershell": ("taskflow", "system.execute_powershell"),
    "organiser_dossier": ("taskflow", "filesystem.organize"),
    "analyser_organisation": ("taskflow", "filesystem.analyze_organization"),
    "rechercher_web": ("taskflow", "web.search"),
    "analyser_page_web": ("taskflow", "web.analyze_page"),
    "rechercher_et_analyser": ("taskflow", "web.search_and_analyze"),
    "naviguer_vers": ("taskflow", "browser.navigate"),
    "cliquer_element": ("taskflow", "browser.click"),
    "remplir_formulaire": ("taskflow", "browser.fill"),
    # Context Engine : mémoire, observations et contexte de continuité.
    "noter": ("context_engine", "memory.note"),
    "lire_notes": ("context_engine", "memory.read_notes"),
    "memoriser_contexte": ("context_engine", "context.remember"),
    "lire_contexte": ("context_engine", "context.read"),
    "oublier_contexte": ("context_engine", "context.forget"),
    "memoriser_preference": ("context_engine", "memory.remember_preference"),
    "lire_preferences": ("context_engine", "memory.read_preferences"),
    "oublier_preference": ("context_engine", "memory.forget_preference"),
    "enregistrer_echange": ("context_engine", "memory.record_conversation"),
    "lire_journal_agents": ("context_engine", "learning.read_agent_sessions"),
    "lire_traces_capacites": ("context_engine", "context.read_traces"),
    "rechercher": ("context_engine", "memory.semantic_search"),
    "analyser_patterns": ("context_engine", "context.analyze_patterns"),
    "rapport_systeme": ("context_engine", "system.report"),
    "tendances_systeme": ("context_engine", "system.trends"),
    # Modules dont les façades sont encore exposées par TaskFlow.
    "obtenir_niveau_defcon": ("datashield", "security.get_defcon"),
    "changer_niveau_defcon": ("datashield", "security.set_defcon"),
    "creer_objectif": ("progress_tracker", "goals.create"),
    "lister_objectifs": ("progress_tracker", "goals.list"),
    "mettre_a_jour_objectif": ("progress_tracker", "goals.update"),
    "stats_objectifs": ("progress_tracker", "goals.statistics"),
    "creer_snapshot_systeme": ("syncsphere", "snapshots.create"),
    "lister_snapshots_systeme": ("syncsphere", "snapshots.list"),
    "demarrer_overlay_navigation": ("interface_morphique", "interface.browser_overlay.start"),
    "arreter_overlay_navigation": ("interface_morphique", "interface.browser_overlay.stop"),
    "terminer_tache": ("jarvis", "orchestration.complete_task"),
    "lire_capacites": ("core_intellect", "capabilities.describe"),
}


def owner_for(legacy_tool: str) -> tuple[str, str]:
    """Retourne le module souverain et le nom canonique d'une façade historique."""
    if legacy_tool in _EXPLICIT_CAPABILITIES:
        return _EXPLICIT_CAPABILITIES[legacy_tool]
    # Les outils non encore migrés sont des automatisations/exécutions : leur
    # propriété temporaire reste TaskFlow, jamais la façade Jarvis.
    return "taskflow", f"taskflow.{legacy_tool}"


def list_capabilities(registry: dict[str, Callable]) -> list[CapabilityDescriptor]:
    return [
        CapabilityDescriptor(name=owner_for(name)[1], owner=owner_for(name)[0], legacy_tool=name)
        for name in sorted(registry)
    ]


def resolve_capability(registry: dict[str, Callable], name: str) -> CapabilityDescriptor | None:
    """Résout un nom canonique ou un alias historique sans exécuter l'action."""
    for descriptor in list_capabilities(registry):
        if name in {descriptor.name, descriptor.legacy_tool}:
            return descriptor
    return None


def execute_capability(
    registry: dict[str, Callable], name: str, arguments: dict | None = None,
) -> CapabilityResult:
    """Exécute une capacité résolue et retourne toujours un résultat structuré.

    Le dispatcher reste neutre : DataShield garde la politique et le module
    propriétaire garde la logique métier. Pendant la transition, le registre
    historique apporte les adaptateurs d'exécution.
    """
    descriptor = resolve_capability(registry, name)
    if descriptor is None:
        return CapabilityResult(
            capability=name,
            status=CapabilityStatus.FAILED,
            message=f"Outil inconnu : {name}",
            error_category="erreur_technique_outil",
        )
    if arguments is not None and not isinstance(arguments, dict):
        return CapabilityResult(
            capability=descriptor.name,
            status=CapabilityStatus.FAILED,
            message=f"Arguments invalides pour {descriptor.legacy_tool}.",
            error_category="erreur_technique_outil",
        )

    started = perf_counter()
    try:
        try:
            raw_result = registry[descriptor.legacy_tool](**(arguments or {}))
        except TypeError as exc:
            # Compatibilité transitoire pour les extensions historiques qui
            # n'acceptent que des arguments positionnels. On ne réessaie pas
            # un TypeError interne à l'outil, pour éviter de dupliquer un effet.
            if "unexpected keyword argument" not in str(exc):
                raise
            raw_result = registry[descriptor.legacy_tool](*(arguments or {}).values())
        message = str(raw_result)
        error_category = getattr(raw_result, "categorie_erreur", None)
        if getattr(raw_result, "erreur", False):
            if error_category in {"defcon_blocked", "securite_bloquee"}:
                status = CapabilityStatus.DENIED
            elif error_category in {"action_refusee_par_confirmation", "confirmation_refusee"}:
                status = CapabilityStatus.CANCELLED
            else:
                status = CapabilityStatus.FAILED
        elif message.startswith("Timeout"):
            status = CapabilityStatus.TIMEOUT
        else:
            status = CapabilityStatus.SUCCESS
        return CapabilityResult(
            capability=descriptor.name,
            status=status,
            message=message,
            data={
                "owner": descriptor.owner,
                "legacy_tool": descriptor.legacy_tool,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
            error_category=error_category,
        )
    except TypeError as exc:
        message = f"ERREUR TECHNIQUE arguments {descriptor.legacy_tool} : {exc}"
    except Exception as exc:
        message = f"Erreur outil {descriptor.legacy_tool} : {exc}"
    return CapabilityResult(
        capability=descriptor.name,
        status=CapabilityStatus.FAILED,
        message=message,
        data={
            "owner": descriptor.owner,
            "legacy_tool": descriptor.legacy_tool,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
        },
        error_category="erreur_technique_outil",
    )


class LegacyToolRegistry(dict):
    """Adaptateur explicite de compatibilité versionnée pour le catalogue d'outils historiques.

    Remplace le dictionnaire anonyme de fonctions par une structure typée et traçable,
    garantissant la rétrocompatibilité (mapping, clés, introspection) tout en exposant
    explicitement la délégation vers le dispatcher de capacités GreatOS.
    """

    def __init__(self, tools_dict: dict[str, Callable] | None = None):
        super().__init__(tools_dict or {})

    def execute(self, capability: str, arguments: dict | None = None) -> CapabilityResult:
        """Exécute une capacité via le dispatcher central souverain."""
        return execute_capability(self, capability, arguments)

    def resolve(self, name: str) -> CapabilityDescriptor | None:
        """Résout un descripteur de capacité souverain depuis ce registre."""
        return resolve_capability(self, name)

    def list_descriptors(self) -> list[CapabilityDescriptor]:
        """Retourne la liste des descripteurs de capacités connus pour ce registre."""
        return list_capabilities(self)

    def __repr__(self) -> str:
        return f"<LegacyToolRegistry: {len(self)} tools registered>"

