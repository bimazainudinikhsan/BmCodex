from flask import Flask, jsonify, Response, render_template
import json, time, threading, os

app = Flask(__name__)

STATS_FILE = "stats.json"
LOG_FILE = "userbot.log"

def read_stats():
    if not os.path.exists(STATS_FILE):
        return {}
    with open(STATS_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return {}

@app.route("/")
def home():
    return render_template("dashboard.html")

@app.route("/stats")
def stats():
    return jsonify(read_stats())

@app.route('/stream')
def stream():
    def event_stream():
        while True:
            data = read_stats()
            yield f"data: {json.dumps(data)}\n\n"
            time.sleep(2)
    return Response(event_stream(), mimetype='text/event-stream')

@app.route('/logs')
def logs():
    if not os.path.exists(LOG_FILE):
        return "Log file not found"
    with open(LOG_FILE, "r", errors="ignore") as f:
        lines = f.readlines()[-200:]
    return "<pre>" + "".join(lines) + "</pre>"

def start_dashboard():
    app.run(host="0.0.0.0", port=5000)
