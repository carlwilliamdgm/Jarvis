# Tests Manuels

Ce dossier contient des tests manuels qui nécessitent une intervention humaine pour vérifier le comportement visuel ou interactif.

## Tests disponibles

### test_overlay_direct.py
Test direct de l'overlay vocal sans passer par uvicorn. Simule les transitions d'état automatiquement.

**Exécution :**
`powershell
cd C:\Users\Carl\Jarvis
python tests\manual\test_overlay_direct.py
`

### test_overlay_manuel.py  
Test manuel des transitions d'état pour l'overlay. Nécessite une application ouverte pour vérifier le comportement visuel.

**Exécution :**
`powershell
cd C:\Users\Carl\Jarvis
python tests\manual\test_overlay_manuel.py
`

## Notes

- Ces tests ne font pas partie de la suite de tests automatiques (pytest)
- Ils servent à vérifier manuellement le comportement visuel et interactif
- Assurez-vous que l'overlay vocal est fonctionnel avant d'exécuter ces tests
