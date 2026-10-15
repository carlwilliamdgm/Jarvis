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

from greatos_contracts import CapabilityExecution, CapabilityResult, CapabilityStatus


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
    "controler_multimedia": ("taskflow", "desktop.multimedia_control"),
    "manipuler_fenetre": ("taskflow", "desktop.window_control"),
    "regarder_ecran": ("taskflow", "desktop.vision_inspect"),
    "faire_briefing_quotidien": ("taskflow", "system.daily_briefing"),
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
    "statut_chiffrement": ("datashield", "security.crypto_status"),
    "chiffrer_valeur": ("datashield", "security.encrypt"),
    "dechiffrer_valeur": ("datashield", "security.decrypt"),
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
    # Ces fonctions sont exportées par leurs modules propriétaires, même si
    # leurs noms de capacité historiques restent préfixés taskflow.
    "consulter_etat_maison": ("core_intellect", "taskflow.consulter_etat_maison"),
    "inspecter_architecture_greatos": ("core_intellect", "taskflow.inspecter_architecture_greatos"),
    "consulter_historique_projet": ("core_intellect", "taskflow.consulter_historique_projet"),
    "arbitrer_priorite_taches": ("core_intellect", "taskflow.arbitrer_priorite_taches"),
    "capturer_contexte_quadridimensionnel": (
        "context_engine", "taskflow.capturer_contexte_quadridimensionnel",
    ),
    "charger_etat_gamification": ("progress_tracker", "taskflow.charger_etat_gamification"),
}

_KNOWN_READ_ONLY_TOOLS = {
    "lire_fichier", "lister_dossier", "rechercher_web", "analyser_page_web",
    "lister_objectifs", "stats_objectifs", "lister_snapshots_systeme",
    "obtenir_niveau_defcon", "statut_chiffrement", "lire_notes", "lire_contexte",
    "lire_preferences", "lire_journal_agents", "lire_traces_capacites",
    "consulter_etat_maison", "inspecter_architecture_greatos",
    "consulter_historique_projet", "arbitrer_priorite_taches",
    "capturer_contexte_quadridimensionnel", "charger_etat_gamification",
    "faire_briefing_quotidien",
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


def _execute_capability(
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
            error_category="capacite_manquante",
        )
    if arguments is not None and not isinstance(arguments, dict):
        return CapabilityResult(
            capability=descriptor.name,
            status=CapabilityStatus.FAILED,
            message=f"Arguments invalides pour {descriptor.legacy_tool}.",
            error_category="erreur_technique_outil",
        )

    try:
        from interface_morphique.server import WINDOWS_SESSION_LOCKED
        from datashield.profile_gate import profile_execution_gate
        if WINDOWS_SESSION_LOCKED.is_set() and not profile_execution_gate.current_action_admitted:
            return CapabilityResult(
                capability=descriptor.name,
                status=CapabilityStatus.FAILED,
                message="Capacité refusée : le profil GreatOS est verrouillé.",
                error_category="profil_verrouille",
            )
    except ImportError:
        # Keep the dispatcher usable by isolated module tools without loading
        # the HTTP server; production calls resolve the shared session gate.
        pass

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
        if isinstance(raw_result, CapabilityExecution):
            return CapabilityResult(
                capability=descriptor.name,
                status=raw_result.status,
                message=raw_result.message,
                data={
                    "owner": descriptor.owner,
                    "legacy_tool": descriptor.legacy_tool,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                    **raw_result.data,
                },
                error_category=raw_result.error_category,
                compensator=raw_result.compensator,
                effect_status=raw_result.effect_status,
            )

        if (
            descriptor.legacy_tool == "executer_workflow_preconfigure"
            and isinstance(raw_result, dict)
            and isinstance(raw_result.get("succes"), bool)
        ):
            succeeded = raw_result["succes"]
            details = raw_result.get("etapes", [])
            failed_steps = [
                str(item.get("etape", "étape"))
                for item in details if isinstance(item, dict) and item.get("statut") != "ok"
            ] if isinstance(details, list) else []
            message = str(raw_result.get("workflow", descriptor.legacy_tool))
            if failed_steps:
                message += " · échec : " + ", ".join(failed_steps)
            effects = raw_result.get("effets_non_annules", [])
            rollback = raw_result.get("rollback", {})
            if not succeeded and isinstance(rollback, dict):
                message += f" · rollback {rollback.get('statut', 'inconnu')}"
            if effects:
                effect_names = [
                    str(item.get("etape", "effet"))
                    for item in effects if isinstance(item, dict)
                ] if isinstance(effects, list) else []
                if effect_names:
                    message += " · effets non annulés : " + ", ".join(effect_names)
            return CapabilityResult(
                capability=descriptor.name,
                status=CapabilityStatus.SUCCESS if succeeded else CapabilityStatus.FAILED,
                message=message,
                data={
                    "owner": descriptor.owner,
                    "legacy_tool": descriptor.legacy_tool,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                    "workflow_rollback": rollback,
                    "uncompensated_effects": effects if isinstance(effects, list) else [],
                },
                error_category=None if succeeded else "workflow_failed",
                effect_status="none" if succeeded or not effects else "partial",
            )

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
            effect_status="none" if descriptor.legacy_tool in _KNOWN_READ_ONLY_TOOLS else "unknown",
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


def execute_capability(
    registry: dict[str, Callable], name: str, arguments: dict | None = None,
) -> CapabilityResult:
    """Atomically admit a capability and retain its lease through completion."""
    descriptor = resolve_capability(registry, name)
    if descriptor is None or (arguments is not None and not isinstance(arguments, dict)):
        return _execute_capability(registry, name, arguments)

    from datashield.profile_gate import profile_execution_gate
    with profile_execution_gate.action_step() as action_admitted:
        if not action_admitted:
            return CapabilityResult(
                capability=descriptor.name,
                status=CapabilityStatus.FAILED,
                message="Capacité refusée : le profil GreatOS est verrouillé.",
                error_category="profil_verrouille",
            )
        with profile_execution_gate.admit() as admitted:
            if not admitted:
                return CapabilityResult(
                    capability=descriptor.name,
                    status=CapabilityStatus.FAILED,
                    message="Capacité refusée : le profil GreatOS est verrouillé.",
                    error_category="profil_verrouille",
                )
            return _execute_capability(registry, name, arguments)


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

