# Continuité d apprentissage GreatOS

Chaque agent qui analyse, modifie ou valide ce dépôt doit laisser un passage de
relais durable à GreatOS avant de terminer sa session. La mémoire de l'agent,
le statut Git et les logs techniques seuls ne sont pas des sources de suivi
suffisantes.

## Procédure obligatoire

À la fin de chaque session significative, exécuter depuis la racine :

```powershell
python scripts/log_agent_session.py --agent "NomAgent" --status completed --summary "Résultat concret" --changes "fichier ou comportement" --verification "test ou contrôle" --learnings "connaissance réutilisable" --next-steps "suite actionnable"
```

Les statuts admis sont `completed`, `in_progress`, `blocked` et `review`.
Ne jamais inscrire de secrets, tokens, données personnelles ou contenu de clés
API dans le journal.

## Source de vérité

- `learning/agent_sessions.jsonl` : journal structuré, append-only, lisible par GreatOS.
- `SUIVI_PROJET.md` : vue humaine régénérée automatiquement à partir du journal.
- `context_engine/agent_learning.py` : API Python à utiliser par GreatOS et ses intégrations.

Un agent qui reprend le projet doit lire `SUIVI_PROJET.md`, puis consulter les
dernières entrées JSONL pertinentes avant de tirer des conclusions.
