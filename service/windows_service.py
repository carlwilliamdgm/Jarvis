import win32serviceutil
import win32service
import win32event
import subprocess
import threading
import os
import sys

class JarvisService(win32serviceutil.ServiceFramework):
    _svc_name_ = 'JarvisService'
    _svc_display_name_ = 'Jarvis AI Agent'

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        try:
            os.chdir(os.path.dirname(os.path.abspath(__file__)))
            os.chdir('../')
            subprocess.Popen(['taskkill', '/im', 'uvicorn.exe'], shell=True)
        except Exception as e:
            print(f"Erreur lors de l'arrêt du service : {e}")
        self.stop_event.set()
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        self.ReportServiceStatus(win32service.SERVICE_START_PENDING)
        try:
            os.chdir(os.path.dirname(os.path.abspath(__file__)))
            os.chdir('../')
            subprocess.Popen(['uvicorn', 'api.server:app', '--host', '0.0.0.0', '--port', '8000'], shell=True)
            import sys
            sys.path.insert(0, os.getcwd())
            from core.memory import charger_memoire, normaliser_memoire
            from tools import OUTILS
            from jarvis import AutonomousAgent, initialiser
            from rich.console import Console
    
            console = Console()
            memoire = initialiser()
    
            agent = AutonomousAgent(
                memoire=memoire,
                outils=OUTILS,
                console=console
            )
    
            self.stop_event = threading.Event()
            agent_thread = threading.Thread(
                target=agent.run,
                args=(self.stop_event,),
                daemon=True
            )
            agent_thread.start()
        except Exception as e:
            print(f"Erreur lors du démarrage du service : {e}")
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(JarvisService)
