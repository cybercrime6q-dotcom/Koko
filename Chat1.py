from flask import Flask, request, render_template_string, redirect, url_for
import json, os

app = Flask(__name__)

USERS_FILE = "users.json"
MESSAGES_FILE = "messages.json"

for f in [USERS_FILE, MESSAGES_FILE]:
    if not os.path.exists(f):
        with open(f, "w") as file:
            json.dump({} if f == USERS_FILE else [], file)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Mini Chat</title></head>
<body>
<h2>Mini Chat</h2>
{% if username %}
<p>Hi {{ username }} | <a href="{{ url_for('logout') }}">Logout</a></p>
<form method="post" action="{{ url_for('send') }}">
<input type="text" name="message" placeholder="Tulis pesan..." required>
<button type="submit">Kirim</button>
</form>
<h3>Pesan:</h3>
<ul>
{% for msg in messages %}
<li><b>{{ msg['user'] }}:</b> {{ msg['text'] }}</li>
{% endfor %}
</ul>
{% else %}
<form method="post" action="{{ url_for('login') }}">
<input type="text" name="username" placeholder="Masukkan username" required>
<button type="submit">Login/Register</button>
</form>
{% endif %}
</body>
</html>
"""

def load_json(filename):
    with open(filename, "r") as f:
        return json.load(f)

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f)

@app.route("/", methods=["GET"])
def index():
    username = request.args.get("username")
    messages = load_json(MESSAGES_FILE)
    return render_template_string(HTML_TEMPLATE, username=username, messages=messages)

@app.route("/login", methods=["POST"])
def login():
    username = request.form["username"]
    users = load_json(USERS_FILE)
    if username not in users:
        users[username] = {}
        save_json(USERS_FILE, users)
    return redirect(url_for("index", username=username))

@app.route("/send", methods=["POST"])
def send():
    username = request.args.get("username")
    if not username:
        return redirect(url_for("index"))
    messages = load_json(MESSAGES_FILE)
    text = request.form["message"]
    messages.append({"user": username, "text": text})
    save_json(MESSAGES_FILE, messages)
    return redirect(url_for("index", username=username))

@app.route("/logout")
def logout():
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)