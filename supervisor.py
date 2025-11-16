import subprocess, time, threading
from dashboard import start_dashboard

USERBOT_FILE = "telethon_userbot_full.py"

dashboard_thread = threading.Thread(target=start_dashboard, daemon=True)
dashboard_thread.start()

def start_userbot():
    while True:
        print("[Supervisor] Starting Userbot...")
        p = subprocess.Popen(["python", USERBOT_FILE])
        p.wait()
        print("[Supervisor] Userbot crashed, restarting in 5 seconds...")
        time.sleep(5)

start_userbot()
