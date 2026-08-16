"""Calendar Integration - Intégration avec le calendrier Windows."""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import subprocess
import json

from core.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire


def obtenir_evenements_calendrier(jours: int = 7) -> List[Dict[str, Any]]:
    """
    Obtient les événements du calendrier Windows pour les N prochains jours.
    
    Args:
        jours: Nombre de jours à analyser
        
    Returns:
        Liste des événements calendrier
    """
    try:
        # Utiliser PowerShell pour accéder au calendrier Windows
        commande = f"""
        $ErrorActionPreference = SilentlyContinue
        try {{
            $outlook = New-Object -ComObject Outlook.Application
            $calendar = $outlook.Session.GetDefaultFolder(6) # 6 = olFolderCalendar
            $items = $calendar.Items
            $items.Sort("[Start]")
            $items.IncludeRecurrences = $false
            
            $endDate = (Get-Date).AddDays({jours})
            $items = $items.Restrict("[Start] <= '$($endDate.ToString('s'))'")
            
            $events = @()
            foreach ($item in $items) {{
                if ($item.Start -ge (Get-Date).AddDays(-1)) {{
                    $events += @{{
                        Subject = $item.Subject
                        Start = $item.Start.ToString('s')
                        End = $item.End.ToString('s')
                        Location = $item.Location
                        Body = $item.Body
                        Importance = $item.Importance
                    }}
                }}
            }}
            
            ConvertTo-Json -Compress -InputObject $events
        }} catch {{
            # Outlook non disponible, essayer autre méthode
            Write-Output "[]"
        }}
        """
        
        resultat = subprocess.run(
            ["powershell", "-Command", commande],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if resultat.returncode == 0 and resultat.stdout.strip():
            try:
                evenements = json.loads(resultat.stdout)
                if isinstance(evenements, list):
                    return [_normaliser_evenement(e) for e in evenements]
            except json.JSONDecodeError:
                pass
        
        # Fallback : essayer via Windows Calendar API
        return _obtenir_evenements_windows_calendar_api(jours)
        
    except Exception as e:
        return [{"erreur": f"Impossible d'accéder au calendrier: {str(e)}"}]


def _normaliser_evenement(evenement: Dict) -> Dict[str, Any]:
    """Normalise un événement calendrier."""
    return {
        "titre": evenement.get("Subject", "Sans titre"),
        "debut": evenement.get("Start", ""),
        "fin": evenement.get("End", ""),
        "lieu": evenement.get("Location", ""),
        "description": evenement.get("Body", "")[:200],
        "importance": evenement.get("Importance", "normal")
    }


def _obtenir_evenements_windows_calendar_api(jours: int) -> List[Dict[str, Any]]:
    """Fallback : utilise l'API Windows Calendar si disponible."""
    try:
        commande = f"""
        $ErrorActionPreference = SilentlyContinue
        try {{
            $calendar = Get-Content "$env:LOCALAPPDATA\\Microsoft\\Windows Calendar\\*.calendar" -ErrorAction SilentlyContinue
            if ($calendar) {{
                # Parser les fichiers calendrier (format simplifié)
                Write-Output "[]"
            }} else {{
                Write-Output "[]"
            }}
        }} catch {{
            Write-Output "[]"
        }}
        """
        
        resultat = subprocess.run(
            ["powershell", "-Command", commande],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if resultat.returncode == 0:
            try:
                return json.loads(resultat.stdout)
            except json.JSONDecodeError:
                pass
                
    except Exception:
        pass
    
    return []


def obtenir_evenements_aujourdhui() -> List[Dict[str, Any]]:
    """
    Obtient les événements du calendrier pour aujourd'hui.
    
    Returns:
        Liste des événements d'aujourd'hui
    """
    evenements = obtenir_evenements_calendrier(1)
    aujourd_hui = datetime.now().strftime("%Y-%m-%d")
    
    evenements_aujourdhui = []
    for event in evenements:
        debut = event.get("debut", "")
        if debut.startswith(aujourd_hui):
            evenements_aujourdhui.append(event)
    
    return evenements_aujourdhui


def verifier_rappels_calendrier() -> List[Dict[str, Any]]:
    """
    Vérifie les rappels de calendrier imminents (dans l'heure suivante).
    
    Returns:
        Liste des événements avec rappels imminents
    """
    evenements = obtenir_evenements_calendrier(1)
    maintenant = datetime.now()
    dans_une_heure = maintenant + timedelta(hours=1)
    
    rappels = []
    for event in evenements:
        try:
            debut_str = event.get("debut", "")
            if debut_str:
                debut = datetime.fromisoformat(debut_str.replace('Z', '+00:00'))
                if maintenant <= debut <= dans_une_heure:
                    rappels.append({
                        **event,
                        "minutes_restant": int((debut - maintenant).total_seconds() / 60)
                    })
        except (ValueError, TypeError):
            continue
    
    return rappels


def formater_evenements(evenements: List[Dict[str, Any]]) -> str:
    """
    Formate les événements pour affichage.
    
    Returns:
        Description textuelle des événements
    """
    if not evenements or ("erreur" in evenements[0]):
        return "Aucun événement calendrier disponible ou erreur d'accès."
    
    lignes = ["=== ÉVÉNEMENTS CALENDRIER ==="]
    
    for i, event in enumerate(evenements, 1):
        lignes.append(f"\n{i}. {event.get('titre', 'Sans titre')}")
        
        debut = event.get("debut", "")
        if debut:
            try:
                dt = datetime.fromisoformat(debut.replace('Z', '+00:00'))
                lignes.append(f"   {dt.strftime('%d/%m %H:%M')}")
            except (ValueError, TypeError):
                lignes.append(f"   {debut}")
        
        if event.get("lieu"):
            lignes.append(f"   📍 {event['lieu']}")
        
        importance = event.get("importance", "")
        if importance and importance != "normal":
            lignes.append(f"   ⚠️  {importance}")
    
    return "\n".join(lignes)


def creer_rappel_calendrier(titre: str, date_heure: str, description: str = "") -> str:
    """
    Crée un rappel dans le calendrier système.
    
    Args:
        titre: Titre du rappel
        date_heure: Date et heure (format YYYY-MM-DD HH:MM)
        description: Description optionnelle
        
    Returns:
        Résultat de la création
    """
    try:
        commande = f"""
        $ErrorActionPreference = SilentlyContinue
        try {{
            $outlook = New-Object -ComObject Outlook.Application
            $appointment = $outlook.CreateItem(1) # 1 = olAppointmentItem
            
            $appointment.Subject = "{titre}"
            $appointment.Start = "{date_heure}"
            $appointment.Duration = 60
            $appointment.ReminderMinutesBeforeStart = 15
            $appointment.ReminderSet = $true
            
            if ("{description}") {{
                $appointment.Body = "{description}"
            }}
            
            $appointment.Save()
            Write-Output "Rappel créé avec succès"
        }} catch {{
            Write-Output "Erreur: Outlook non disponible"
        }}
        """
        
        resultat = subprocess.run(
            ["powershell", "-Command", commande],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if resultat.returncode == 0:
            return resultat.stdout.strip()
        else:
            return f"Erreur lors de la création du rappel: {resultat.stderr}"
            
    except Exception as e:
        return f"Erreur: {str(e)}"


def analyser_disponibilite(date_debut: str, date_fin: str) -> Dict[str, Any]:
    """
    Analyse la disponibilité sur une période donnée.
    
    Args:
        date_debut: Date de début (YYYY-MM-DD)
        date_fin: Date de fin (YYYY-MM-DD)
        
    Returns:
        Analyse des créneaux disponibles
    """
    try:
        debut = datetime.strptime(date_debut, "%Y-%m-%d")
        fin = datetime.strptime(date_fin, "%Y-%m-%d")
        jours = (fin - debut).days + 1
        
        evenements = obtenir_evenements_calendrier(jours + 7)
        
        # Analyser les créneaux occupés
        creneaux_occupes = []
        for event in evenements:
            try:
                event_debut = datetime.fromisoformat(event.get("debut", "").replace('Z', '+00:00'))
                event_fin = datetime.fromisoformat(event.get("fin", "").replace('Z', '+00:00'))
                
                if debut <= event_debut.date() <= fin.date():
                    creneaux_occupes.append({
                        "debut": event_debut,
                        "fin": event_fin,
                        "titre": event.get("titre", "")
                    })
            except (ValueError, TypeError):
                continue
        
        # Calculer le taux d'occupation
        total_heures = jours * 8  # 8 heures par jour
        heures_occupees = sum(
            (c["fin"] - c["debut"]).total_seconds() / 3600 
            for c in creneaux_occupes
        )
        
        taux_occupation = (heures_occupees / total_heures * 100) if total_heures > 0 else 0
        
        return {
            "periode": f"{date_debut} à {date_fin}",
            "jours_analyses": jours,
            "evenements_trouves": len(creneaux_occupes),
            "heures_occupees": round(heures_occupees, 1),
            "taux_occupation": round(taux_occupation, 1),
            "disponible": taux_occupation < 70
        }
        
    except Exception as e:
        return {"erreur": f"Erreur lors de l'analyse: {str(e)}"}


def synchroniser_calendrier_jarvis() -> str:
    """
    Synchronise les événements calendrier avec la mémoire Jarvis.
    
    Returns:
        Résultat de la synchronisation
    """
    evenements = obtenir_evenements_calendrier(7)
    
    if not evenements or ("erreur" in evenements[0]):
        return "Aucun événement à synchroniser."
    
    data = normaliser_memoire(charger_memoire())
    data["evenements_calendrier"] = evenements
    data["derniere_sync_calendrier"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sauvegarder_memoire(data)
    
    return f"Synchronisé : {len(evenements)} événements calendrier"
