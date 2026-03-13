"""
WaClone - WhatsApp Clone
Stack: Supabase (DB + Auth) | Cloudinary (Storage) | Agora (Call/Live)
"""

from flask import Flask, request, jsonify, redirect, make_response
import time, sys, os, uuid, json, urllib.request, urllib.parse, hashlib, hmac, base64
from dotenv import load_dotenv

# Load environment variables dari file .env
load_dotenv()

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False  # Allow Unicode in JSON responses
app.secret_key = os.environ.get("SECRET_KEY", "waclone-secret-2024")

# ============================
# ENV CONFIG
# ============================
CLOUDINARY_CLOUD_NAME    = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY       = os.environ.get("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET    = os.environ.get("CLOUDINARY_API_SECRET", "")

SUPABASE_URL             = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY             = os.environ.get("SUPABASE_KEY", "")

AGORA_APP_ID             = os.environ.get("AGORA_APP_ID", "")
AGORA_APP_CERTIFICATE    = os.environ.get("AGORA_APP_CERTIFICATE", "")

# ============================
# SUPABASE HELPERS
# ============================
def supa_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def supa_get(table, params=""):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    req = urllib.request.Request(url, headers=supa_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"Supa GET error {table}:", e.read(), file=sys.stderr)
        return []
    except Exception as e:
        print(f"Supa GET error {table}:", e, file=sys.stderr)
        return []

def supa_post(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=supa_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
            if not raw.strip():
                return True
            result = json.loads(raw)
            return result
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"Supa POST error {table}:", err, file=sys.stderr)
        return None
    except Exception as e:
        print(f"Supa POST error {table}:", e, file=sys.stderr)
        return None

def supa_patch(table, params, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=supa_headers(), method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"Supa PATCH error {table}:", e.read(), file=sys.stderr)
        return None
    except Exception as e:
        print(f"Supa PATCH error {table}:", e, file=sys.stderr)
        return None

def supa_delete(table, params):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    req = urllib.request.Request(url, headers=supa_headers(), method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return True
    except Exception as e:
        print(f"Supa DELETE error {table}:", e, file=sys.stderr)
        return False

# ============================
# CLOUDINARY HELPERS
# ============================
def cloudinary_upload(file_bytes, filename, resource_type="auto", folder="waclone"):
    """Upload file to Cloudinary using REST API"""
    timestamp = str(int(time.time()))
    public_id = f"{folder}/{int(time.time())}_{uuid.uuid4().hex[:8]}"

    # Build signature
    params_to_sign = f"public_id={public_id}&timestamp={timestamp}"
    sig = hashlib.sha256((params_to_sign + CLOUDINARY_API_SECRET).encode()).hexdigest()

    boundary = uuid.uuid4().hex
    body_parts = []

    def add_field(name, value):
        body_parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}".encode())

    add_field("api_key", CLOUDINARY_API_KEY)
    add_field("timestamp", timestamp)
    add_field("public_id", public_id)
    add_field("signature", sig)

    # File part
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    ct_map = {"jpg":"image/jpeg","jpeg":"image/jpeg","png":"image/png","gif":"image/gif",
              "webp":"image/webp","mp4":"video/mp4","webm":"video/webm","mp3":"audio/mpeg",
              "ogg":"audio/ogg","pdf":"application/pdf"}
    content_type = ct_map.get(ext, "application/octet-stream")
    file_part = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + file_bytes

    body_parts.append(file_part)
    body_parts.append(f"--{boundary}--".encode())

    body = b"\r\n".join(body_parts)
    upload_url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/{resource_type}/upload"
    req = urllib.request.Request(
        upload_url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read().decode())
            return result.get("secure_url", ""), content_type
    except urllib.error.HTTPError as e:
        print("Cloudinary upload error:", e.read(), file=sys.stderr)
        return "", ""
    except Exception as e:
        print("Cloudinary upload error:", e, file=sys.stderr)
        return "", ""

# ============================
# PASSWORD HELPERS
# ============================
def hash_password(pw):
    salt = uuid.uuid4().hex
    hashed = hashlib.sha256((salt + pw).encode()).hexdigest()
    return f"{salt}:{hashed}"

def check_password(stored, pw):
    try:
        salt, hashed = stored.split(":", 1)
        return hashlib.sha256((salt + pw).encode()).hexdigest() == hashed
    except:
        return False

# ============================
# USER HELPERS
# ============================
def get_current_user(req):
    uid = req.cookies.get("uid")
    if not uid: return None
    rows = supa_get("users", f"uid=eq.{uid}&select=*")
    return rows[0] if rows else None

# ============================
# AUTH PAGE HTML
# ============================
AUTH_PAGE = """<!DOCTYPE html>
<html>
<head>
<title>WaClone</title>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root{--g:#00a884;--dk:#111b21;--pn:#202c33;--bd:#2a3942;--tx:#e9edef;--st:#8696a0;--rd:#f15c6d;}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:'Nunito',sans-serif;background:var(--dk);color:var(--tx);display:flex;align-items:center;justify-content:center;min-height:100vh;background-image:radial-gradient(circle at 20% 80%,rgba(0,168,132,.08) 0,transparent 50%),radial-gradient(circle at 80% 20%,rgba(0,168,132,.06) 0,transparent 50%);}
input{outline:none;border:none;font-family:'Nunito',sans-serif;}button{cursor:pointer;font-family:'Nunito',sans-serif;}
.wrap{width:100%;max-width:420px;padding:20px;}
.logo{text-align:center;margin-bottom:32px;}
.logo svg{width:76px;height:76px;filter:drop-shadow(0 8px 24px rgba(0,168,132,.5));}
.logo h1{font-size:30px;font-weight:900;color:var(--g);margin-top:10px;letter-spacing:-1px;}
.logo p{color:var(--st);font-size:14px;margin-top:4px;}
.card{background:var(--pn);border-radius:20px;padding:28px;border:1px solid var(--bd);box-shadow:0 20px 60px rgba(0,0,0,.4);}
.tabs{display:flex;gap:4px;background:var(--dk);border-radius:12px;padding:4px;margin-bottom:24px;}
.tab{flex:1;padding:10px;text-align:center;border-radius:9px;font-weight:800;font-size:14px;color:var(--st);cursor:pointer;transition:.2s;}
.tab.active{background:var(--g);color:#fff;box-shadow:0 4px 12px rgba(0,168,132,.4);}
.fg{margin-bottom:14px;position:relative;}
.fg label{display:block;font-size:11px;font-weight:800;color:var(--st);margin-bottom:6px;text-transform:uppercase;letter-spacing:.8px;}
.fg input{width:100%;padding:13px 16px;border-radius:12px;font-size:15px;background:var(--dk);border:1.5px solid var(--bd);color:var(--tx);transition:.2s;}
.fg input:focus{border-color:var(--g);background:#1a2328;}
.eye{position:absolute;right:14px;bottom:13px;cursor:pointer;color:var(--st);font-size:18px;line-height:1;}
.btn{width:100%;padding:14px;background:var(--g);color:#fff;border:none;border-radius:12px;font-size:16px;font-weight:800;transition:.2s;margin-top:6px;}
.btn:hover{background:#009070;transform:translateY(-1px);box-shadow:0 8px 20px rgba(0,168,132,.35);}
.btn:disabled{opacity:.6;transform:none;}
.pf{display:none;}.pf.active{display:block;}
.err{color:var(--rd);font-size:13px;margin-top:8px;text-align:center;min-height:18px;}
.toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:var(--pn);color:var(--tx);padding:12px 24px;border-radius:12px;border-left:4px solid var(--g);z-index:9999;box-shadow:0 8px 32px rgba(0,0,0,.5);opacity:0;transition:opacity .3s;pointer-events:none;font-weight:700;}
.toast.show{opacity:1;}
.spin{display:inline-block;width:18px;height:18px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;}
@keyframes spin{to{transform:rotate(360deg);}}
</style>
</head>
<body>
<div class="wrap">
  <div class="logo">
    <svg viewBox="0 0 80 80" fill="none">
      <circle cx="40" cy="40" r="40" fill="#00a884"/>
      <path d="M40 16C27 16 16 27 16 40c0 4.3 1.2 8.4 3.3 11.8L16 64l12.7-3.4A24 24 0 1040 16z" fill="white"/>
      <path d="M31 33c0-.6.5-1 1-1h16c.6 0 1 .4 1 1v.6c0 .5-.4 1-1 1H32c-.5 0-1-.5-1-1V33zm0 8c0-.6.5-1 1-1h10c.5 0 1 .4 1 1v.5c0 .6-.5 1-1 1H32c-.5 0-1-.4-1-1V41z" fill="#00a884"/>
    </svg>
    <h1>WaClone</h1>
    <p>Simple. Fast. Private.</p>
  </div>
  <div class="card">
    <div class="tabs">
      <div class="tab active" onclick="sw('login')">Masuk</div>
      <div class="tab" onclick="sw('register')">Daftar</div>
    </div>
    <div id="login-p" class="pf active">
      <div class="fg"><label>Email</label><input id="le" type="email" placeholder="nama@email.com" onkeydown="if(event.key==='Enter')doLogin()"></div>
      <div class="fg">
        <label>Password</label>
        <input id="lp" type="password" placeholder="â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢" onkeydown="if(event.key==='Enter')doLogin()">
        <span class="eye" onclick="togglePw('lp',this)">ðŸ‘ï¸</span>
      </div>
      <div class="err" id="le2"></div>
      <button class="btn" id="lbtn" onclick="doLogin()">Masuk â†’</button>
    </div>
    <div id="register-p" class="pf">
      <div class="fg"><label>Username</label><input id="ru" placeholder="username kamu" onkeydown="if(event.key==='Enter')doReg()"></div>
      <div class="fg"><label>Email</label><input id="re" type="email" placeholder="nama@email.com" onkeydown="if(event.key==='Enter')doReg()"></div>
      <div class="fg">
        <label>Password</label>
        <input id="rp" type="password" placeholder="min. 6 karakter" onkeydown="if(event.key==='Enter')doReg()">
        <span class="eye" onclick="togglePw('rp',this)">ðŸ‘ï¸</span>
      </div>
      <div class="err" id="re2"></div>
      <button class="btn" id="rbtn" onclick="doReg()">Daftar â†’</button>
      <p style="font-size:12px;color:var(--st);text-align:center;margin-top:14px;">Dengan mendaftar kamu menyetujui syarat & ketentuan WaClone.</p>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>
function sw(t){document.querySelectorAll('.tab').forEach(e=>e.classList.remove('active'));document.querySelectorAll('.pf').forEach(e=>e.classList.remove('active'));document.getElementById(t+'-p').classList.add('active');document.querySelectorAll('.tab')[t==='login'?0:1].classList.add('active');document.getElementById('le2').textContent='';document.getElementById('re2').textContent='';}
function toast(m,d=3000){const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),d);}
function togglePw(id,el){const i=document.getElementById(id);i.type=i.type==='password'?'text':'password';el.textContent=i.type==='password'?'ðŸ‘ï¸':'ðŸ™ˆ';}
function setLoading(btn,loading,label){const b=document.getElementById(btn);if(loading){b.disabled=true;b.innerHTML='<span class="spin"></span>';}else{b.disabled=false;b.textContent=label;}}
async function doLogin(){
  const email=document.getElementById('le').value.trim(),pass=document.getElementById('lp').value;
  const err=document.getElementById('le2');if(!email||!pass){err.textContent='Isi semua field!';return;}
  setLoading('lbtn',true);
  const fd=new FormData();fd.append('email',email);fd.append('password',pass);
  const r=await fetch('/login',{method:'POST',body:fd});const d=await r.json();
  setLoading('lbtn',false,'Masuk â†’');
  if(d.ok){toast('Login berhasil! ðŸŽ‰');setTimeout(()=>location.href='/home',700);}else err.textContent=d.msg||'Login gagal';
}
async function doReg(){
  const u=document.getElementById('ru').value.trim(),e=document.getElementById('re').value.trim(),p=document.getElementById('rp').value;
  const err=document.getElementById('re2');if(!u||!e||!p){err.textContent='Isi semua field!';return;}
  if(p.length<6){err.textContent='Password minimal 6 karakter';return;}
  if(!/^[a-zA-Z0-9_]+$/.test(u)){err.textContent='Username hanya huruf, angka, underscore';return;}
  setLoading('rbtn',true);
  const fd=new FormData();fd.append('username',u);fd.append('email',e);fd.append('password',p);
  const r=await fetch('/register',{method:'POST',body:fd});const d=await r.json();
  setLoading('rbtn',false,'Daftar â†’');
  if(d.ok){toast('Registrasi berhasil! ðŸŽ‰');setTimeout(()=>location.href='/home',700);}else err.textContent=d.msg||'Registrasi gagal';
}
</script>
</body>
</html>"""

# ============================
# MAIN APP HTML (inline, no external template)
# ============================
MAIN_HTML = """<!DOCTYPE html>
<html>
<head>
<title>WaClone</title>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<script src="https://download.agora.io/sdk/release/AgoraRTC_N-4.19.0.js"></script>
<style>
:root{--g:#00a884;--dk:#111b21;--pn:#202c33;--bo:#005c4b;--bi:#1e2c33;--bd:#2a3942;--tx:#e9edef;--st:#8696a0;--hv:#2a3942;--rd:#f15c6d;--bl:#53bdeb;--inp:#2a3942;}
*{margin:0;padding:0;box-sizing:border-box;}html,body{height:100%;overflow:hidden;}
body{font-family:'Nunito',sans-serif;background:var(--dk);color:var(--tx);display:flex;height:100vh;}
::-webkit-scrollbar{width:5px;}::-webkit-scrollbar-thumb{background:var(--bd);border-radius:3px;}
input,textarea{outline:none;border:none;background:transparent;color:var(--tx);font-family:'Nunito',sans-serif;}
button{cursor:pointer;font-family:'Nunito',sans-serif;border:none;}

/* SIDEBAR */
.sb{width:360px;min-width:300px;max-width:360px;background:var(--pn);display:flex;flex-direction:column;border-right:1px solid var(--bd);height:100vh;overflow:hidden;transition:transform .25s;}
.sbh{padding:10px 14px;display:flex;align-items:center;gap:8px;height:60px;border-bottom:1px solid var(--bd);flex-shrink:0;}
.my-av{width:40px;height:40px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:17px;color:#fff;cursor:pointer;flex-shrink:0;overflow:hidden;}
.my-av img{width:40px;height:40px;object-fit:cover;border-radius:50%;}
.sbh-title{font-size:19px;font-weight:900;flex:1;}
.icon-btn{width:38px;height:38px;border-radius:50%;background:transparent;color:var(--st);display:flex;align-items:center;justify-content:center;transition:.2s;position:relative;flex-shrink:0;border:none;}
.icon-btn:hover{background:var(--hv);color:var(--tx);}
.badge{position:absolute;top:3px;right:3px;background:var(--rd);color:#fff;border-radius:50%;width:16px;height:16px;font-size:9px;font-weight:900;display:flex;align-items:center;justify-content:center;}
.sbtabs{display:flex;border-bottom:1px solid var(--bd);flex-shrink:0;}
.stab{flex:1;padding:10px 4px;text-align:center;font-size:12px;font-weight:800;color:var(--st);cursor:pointer;border-bottom:2.5px solid transparent;transition:.2s;}
.stab.active{color:var(--g);border-bottom-color:var(--g);}
.search-wrap{padding:7px 12px;flex-shrink:0;}
.search-inner{position:relative;display:flex;align-items:center;}
.search-inner svg{position:absolute;left:11px;color:var(--st);pointer-events:none;}
.search-inner input{width:100%;padding:8px 14px 8px 38px;border-radius:10px;background:var(--dk);font-size:14px;color:var(--tx);border:1.5px solid transparent;}
.search-inner input:focus{border-color:var(--g);}
.sb-panel{flex:1;overflow-y:auto;display:none;flex-direction:column;}
.sb-panel.active{display:flex;}
.chat-item{display:flex;align-items:center;gap:11px;padding:9px 14px;cursor:pointer;border-bottom:1px solid rgba(255,255,255,.03);transition:.15s;}
.chat-item:hover,.chat-item.active{background:var(--hv);}
.chat-av{width:48px;height:48px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:19px;color:#fff;flex-shrink:0;position:relative;overflow:hidden;}
.chat-av img{width:48px;height:48px;border-radius:50%;object-fit:cover;}
.online-dot{position:absolute;bottom:1px;right:1px;width:12px;height:12px;background:#44c56a;border-radius:50%;border:2px solid var(--pn);}
.chat-info{flex:1;min-width:0;}
.chat-name{font-weight:800;font-size:14px;}
.chat-prev{font-size:12px;color:var(--st);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;}
.chat-meta{display:flex;flex-direction:column;align-items:flex-end;gap:3px;flex-shrink:0;}
.chat-time{font-size:11px;color:var(--st);}
.unread-badge{background:var(--g);color:#fff;border-radius:50%;min-width:19px;height:19px;font-size:11px;font-weight:900;display:flex;align-items:center;justify-content:center;padding:0 4px;}

/* STATUS */
.status-section-label{font-size:11px;font-weight:800;color:var(--st);text-transform:uppercase;letter-spacing:.5px;padding:10px 14px 5px;}
.my-status-row{display:flex;align-items:center;gap:12px;padding:10px 14px;cursor:pointer;border-bottom:1px solid var(--bd);transition:.15s;}
.my-status-row:hover{background:var(--hv);}
.status-ring{width:52px;height:52px;border-radius:50%;border:3px solid var(--g);padding:2px;position:relative;flex-shrink:0;}
.status-ring-inner{width:100%;height:100%;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff;overflow:hidden;}
.status-ring-inner img{width:100%;height:100%;object-fit:cover;}
.status-add-badge{position:absolute;bottom:-2px;right:-2px;width:20px;height:20px;border-radius:50%;background:var(--g);color:#fff;font-size:15px;line-height:20px;text-align:center;border:2px solid var(--pn);}
.status-friend-item{display:flex;align-items:center;gap:12px;padding:9px 14px;cursor:pointer;border-bottom:1px solid rgba(255,255,255,.03);transition:.15s;}
.status-friend-item:hover{background:var(--hv);}

/* MAIN */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;position:relative;height:100vh;}
.no-chat{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--st);gap:10px;}
.no-chat-icon{font-size:70px;opacity:.25;}
.no-chat h2{font-size:21px;font-weight:900;color:var(--tx);}

/* CHAT HEADER */
.chat-header{height:60px;background:var(--pn);display:flex;align-items:center;gap:4px;padding:0 6px 0 4px;border-bottom:1px solid var(--bd);flex-shrink:0;overflow:visible;min-width:0;}
.back-btn{width:36px;height:36px;border-radius:50%;background:transparent;color:var(--st);display:none;align-items:center;justify-content:center;flex-shrink:0;transition:.2s;}
.back-btn:hover{background:var(--hv);color:var(--tx);}
.header-av{width:40px;height:40px;border-radius:50%;overflow:hidden;flex-shrink:0;cursor:pointer;}
.header-btn{width:38px;height:38px;border-radius:50%;background:transparent;color:var(--tx);display:flex;align-items:center;justify-content:center;transition:.2s;flex-shrink:0;border:none;cursor:pointer;}
.header-btn:hover{background:var(--hv);}
.call-btn-audio{background:rgba(0,168,132,.12);color:var(--g);}
.call-btn-audio:hover{background:rgba(0,168,132,.25);}
.call-btn-video{background:rgba(83,189,235,.12);color:var(--bl);}
.call-btn-video:hover{background:rgba(83,189,235,.25);}

/* MESSAGES */
.messages-area{flex:1;overflow-y:auto;padding:8px 18px 4px;display:flex;flex-direction:column;gap:2px;background-color:var(--dk);}
.msg-row{display:flex;margin:1px 0;align-items:flex-end;gap:4px;position:relative;}
.msg-row:hover .msg-actions{opacity:1;}
.msg-row.out{justify-content:flex-end;}
.msg-row.in{justify-content:flex-start;}
.msg-actions{opacity:0;transition:opacity .15s;display:flex;gap:3px;align-items:center;}
.msg-row.out .msg-actions{order:-1;}
.act-btn{width:25px;height:25px;border-radius:50%;background:rgba(32,44,51,.92);border:1px solid var(--bd);color:var(--st);font-size:11px;display:flex;align-items:center;justify-content:center;transition:.15s;}
.act-btn:hover{background:var(--hv);color:var(--tx);}
.bubble{max-width:66%;padding:7px 11px 4px;border-radius:12px;font-size:14px;line-height:1.5;word-break:break-word;box-shadow:0 1px 2px rgba(0,0,0,.3);position:relative;}
.msg-row.out .bubble{background:var(--bo);border-bottom-right-radius:3px;}
.msg-row.in .bubble{background:var(--bi);border-bottom-left-radius:3px;}
.bubble-time{font-size:10.5px;color:rgba(255,255,255,.45);text-align:right;margin-top:3px;display:flex;align-items:center;justify-content:flex-end;gap:2px;white-space:nowrap;}
.tick.read{color:var(--bl);}
.bubble img{max-width:250px;max-height:250px;border-radius:8px;display:block;margin-bottom:3px;cursor:pointer;object-fit:cover;}
.bubble audio{width:210px;margin-bottom:3px;}
.bubble video{max-width:250px;border-radius:8px;display:block;margin-bottom:3px;}
.bubble a.file-link{color:var(--bl);text-decoration:none;font-size:13px;display:flex;align-items:center;gap:6px;padding:5px 0;}
.date-divider{text-align:center;color:var(--st);font-size:11px;margin:8px 0;}
.date-divider span{background:rgba(17,27,33,.85);padding:3px 12px;border-radius:20px;border:1px solid var(--bd);}
.reply-quote{background:rgba(255,255,255,.07);border-left:3px solid var(--g);border-radius:6px;padding:5px 8px;margin-bottom:5px;font-size:11px;}
.rq-name{font-weight:800;color:var(--g);font-size:10px;margin-bottom:2px;}
.rq-text{color:var(--st);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:220px;}
.typing-wrap{padding:3px 18px;min-height:24px;display:flex;align-items:center;flex-shrink:0;}
.typing-dots{display:none;align-items:center;gap:6px;}
.typing-dots.show{display:flex;}
.dot-anim{display:flex;gap:3px;}
.dot-anim span{width:6px;height:6px;background:var(--st);border-radius:50%;animation:dotBounce 1.4s infinite;}
.dot-anim span:nth-child(2){animation-delay:.2s;}
.dot-anim span:nth-child(3){animation-delay:.4s;}
@keyframes dotBounce{0%,60%,100%{transform:translateY(0);}30%{transform:translateY(-5px);}}
.typing-text{font-size:11px;color:var(--st);}

/* INPUT */
.input-area{background:var(--pn);padding:6px 10px 8px;border-top:1px solid var(--bd);flex-shrink:0;display:flex;flex-direction:column;gap:5px;}
.reply-preview{display:none;background:rgba(0,168,132,.1);border-left:3px solid var(--g);border-radius:8px;padding:6px 10px;align-items:center;justify-content:space-between;gap:8px;}
.reply-preview.show{display:flex;}
.rp-name{color:var(--g);font-weight:800;font-size:11px;}
.rp-text{color:var(--st);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.rp-close{width:22px;height:22px;border-radius:50%;background:var(--bd);color:var(--st);font-size:12px;display:flex;align-items:center;justify-content:center;}
.input-row{display:flex;align-items:flex-end;gap:5px;}
.side-btn{width:38px;height:38px;border-radius:50%;background:transparent;color:var(--st);display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;transition:.2s;}
.side-btn:hover{background:var(--hv);color:var(--tx);}
.msg-textarea{flex:1;background:var(--inp);border:1.5px solid transparent;border-radius:22px;padding:9px 15px;font-size:14.5px;color:var(--tx);resize:none;max-height:120px;min-height:42px;line-height:1.4;transition:.2s;display:block;}
.msg-textarea:focus{border-color:var(--g);}
.msg-textarea::placeholder{color:var(--st);}
.send-btn{width:42px;height:42px;border-radius:50%;background:var(--g);color:#fff;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:.2s;}
.send-btn:hover{background:#009070;transform:scale(1.06);}
.rec-btn{width:42px;height:42px;border-radius:50%;background:var(--dk);border:1.5px solid var(--bd);color:var(--st);display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:.2s;}
.rec-btn.recording{background:var(--rd);border-color:var(--rd);color:#fff;animation:recPulse 1s infinite;}
@keyframes recPulse{0%,100%{transform:scale(1);}50%{transform:scale(1.1);}}
.upload-progress{height:3px;background:var(--bd);border-radius:3px;overflow:hidden;display:none;}
.upload-progress.show{display:block;}
.upload-fill{height:100%;background:var(--g);width:0%;transition:width .3s;border-radius:3px;}

/* EMOJI */
.emoji-picker{position:absolute;bottom:68px;right:52px;background:var(--pn);border:1px solid var(--bd);border-radius:16px;padding:10px;box-shadow:0 8px 30px rgba(0,0,0,.6);z-index:200;display:none;width:280px;}
.emoji-picker.open{display:block;}
.emoji-grid{display:flex;flex-wrap:wrap;gap:2px;max-height:170px;overflow-y:auto;}
.emoji-item{font-size:21px;cursor:pointer;padding:4px;border-radius:7px;transition:.1s;line-height:1;}
.emoji-item:hover{background:var(--hv);}

/* ATT MENU */
.att-menu{position:absolute;bottom:68px;left:10px;background:var(--pn);border:1px solid var(--bd);border-radius:16px;padding:12px;box-shadow:0 8px 30px rgba(0,0,0,.6);z-index:200;display:none;flex-wrap:wrap;gap:8px;width:220px;}
.att-menu.open{display:flex;}
.att-opt{display:flex;flex-direction:column;align-items:center;gap:5px;cursor:pointer;width:calc(33% - 6px);padding:5px 0;border-radius:10px;transition:.15s;}
.att-opt:hover{background:var(--hv);}
.att-ic{width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:19px;}
.att-lbl{font-size:10px;font-weight:700;color:var(--st);}

/* CTX MENU */
.ctx-menu{position:fixed;background:var(--pn);border:1px solid var(--bd);border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.6);z-index:600;min-width:178px;overflow:hidden;display:none;}
.ctx-item{padding:10px 16px;font-size:14px;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:10px;transition:.15s;color:var(--tx);}
.ctx-item:hover{background:var(--hv);}
.ctx-item.danger{color:var(--rd);}

/* OVERLAY/PANEL */
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:400;display:none;align-items:center;justify-content:center;}
.overlay.open{display:flex;}
.panel{background:var(--pn);border-radius:20px;width:400px;max-height:90vh;overflow-y:auto;border:1px solid var(--bd);box-shadow:0 20px 60px rgba(0,0,0,.6);}
.panel-header{padding:16px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--bd);position:sticky;top:0;background:var(--pn);z-index:1;}
.panel-header h2{font-size:17px;font-weight:900;}
.close-btn{background:var(--hv);border:none;color:var(--st);width:30px;height:30px;border-radius:50%;font-size:15px;display:flex;align-items:center;justify-content:center;cursor:pointer;}
.panel-body{padding:18px 20px;}
.pav-wrap{text-align:center;margin-bottom:14px;position:relative;display:inline-block;left:50%;transform:translateX(-50%);}
.pav-big{width:96px;height:96px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:38px;font-weight:900;color:#fff;overflow:hidden;cursor:pointer;border:3px solid var(--bd);transition:.2s;}
.pav-big:hover{border-color:var(--g);}
.pav-big img{width:100%;height:100%;object-fit:cover;}
.pav-edit-btn{position:absolute;bottom:1px;right:0;background:var(--g);width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:12px;}
.prof-name{font-size:19px;font-weight:900;text-align:center;}
.prof-email{color:var(--st);font-size:12px;text-align:center;margin-top:3px;}
.field-group{margin-bottom:12px;}
.field-group label{display:block;font-size:10px;font-weight:800;color:var(--g);text-transform:uppercase;letter-spacing:.6px;margin-bottom:5px;}
.field-group input,.field-group textarea{width:100%;padding:9px 12px;border-radius:10px;background:var(--dk);border:1.5px solid var(--bd);color:var(--tx);font-size:13px;font-family:'Nunito',sans-serif;transition:.2s;}
.field-group input:focus,.field-group textarea:focus{border-color:var(--g);outline:none;}
.field-group textarea{resize:none;height:68px;line-height:1.5;}
.save-btn{width:100%;padding:11px;background:var(--g);color:#fff;border:none;border-radius:12px;font-size:14px;font-weight:800;margin-top:5px;transition:.2s;cursor:pointer;}
.save-btn:hover{background:#009070;}
.logout-btn{width:100%;padding:10px;background:transparent;color:var(--rd);border:1.5px solid var(--rd);border-radius:12px;font-size:14px;font-weight:800;margin-top:7px;transition:.2s;cursor:pointer;}
.logout-btn:hover{background:var(--rd);color:#fff;}

/* NOTIF */
.notif-item{display:flex;gap:10px;align-items:center;padding:9px 0;border-bottom:1px solid var(--bd);cursor:pointer;}
.notif-av{width:42px;height:42px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:17px;color:#fff;flex-shrink:0;overflow:hidden;}
.notif-av img{width:42px;height:42px;object-fit:cover;}
.notif-dot{width:8px;height:8px;background:var(--g);border-radius:50%;flex-shrink:0;}

/* STATUS VIEWER */
.stv{background:#000;width:100%;max-width:460px;border-radius:20px;overflow:hidden;}
.stv-progress{display:flex;gap:3px;padding:10px 12px 6px;}
.stv-seg{flex:1;height:3px;background:rgba(255,255,255,.3);border-radius:3px;overflow:hidden;}
.stv-fill{height:100%;background:#fff;width:0%;transition:width linear;}
.stv-head{display:flex;align-items:center;gap:10px;padding:6px 14px;}
.stv-av{width:34px;height:34px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;color:#fff;font-size:13px;overflow:hidden;}
.stv-av img{width:100%;height:100%;object-fit:cover;}
.stv-body{min-height:200px;display:flex;align-items:center;justify-content:center;padding:14px;}
.stv-text{font-size:22px;font-weight:800;text-align:center;color:#fff;padding:22px 14px;width:100%;}
.stv-img{max-width:100%;max-height:380px;object-fit:contain;border-radius:4px;}
.stv-nav-btns{display:flex;justify-content:space-between;padding:8px 14px 14px;}
.stv-nav-btn{padding:8px 20px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);border-radius:20px;color:#fff;font-size:13px;font-weight:700;cursor:pointer;transition:.2s;}
.stv-nav-btn:hover{background:rgba(255,255,255,.2);}

/* CAM */
.cam-wrap{background:#000;border-radius:12px;overflow:hidden;}
.cam-wrap video{width:100%;display:block;max-height:270px;object-fit:cover;}
.cam-controls{display:flex;gap:10px;justify-content:center;margin-top:10px;}
.cam-btn{width:50px;height:50px;border-radius:50%;border:none;display:flex;align-items:center;justify-content:center;font-size:20px;cursor:pointer;transition:.2s;}

/* FORWARD */
.fw-list{display:flex;flex-direction:column;gap:6px;max-height:260px;overflow-y:auto;}
.fw-item{display:flex;align-items:center;gap:10px;padding:9px;background:var(--dk);border-radius:10px;cursor:pointer;border:1.5px solid var(--bd);transition:.15s;}
.fw-item:hover,.fw-item.sel{border-color:var(--g);}
.fw-av{width:36px;height:36px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:14px;color:#fff;flex-shrink:0;overflow:hidden;}

/* CALL UI */
.call-ui{position:fixed;inset:0;background:#080d14;z-index:900;display:none;flex-direction:column;align-items:center;justify-content:space-between;padding:20px;}
.call-ui.active{display:flex;}
.call-video-grid{width:100%;max-width:960px;flex:1;display:none;align-items:center;justify-content:center;gap:12px;padding:8px 0;position:relative;}
.call-video-grid.show{display:flex;}
#agora-remote{flex:1;max-height:72vh;border-radius:18px;overflow:hidden;background:#111827;border:1px solid var(--bd);min-height:220px;display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,.3);font-size:14px;}
#agora-local{position:relative;width:160px;min-width:130px;height:220px;border-radius:16px;overflow:hidden;background:#111;border:2px solid var(--g);flex-shrink:0;}
.audio-call-info{text-align:center;flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;}
.call-person-av{width:120px;height:120px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:50px;font-weight:900;color:#fff;overflow:hidden;border:4px solid rgba(0,168,132,.3);animation:callRing 2.5s infinite;}
@keyframes callRing{0%,100%{box-shadow:0 0 0 0 rgba(0,168,132,.4);}60%{box-shadow:0 0 0 24px rgba(0,168,132,0);}}
.call-person-av img{width:120px;height:120px;object-fit:cover;border-radius:50%;}
.call-name{font-size:28px;font-weight:900;color:#fff;}
.call-status-txt{font-size:15px;color:rgba(255,255,255,.55);}
.call-timer{font-size:22px;color:var(--g);font-weight:800;display:none;letter-spacing:2px;font-variant-numeric:tabular-nums;}
.call-controls{display:flex;gap:18px;align-items:center;justify-content:center;padding:14px 0 6px;flex-shrink:0;flex-wrap:wrap;}
.ccbtn{width:64px;height:64px;border-radius:50%;border:none;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:.2s;flex-direction:column;gap:3px;}
.ccbtn:hover{transform:scale(1.08);}
.ccbtn span{font-size:10px;color:rgba(255,255,255,.6);font-weight:700;}
.ccbtn svg{display:block;}
.btn-end{background:#e53e3e;}
.btn-toggle{background:#1e2a3a;}
.btn-toggle.on{background:var(--g);}
.btn-toggle.off{background:#c53030;}

/* INCOMING CALL */
.incoming-call{position:fixed;bottom:24px;right:24px;background:var(--pn);border:1px solid var(--bd);border-radius:20px;padding:18px;z-index:950;box-shadow:0 20px 60px rgba(0,0,0,.8);min-width:270px;display:none;}
.incoming-call.show{display:block;animation:slideIn .3s ease;}
@keyframes slideIn{from{transform:translateX(60px);opacity:0;}to{transform:none;opacity:1;}}
.inc-av{width:56px;height:56px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:900;color:#fff;margin:0 auto 8px;overflow:hidden;}
.inc-av img{width:56px;height:56px;object-fit:cover;border-radius:50%;}
.inc-actions{display:flex;gap:8px;margin-top:12px;}
.inc-btn{flex:1;padding:10px;border:none;border-radius:10px;font-size:13px;font-weight:800;cursor:pointer;color:#fff;}
.inc-accept{background:var(--g);}
.inc-video{background:#1a56db;}
.inc-reject{background:var(--rd);flex:none;padding:10px 16px;}

/* LIVE */
.live-ui{position:fixed;inset:0;background:#000;z-index:910;display:none;flex-direction:column;}
.live-ui.active{display:flex;}
.live-header{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:linear-gradient(to bottom,rgba(0,0,0,.8),transparent);position:absolute;top:0;left:0;right:0;z-index:2;}
.live-badge{background:#e53e3e;color:#fff;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:900;letter-spacing:1px;animation:livePulse 1.5s infinite;}
@keyframes livePulse{0%,100%{opacity:1;}50%{opacity:.7;}}
.live-video-area{flex:1;position:relative;background:#000;}
#live-local-video,#live-remote-video{width:100%;height:100%;object-fit:cover;position:absolute;top:0;left:0;}
.live-comments{position:absolute;bottom:80px;left:0;right:0;padding:10px 14px;display:flex;flex-direction:column;gap:4px;max-height:200px;overflow:hidden;pointer-events:none;}
.live-comment{background:rgba(0,0,0,.55);color:#fff;padding:6px 12px;border-radius:20px;font-size:13px;font-weight:600;width:fit-content;max-width:80%;}
.live-comment .cname{color:var(--g);font-weight:900;margin-right:6px;}
.live-controls-bottom{position:absolute;bottom:0;left:0;right:0;padding:12px 16px;background:linear-gradient(to top,rgba(0,0,0,.8),transparent);display:flex;align-items:center;gap:10px;}
.live-comment-input{flex:1;background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25);border-radius:24px;padding:9px 16px;color:#fff;font-size:14px;font-family:'Nunito',sans-serif;}
.live-comment-input:focus{outline:none;border-color:var(--g);}
.live-send-comment{width:40px;height:40px;border-radius:50%;background:var(--g);color:#fff;border:none;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;}

/* AI DRAWER */
.ai-drawer{position:fixed;top:0;right:0;height:100vh;width:360px;background:#13111c;border-left:1px solid rgba(108,58,199,.3);z-index:500;display:flex;flex-direction:column;transform:translateX(100%);transition:transform .3s cubic-bezier(.4,0,.2,1);box-shadow:-20px 0 60px rgba(0,0,0,.5);}
.ai-drawer.open{transform:translateX(0);}
.ai-drawer-header{padding:14px 16px;background:linear-gradient(135deg,#2d1059,#1a0a38);display:flex;align-items:center;gap:10px;border-bottom:1px solid rgba(108,58,199,.3);flex-shrink:0;}
.ai-messages{flex:1;overflow-y:auto;padding:14px 14px 6px;display:flex;flex-direction:column;gap:10px;}
.ai-msg{display:flex;gap:8px;align-items:flex-start;}
.ai-msg.user{flex-direction:row-reverse;}
.ai-msg-av{width:30px;height:30px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:14px;}
.ai-msg.ai .ai-msg-av{background:linear-gradient(135deg,#7c3aed,#9b5de5);}
.ai-msg.user .ai-msg-av{background:var(--g);}
.ai-bubble{max-width:84%;padding:9px 12px;border-radius:14px;font-size:13.5px;line-height:1.55;word-break:break-word;}
.ai-msg.ai .ai-bubble{background:rgba(108,58,199,.15);border:1px solid rgba(108,58,199,.25);color:#d4c8f8;}
.ai-msg.user .ai-bubble{background:var(--bo);color:var(--tx);}
.ai-thinking-bubble{display:flex;gap:4px;padding:10px 14px;background:rgba(108,58,199,.12);border:1px solid rgba(108,58,199,.2);border-radius:14px;}
.ai-thinking-bubble span{width:7px;height:7px;background:#9b5de5;border-radius:50%;animation:dotBounce 1.4s infinite;}
.ai-thinking-bubble span:nth-child(2){animation-delay:.2s;}
.ai-thinking-bubble span:nth-child(3){animation-delay:.4s;}
.ai-chips{display:flex;flex-wrap:wrap;gap:5px;padding:4px 14px 8px;}
.ai-chip{padding:5px 11px;background:rgba(108,58,199,.12);border:1px solid rgba(108,58,199,.25);border-radius:20px;font-size:11.5px;color:#c4b3f0;cursor:pointer;transition:.2s;}
.ai-chip:hover{background:rgba(108,58,199,.25);color:#e0d4ff;}
.ai-input-row{padding:10px 14px 14px;border-top:1px solid rgba(108,58,199,.2);display:flex;gap:8px;align-items:flex-end;flex-shrink:0;}
.ai-textarea{flex:1;background:rgba(108,58,199,.1);border:1.5px solid rgba(108,58,199,.3);border-radius:18px;padding:9px 13px;font-size:13.5px;color:#e0d4ff;resize:none;min-height:40px;max-height:100px;line-height:1.4;font-family:'Nunito',sans-serif;}
.ai-textarea:focus{border-color:#9b5de5;outline:none;}
.ai-textarea::placeholder{color:rgba(224,212,255,.3);}
.ai-send-btn{width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,#7c3aed,#9b5de5);color:#fff;border:none;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:.2s;}
.ai-send-btn:hover{transform:scale(1.08);}

/* LIVE LIST */
.live-item{display:flex;align-items:center;gap:11px;padding:9px 14px;cursor:pointer;border-bottom:1px solid rgba(255,255,255,.03);transition:.15s;}
.live-item:hover{background:var(--hv);}

/* TOAST */
.toast{position:fixed;bottom:26px;left:50%;transform:translateX(-50%);background:var(--pn);color:var(--tx);padding:9px 20px;border-radius:12px;border-left:4px solid var(--g);z-index:9999;box-shadow:0 8px 32px rgba(0,0,0,.5);opacity:0;transition:opacity .3s;pointer-events:none;font-weight:700;white-space:nowrap;}
.toast.show{opacity:1;}
.toast.err{border-left-color:var(--rd);}

/* FULLSCREEN IMG */
.img-fullview{max-width:92vw;max-height:88vh;border-radius:8px;object-fit:contain;}

@media(max-width:700px){
  .sb{position:fixed;left:0;top:0;z-index:100;width:100%!important;max-width:100%!important;}
  .sb.hidden{transform:translateX(-100%);}
  .main{width:100%;}
  .back-btn{display:flex!important;}
  .bubble{max-width:82%;}
  .ai-drawer{width:100%;}
  .call-ui{padding:12px;}
  .ccbtn{width:56px;height:56px;}
}
</style>
</head>
<body>

<!-- SIDEBAR -->
<div class="sb" id="sidebar">
  <div class="sbh">
    <div class="my-av" onclick="openPanel('prof-ov')" id="my-av-el">__SIDEBAR_AV__</div>
    <span class="sbh-title">WaClone</span>
    <button class="icon-btn" onclick="openAI()" title="AI" style="background:linear-gradient(135deg,#7c3aed,#9b5de5);color:#fff;">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a2 2 0 012 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 017 7h1a1 1 0 010 2h-1v1a2 2 0 01-2 2H5a2 2 0 01-2-2v-1H2a1 1 0 010-2h1a7 7 0 017-7h1V5.73A2 2 0 0110 4a2 2 0 012-2zm-5 9a5 5 0 000 10h10a5 5 0 000-10H7zm2 3a1 1 0 110 2 1 1 0 010-2zm6 0a1 1 0 110 2 1 1 0 010-2z"/></svg>
    </button>
    <button class="icon-btn" onclick="openNotifPanel()" title="Notifikasi">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>
      <span class="badge" id="notif-badge" style="display:none">0</span>
    </button>
    <button class="icon-btn" onclick="openPanel('settings-ov')" title="Pengaturan">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M19.14,12.94c0.04-0.3,0.06-0.61,0.06-0.94c0-0.32-0.02-0.64-0.07-0.94l2.03-1.58c0.18-0.14,0.23-0.41,0.12-0.61l-1.92-3.32c-0.12-0.22-0.37-0.29-0.59-0.22l-2.39,0.96c-0.5-0.38-1.03-0.7-1.62-0.94L14.4,2.81c-0.04-0.24-0.24-0.41-0.48-0.41h-3.84c-0.24,0-0.43,0.17-0.47,0.41L9.25,5.35C8.66,5.59,8.12,5.92,7.63,6.29L5.24,5.33c-0.22-0.08-0.47,0-0.59,0.22L2.74,8.87C2.62,9.08,2.66,9.34,2.86,9.48l2.03,1.58C4.84,11.36,4.8,11.69,4.8,12s0.02,0.64,0.07,0.94l-2.03,1.58c-0.18,0.14-0.23,0.41-0.12,0.61l1.92,3.32c0.12,0.22,0.37,0.29,0.59,0.22l2.39-0.96c0.5,0.38,1.03,0.7,1.62,0.94l0.36,2.54c0.05,0.24,0.24,0.41,0.48,0.41h3.84c0.24,0,0.44-0.17,0.47-0.41l0.36-2.54c0.59-0.24,1.13-0.56,1.62-0.94l2.39,0.96c0.22,0.08,0.47,0,0.59-0.22l1.92-3.32c0.12-0.22,0.07-0.47-0.12-0.61L19.14,12.94z M12,15.6c-1.98,0-3.6-1.62-3.6-3.6s1.62-3.6,3.6-3.6s3.6,1.62,3.6,3.6S13.98,15.6,12,15.6z"/></svg>
    </button>
  </div>
  <div class="sbtabs">
    <div class="stab active" onclick="switchTab('chats')" id="tab-chats"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" style="vertical-align:-2px;margin-right:3px;"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>Chat</div>
    <div class="stab" onclick="switchTab('status')" id="tab-status"><svg viewBox="0 0 24 24" width="15" height="15" fill="#4ade80" style="vertical-align:-2px;margin-right:3px;"><circle cx="12" cy="12" r="10"/></svg>Status</div>
    <div class="stab" onclick="switchTab('live')" id="tab-live"><svg viewBox="0 0 24 24" width="15" height="15" fill="#f87171" style="vertical-align:-2px;margin-right:3px;"><circle cx="12" cy="12" r="10"/></svg>Live</div>
    <div class="stab" onclick="switchTab('contacts')" id="tab-contacts"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" style="vertical-align:-2px;margin-right:3px;"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>Kontak</div>
  </div>
  <div class="search-wrap" id="search-wrap-el">
    <div class="search-inner">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
      <input type="text" id="search-input" placeholder="Cari..." oninput="filterList(this.value)">
    </div>
  </div>
  <div class="sb-panel active" id="panel-chats">
    <div id="chat-list"><div style="padding:28px;text-align:center;color:var(--st);">Memuat...</div></div>
  </div>
  <div class="sb-panel" id="panel-status">
    <div class="status-section-label">Status Saya</div>
    <div class="my-status-row" onclick="openMyStatus()">
      <div class="status-ring" id="my-status-ring">
        <div class="status-ring-inner" id="my-status-ring-av">__SIDEBAR_AV__</div>
        <div class="status-add-badge">+</div>
      </div>
      <div style="flex:1;"><div style="font-weight:800;font-size:14px;">Lihat / Tambah Status</div><div style="font-size:12px;color:var(--st);margin-top:2px;" id="my-status-hint">Ketuk untuk buat status</div></div>
    </div>
    <div class="status-section-label" id="friends-stat-label" style="display:none;">Status Teman</div>
    <div id="friends-status-list"></div>
    <div id="status-empty" style="display:none;padding:30px;text-align:center;color:var(--st);font-size:13px;">Belum ada status teman ðŸ‘€</div>
  </div>
  <div class="sb-panel" id="panel-live">
    <div style="padding:12px 14px;">
      <button onclick="startLiveStream()" style="width:100%;padding:12px;background:linear-gradient(135deg,#e53e3e,#c53030);color:#fff;border:none;border-radius:12px;font-size:14px;font-weight:900;cursor:pointer;">ðŸ”´ Mulai Live Streaming</button>
    </div>
    <div class="status-section-label">Live Sekarang</div>
    <div id="live-list"><div style="padding:24px;text-align:center;color:var(--st);font-size:13px;">Tidak ada siaran live ðŸ“º</div></div>
  </div>
  <div class="sb-panel" id="panel-contacts">
    <div id="contacts-list"><div style="padding:28px;text-align:center;color:var(--st);">Memuat...</div></div>
  </div>
</div>

<!-- MAIN PANEL -->
<div class="main" id="main-panel">
  <div class="no-chat" id="no-chat" style="display:flex;">
    <div class="no-chat-icon">ðŸ’¬</div>
    <h2>WaClone</h2>
    <p>Pilih kontak untuk mulai chat</p>
    <div style="margin-top:16px;display:flex;gap:10px;flex-wrap:wrap;justify-content:center;">
      <button onclick="openAI()" style="padding:10px 20px;background:linear-gradient(135deg,#7c3aed,#9b5de5);color:#fff;border:none;border-radius:20px;font-size:14px;font-weight:800;cursor:pointer;font-family:'Nunito',sans-serif;">ðŸ¤– Buka AI</button>
      <button onclick="switchTab('live')" style="padding:10px 20px;background:linear-gradient(135deg,#e53e3e,#c53030);color:#fff;border:none;border-radius:20px;font-size:14px;font-weight:800;cursor:pointer;font-family:'Nunito',sans-serif;"><svg viewBox="0 0 24 24" width="15" height="15" fill="#f87171" style="vertical-align:-2px;margin-right:3px;"><circle cx="12" cy="12" r="10"/></svg>Live</button>
    </div>
  </div>
  <div id="chat-wrap" style="display:none;flex-direction:column;height:100%;overflow:hidden;">
    <div class="chat-header" id="chat-header">
      <button class="back-btn" onclick="goBack()" id="back-btn">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>
      </button>
      <div id="header-av" onclick="showContactInfo()" style="width:40px;height:40px;border-radius:50%;overflow:hidden;flex-shrink:0;cursor:pointer;"></div>
      <div onclick="showContactInfo()" style="flex:1;min-width:0;max-width:calc(100% - 140px);overflow:hidden;cursor:pointer;padding:0 4px;">
        <div id="header-name" style="font-weight:900;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">â€”</div>
        <div id="header-status" style="font-size:11px;color:var(--g);"></div>
      </div>
      <div style="display:flex;align-items:center;gap:4px;flex-shrink:0;">
        <button class="header-btn call-btn-audio" onclick="startCall('audio')" title="Telepon">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
            <path d="M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z"/>
          </svg>
        </button>
        <button class="header-btn call-btn-video" onclick="startCall('video')" title="Video Call">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
            <path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/>
          </svg>
        </button>
        <button class="header-btn" onclick="showChatMenu(this)" title="Lainnya">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/></svg>
        </button>
      </div>
    </div>
    <div id="chat-more-menu" style="display:none;position:fixed;right:8px;top:62px;background:#202c33;border:1px solid #2a3942;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,.5);z-index:999;min-width:160px;overflow:hidden;">
      <div onclick="openAI();this.parentElement.style.display='none'" style="padding:13px 18px;cursor:pointer;font-size:14px;color:#e9edef;" onmouseover="this.style.background='#2a3942'" onmouseout="this.style.background=''">ðŸ¤– Tanya AI</div>
      <div onclick="searchInChat();this.parentElement.style.display='none'" style="padding:13px 18px;cursor:pointer;font-size:14px;color:#e9edef;" onmouseover="this.style.background='#2a3942'" onmouseout="this.style.background=''">ðŸ” Cari Pesan</div>
    </div>
    <div class="messages-area" id="messages-area"></div>
    <div class="typing-wrap">
      <div class="typing-dots" id="typing-dots">
        <div class="dot-anim"><span></span><span></span><span></span></div>
        <span class="typing-text" id="typing-text"></span>
      </div>
    </div>
    <div class="att-menu" id="att-menu">
      <div class="att-opt" onclick="triggerFile('photo')"><div class="att-ic" style="background:#1a56db22;">ðŸ“·</div><span class="att-lbl">Foto/Video</span></div>
      <div class="att-opt" onclick="triggerFile('doc')"><div class="att-ic" style="background:#7c3aed22;">ðŸ“„</div><span class="att-lbl">Dokumen</span></div>
      <div class="att-opt" onclick="openCameraChat()"><div class="att-ic" style="background:#05966922;">ðŸ“¸</div><span class="att-lbl">Kamera</span></div>
    </div>
    <input type="file" id="file-photo" style="display:none" accept="image/*,video/*" onchange="handleUpload(this)">
    <input type="file" id="file-doc" style="display:none" accept=".pdf,.txt,.doc,.docx,.xls,.xlsx,.zip,.rar" onchange="handleUpload(this)">
    <div class="emoji-picker" id="emoji-picker"><div class="emoji-grid" id="emoji-grid"></div></div>
    <div class="upload-progress" id="upload-progress"><div class="upload-fill" id="upload-fill"></div></div>
    <div class="input-area">
      <div class="reply-preview" id="reply-preview">
        <div style="flex:1;min-width:0;"><div class="rp-name" id="rp-name"></div><div class="rp-text" id="rp-text"></div></div>
        <button class="rp-close" onclick="cancelReply()">Ã—</button>
      </div>
      <div class="input-row">
        <button class="side-btn" onclick="toggleAttMenu()" title="Lampiran">
          <svg width="21" height="21" viewBox="0 0 24 24" fill="currentColor"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/></svg>
        </button>
        <button class="side-btn" onclick="toggleEmojiPicker()" title="Emoji" style="font-size:20px;line-height:1;">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" style="opacity:.7;"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm3.5-9c.83 0 1.5-.67 1.5-1.5S16.33 8 15.5 8 14 8.67 14 9.5s.67 1.5 1.5 1.5zm-7 0c.83 0 1.5-.67 1.5-1.5S9.33 8 8.5 8 7 8.67 7 9.5 7.67 11 8.5 11zm3.5 6.5c2.33 0 4.31-1.46 5.11-3.5H6.89c.8 2.04 2.78 3.5 5.11 3.5z"/></svg>
        </button>
        <textarea id="msg-input" class="msg-textarea" rows="1" placeholder="Ketik pesan..." onkeydown="handleMsgKey(event)" oninput="onMsgInput(this)"></textarea>
        <button class="rec-btn" id="rec-btn" onmousedown="startVoice()" onmouseup="stopVoice()" ontouchstart="startVoice(event)" ontouchend="stopVoice(event)" title="Tahan rekam">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg>
        </button>
        <button class="send-btn" onclick="sendMessage()">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="white"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
      </div>
    </div>
  </div>
</div>

<!-- CONTEXT MENU -->
<div class="ctx-menu" id="ctx-menu">
  <div class="ctx-item" onclick="doReply()">â†©ï¸ Balas</div>
  <div class="ctx-item" onclick="doCopy()">ðŸ“‹ Salin</div>
  <div class="ctx-item" onclick="doForward()">â†ªï¸ Teruskan</div>
  <div class="ctx-item" onclick="askAIAboutMsg()">ðŸ¤– Tanya AI</div>
  <div class="ctx-item danger" onclick="doDelete()">ðŸ—‘ï¸ Hapus</div>
</div>

<!-- AI DRAWER -->
<div class="ai-drawer" id="ai-drawer">
  <div class="ai-drawer-header">
    <div style="width:38px;height:38px;border-radius:50%;background:linear-gradient(135deg,#7c3aed,#9b5de5);display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;">ðŸ¤–</div>
    <div style="flex:1;margin-left:10px;"><div style="font-weight:900;font-size:16px;color:#e0d4ff;">WaClone AI</div><div style="font-size:11px;color:rgba(224,212,255,.5);">Asisten pintarmu</div></div>
    <button style="background:rgba(255,255,255,.08);border:none;color:rgba(224,212,255,.6);width:30px;height:30px;border-radius:50%;font-size:16px;cursor:pointer;" onclick="closeAI()">Ã—</button>
  </div>
  <div class="ai-messages" id="ai-messages">
    <div class="ai-msg ai"><div class="ai-msg-av">ðŸ¤–</div><div class="ai-bubble">Halo! Saya <b>WaClone AI</b> ðŸ‘‹<br><br>Saya bisa bantu menulis pesan, menjawab pertanyaan, atau menerjemahkan teks.<br><br>Ada yang bisa saya bantu?</div></div>
  </div>
  <div class="ai-chips" id="ai-chips">
    <div class="ai-chip" onclick="sendAIMsg('Bantu saya menulis pesan yang baik')">âœï¸ Tulis pesan</div>
    <div class="ai-chip" onclick="sendAIMsg('Buat lelucon lucu untuk teman')">ðŸ˜‚ Lelucon</div>
    <div class="ai-chip" onclick="sendAIMsg('Terjemahkan ke Inggris: Halo, apa kabar?')">ðŸŒ Terjemah</div>
  </div>
  <div class="ai-input-row">
    <textarea class="ai-textarea" id="ai-input" rows="1" placeholder="Tanya AI apapun..." onkeydown="handleAIKey(event)" oninput="autoResizeAI(this)"></textarea>
    <button class="ai-send-btn" onclick="sendAIFromInput()">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="white"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
    </button>
  </div>
</div>

<!-- OVERLAYS -->
<div class="overlay" id="prof-ov">
  <div class="panel">
    <div class="panel-header"><h2>ðŸ‘¤ Profil Saya</h2><button class="close-btn" onclick="closePanel('prof-ov')">Ã—</button></div>
    <div class="panel-body">
      <div class="pav-wrap">
        <div class="pav-big" id="pav-big" onclick="document.getElementById('avatar-input').click()">__PROFILE_AV__</div>
        <div class="pav-edit-btn" onclick="document.getElementById('avatar-input').click()">ðŸ“·</div>
        <input type="file" id="avatar-input" style="display:none" accept="image/*" onchange="uploadAvatar(this)">
      </div>
      <div class="prof-name" id="pname">__USERNAME__</div>
      <div class="prof-email">__EMAIL__</div>
      <div style="margin-top:16px;">
        <div class="field-group"><label>Username</label><input id="edit-username" value="__USERNAME__"></div>
        <div class="field-group"><label>Bio</label><textarea id="edit-bio">__BIO__</textarea></div>
      </div>
      <button class="save-btn" onclick="saveProfile()">ðŸ’¾ Simpan Profil</button>
      <button class="logout-btn" onclick="doLogout()">ðŸšª Logout</button>
    </div>
  </div>
</div>

<div class="overlay" id="settings-ov">
  <div class="panel" style="width:440px;">
    <div class="panel-header"><h2>âš™ï¸ Pengaturan</h2><button class="close-btn" onclick="closePanel('settings-ov')">Ã—</button></div>
    <div class="panel-body">
      <div style="margin-bottom:18px;"><div style="font-size:11px;font-weight:800;color:var(--g);text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px;padding-bottom:5px;border-bottom:1px solid var(--bd);"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" style="vertical-align:-2px;margin-right:3px;"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>Chat</div>
        <div style="display:flex;align-items:center;justify-content:space-between;padding:9px 0;">
          <div><div style="font-size:13px;font-weight:700;">Enter untuk Kirim</div></div>
          <label style="position:relative;width:44px;height:24px;flex-shrink:0;"><input type="checkbox" id="set-enter-send" checked onchange="saveSetting('enter_send',this.checked)" style="opacity:0;width:0;height:0;"><span style="position:absolute;inset:0;background:var(--bd);border-radius:24px;cursor:pointer;transition:.3s;"><span style="position:absolute;width:18px;height:18px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.3s;"></span></span></label>
        </div>
      </div>
      <div><div style="font-size:11px;font-weight:800;color:var(--g);text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px;padding-bottom:5px;border-bottom:1px solid var(--bd);">ðŸ—‘ï¸ Data</div>
        <div style="display:flex;align-items:center;justify-content:space-between;padding:9px 0;">
          <div><div style="font-size:13px;font-weight:700;">Hapus Cache Lokal</div></div>
          <button onclick="clearLocalCache()" style="padding:7px 14px;background:var(--dk);border:1.5px solid var(--bd);border-radius:8px;color:var(--tx);font-size:12px;font-weight:700;cursor:pointer;">ðŸ—‘ï¸ Hapus</button>
        </div>
        <div style="display:flex;align-items:center;justify-content:space-between;padding:9px 0;">
          <div><div style="font-size:13px;font-weight:700;">Versi</div></div>
          <span style="font-size:12px;color:var(--g);font-weight:700;">v4.0 â€¢ Cloudinary + Supabase</span>
        </div>
      </div>
    </div>
  </div>
</div>

<div class="overlay" id="notif-ov">
  <div class="panel">
    <div class="panel-header"><h2>ðŸ”” Notifikasi</h2><button class="close-btn" onclick="closePanel('notif-ov');markNotifsRead()">Ã—</button></div>
    <div class="panel-body" id="notif-list"></div>
  </div>
</div>

<div class="overlay" id="stview-ov">
  <div class="stv" id="stv-wrap">
    <div class="stv-progress" id="stv-progress"></div>
    <div class="stv-head">
      <div class="stv-av" id="stv-av"></div>
      <div style="flex:1;"><div style="font-weight:800;font-size:14px;color:#fff;" id="stv-name"></div><div style="font-size:11px;color:rgba(255,255,255,.5);" id="stv-time"></div></div>
      <button class="close-btn" onclick="closeStatusViewer()" style="background:rgba(255,255,255,.1);color:rgba(255,255,255,.7);">Ã—</button>
    </div>
    <div class="stv-body" id="stv-body"></div>
    <div class="stv-nav-btns">
      <button class="stv-nav-btn" id="stv-prev-btn" onclick="prevStatus()">â—€ Prev</button>
      <button class="stv-nav-btn" id="stv-next-btn" onclick="nextStatus()">Next â–¶</button>
    </div>
  </div>
</div>

<div class="overlay" id="cstat-ov">
  <div class="panel">
    <div class="panel-header"><h2>âœï¸ Buat Status</h2><button class="close-btn" onclick="closePanel('cstat-ov')">Ã—</button></div>
    <div class="panel-body">
      <div style="display:flex;flex-direction:column;gap:8px;">
        <div onclick="showTextStatusForm()" style="display:flex;align-items:center;gap:12px;padding:11px;background:var(--dk);border-radius:10px;border:1.5px solid var(--bd);cursor:pointer;">
          <div style="width:42px;height:42px;border-radius:50%;background:#2563eb22;display:flex;align-items:center;justify-content:center;font-size:19px;">âœï¸</div>
          <div><div style="font-weight:800;">Teks</div></div>
        </div>
        <div onclick="document.getElementById('stat-photo-in').click()" style="display:flex;align-items:center;gap:12px;padding:11px;background:var(--dk);border-radius:10px;border:1.5px solid var(--bd);cursor:pointer;">
          <div style="width:42px;height:42px;border-radius:50%;background:#dc262622;display:flex;align-items:center;justify-content:center;font-size:19px;">ðŸ–¼ï¸</div>
          <div><div style="font-weight:800;">Foto</div></div>
        </div>
        <div onclick="document.getElementById('stat-video-in').click()" style="display:flex;align-items:center;gap:12px;padding:11px;background:var(--dk);border-radius:10px;border:1.5px solid var(--bd);cursor:pointer;">
          <div style="width:42px;height:42px;border-radius:50%;background:#7c3aed22;display:flex;align-items:center;justify-content:center;font-size:19px;">ðŸŽ¥</div>
          <div><div style="font-weight:800;">Video</div></div>
        </div>
      </div>
      <input type="file" id="stat-photo-in" accept="image/*" style="display:none" onchange="uploadStatus(this,'image')">
      <input type="file" id="stat-video-in" accept="video/*" style="display:none" onchange="uploadStatus(this,'video')">
      <div id="text-stat-form" style="display:none;margin-top:14px;">
        <div class="field-group"><label>Teks Status</label><textarea id="stat-text-inp" placeholder="Tulis status kamu..." style="height:88px;" maxlength="200"></textarea></div>
        <button class="save-btn" onclick="postTextStatus()">ðŸ“¤ Posting Status</button>
      </div>
    </div>
  </div>
</div>

<div class="overlay" id="cam-ov">
  <div class="panel" style="width:420px;">
    <div class="panel-header"><h2>ðŸ“· Kamera</h2><button class="close-btn" onclick="closeCamera()">Ã—</button></div>
    <div class="panel-body">
      <div class="cam-wrap"><video id="cam-vid" autoplay playsinline muted></video></div>
      <canvas id="cam-canvas" style="display:none;width:100%;border-radius:10px;margin-top:8px;"></canvas>
      <div class="cam-controls">
        <button class="cam-btn" style="background:var(--g);" onclick="snapPhoto()">ðŸ“¸</button>
        <button class="cam-btn" style="background:#2a3942;" onclick="switchCamFacing()">ðŸ”„</button>
        <button class="cam-btn" style="background:var(--rd);" onclick="closeCamera()">Ã—</button>
      </div>
      <div id="cam-send-wrap" style="display:none;margin-top:10px;">
        <button class="save-btn" onclick="sendCamPhoto()">ðŸ“¤ Kirim Foto</button>
      </div>
    </div>
  </div>
</div>

<div class="overlay" id="fw-ov">
  <div class="panel">
    <div class="panel-header"><h2>â†ªï¸ Teruskan Pesan</h2><button class="close-btn" onclick="closePanel('fw-ov')">Ã—</button></div>
    <div class="panel-body">
      <div class="fw-list" id="fw-list"></div>
      <button class="save-btn" id="fw-send-btn" style="display:none;margin-top:12px;" onclick="execForward()">ðŸ“¤ Kirim</button>
    </div>
  </div>
</div>

<div class="overlay" id="img-ov" onclick="closePanel('img-ov')">
  <img class="img-fullview" id="img-full" src="" alt="">
</div>

<!-- CALL UI -->
<div class="call-ui" id="call-ui">
  <div class="call-video-grid" id="call-video-grid">
    <div id="agora-remote">
      <div style="text-align:center;">
        <div style="font-size:48px;margin-bottom:8px;">ðŸ‘¤</div>
        <div style="font-size:13px;">Menunggu video...</div>
      </div>
    </div>
    <div id="agora-local"></div>
  </div>
  <div class="audio-call-info" id="audio-call-info">
    <div class="call-person-av" id="call-av">ðŸ‘¤</div>
    <div class="call-name" id="call-name">â€”</div>
    <div class="call-status-txt" id="call-status-txt">Memanggil...</div>
    <div class="call-timer" id="call-timer">00:00</div>
  </div>
  <div class="call-controls">
    <button class="ccbtn btn-toggle on" id="ccbtn-mic" onclick="toggleMic()">
      <svg width="26" height="26" viewBox="0 0 24 24" fill="white"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg>
      <span>Mic</span>
    </button>
    <button class="ccbtn btn-toggle on" id="ccbtn-cam" onclick="toggleCam()">
      <svg width="26" height="26" viewBox="0 0 24 24" fill="white"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg>
      <span>Kamera</span>
    </button>
    <button class="ccbtn btn-end" onclick="endCall()">
      <svg width="26" height="26" viewBox="0 0 24 24" fill="white"><path d="M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z"/></svg>
      <span>Tutup</span>
    </button>
    <button class="ccbtn btn-toggle on" id="ccbtn-spk" onclick="toggleSpeaker()">
      <svg width="26" height="26" viewBox="0 0 24 24" fill="white"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>
      <span>Speaker</span>
    </button>
  </div>
</div>

<!-- Incoming Call -->
<div class="incoming-call" id="incoming-call">
  <div class="inc-av" id="inc-av">ðŸ‘¤</div>
  <div style="text-align:center;font-size:17px;font-weight:900;" id="inc-name">â€”</div>
  <div style="text-align:center;font-size:12px;color:var(--st);margin-top:4px;" id="inc-type">ðŸ“ž Panggilan Masuk</div>
  <div class="inc-actions">
    <button class="inc-btn inc-accept" onclick="answerCall('audio')">ðŸ“ž Audio</button>
    <button class="inc-btn inc-video" onclick="answerCall('video')">ðŸ“¹ Video</button>
    <button class="inc-btn inc-reject" onclick="rejectCall()">ðŸ“µ</button>
  </div>
</div>

<!-- LIVE UI -->
<div class="live-ui" id="live-ui">
  <div class="live-header">
    <div style="display:flex;align-items:center;gap:10px;">
      <div class="live-badge" id="live-badge">â— LIVE</div>
      <div style="background:rgba(0,0,0,.6);color:#fff;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:700;" id="live-viewer-count">ðŸ‘ 0 penonton</div>
    </div>
    <div style="display:flex;align-items:center;gap:8px;">
      <span id="live-streamer-name" style="color:#fff;font-size:14px;font-weight:700;"></span>
      <button onclick="closeLiveUI()" style="background:rgba(255,255,255,.15);border:none;color:#fff;width:32px;height:32px;border-radius:50%;font-size:18px;cursor:pointer;">Ã—</button>
    </div>
  </div>
  <div class="live-video-area">
    <div id="live-local-video"></div>
    <div id="live-remote-video"></div>
    <div class="live-comments" id="live-comments"></div>
  </div>
  <div class="live-controls-bottom">
    <input type="text" class="live-comment-input" id="live-comment-input" placeholder="Tulis komentar..." onkeydown="if(event.key==='Enter')sendLiveComment()">
    <button class="live-send-comment" onclick="sendLiveComment()">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="white"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
    </button>
    <button id="live-end-btn" onclick="endLiveStream()" style="display:none;padding:9px 18px;background:#e53e3e;color:#fff;border:none;border-radius:20px;font-size:13px;font-weight:800;cursor:pointer;">â¹ Akhiri</button>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// ============================================================
// CONFIG
// ============================================================
const AGORA_APP_ID = "__AGORA_APP_ID__";
const ME = { uid: "__UID__", username: "__USERNAME__" };
const EMOJIS = ['ðŸ˜€','ðŸ˜‚','ðŸ˜','ðŸ¥°','ðŸ˜Ž','ðŸ¤“','ðŸ˜­','ðŸ˜¡','ðŸ‘','ðŸ‘Ž','â¤ï¸','ðŸ”¥','âœ…','â­','ðŸŽ‰','ðŸ™','ðŸ’ª','ðŸ˜´','ðŸ¤£','ðŸ˜Š','ðŸ˜˜','ðŸ¤—','ðŸ¥º','ðŸ˜…','ðŸ˜¬','ðŸ¤™','ðŸ‘€','ðŸ’‹','ðŸ«‚','ðŸŒŸ','ðŸ’¯','ðŸŽŠ','ðŸ˜','ðŸ˜±','ðŸ¤¯','ðŸ«¡','ðŸ¥³','ðŸ˜¤','ðŸ«¶','ðŸ‘‹','ðŸ™Œ','ðŸ‘€','ðŸŽµ','ðŸŒˆ','ðŸ•','â˜•','ðŸš€','ðŸ’¡','ðŸŽ¯','ðŸ†','ðŸ’Ž','ðŸŒ¸','ðŸ¦‹','ðŸŒ™','â˜€ï¸','ðŸŒŠ','ðŸ€','ðŸ¶','ðŸ±','ðŸ¦','ðŸ»','ðŸ¦Š','ðŸ¼','ðŸ¨','ðŸ¦„'];

let allUsers=[], currentFriend=null, pollTimer=null;
let replyData=null, ctxMsgData=null;
let mediaRecorder=null, recChunks=[], isRecording=false;
let callTimerInt=null, callSecs=0, micMuted=false, camOff=false, speakerOff=false;
let incCallInfo=null;
let camStream=null, camFacing='user', camMode='chat', camPhotoBlob=null;
let stvData=null, stvIdx=0, stvTimerInt=null;
let fwText='', fwTargetUid=null;
let lastTypingPing=0;
let aiHistory=[];
let agoraClient=null, agoraLocalAudioTrack=null, agoraLocalVideoTrack=null;
let agoraCurrentCallId=null, currentCallType='audio';
let agoraLiveClient=null, agoraLiveLocalVideoTrack=null, agoraLiveLocalAudioTrack=null;
let isLiveHost=false, liveChannelName='', liveCommentPollTimer=null;
let appSettings={enter_send:true};

// ============================================================
// UTILS
// ============================================================
function toast(msg,dur=2500,isErr=false){
  const t=document.getElementById('toast');t.textContent=msg;t.className='toast show'+(isErr?' err':'');
  setTimeout(()=>t.classList.remove('show'),dur);
}
function escHtml(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function fmtTime(ts){
  if(!ts||ts==0)return'';
  const ms=ts>9999999999?ts:ts*1000;
  const d=new Date(ms),now=new Date();
  if(isNaN(d.getTime()))return'';
  if(d.toDateString()===now.toDateString())return d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0');
  const diff=Math.floor((now-d)/86400000);
  if(diff===1)return'Kemarin';
  if(diff<7)return['Min','Sen','Sel','Rab','Kam','Jum','Sab'][d.getDay()];
  return d.getDate()+'/'+(d.getMonth()+1);
}
function makeAv(u,size=48){
  if(u&&u.avatar)return`<img src="${u.avatar}" style="width:${size}px;height:${size}px;border-radius:50%;object-fit:cover;" onerror="this.style.display='none'">`;
  const n=(u&&(u.username||u.name))||'?';
  const pal=['#00a884','#7c3aed','#1a56db','#dc2626','#d97706','#059669','#0891b2','#be185d'];
  const bg=pal[(n.charCodeAt(0)||0)%pal.length];
  const fs=Math.floor(size*0.42);
  return`<div style="width:${size}px;height:${size}px;border-radius:50%;background:${bg};display:flex;align-items:center;justify-content:center;font-weight:900;font-size:${fs}px;color:#fff;flex-shrink:0;">${n[0].toUpperCase()}</div>`;
}
function loadSettings(){try{const s=JSON.parse(localStorage.getItem('wc_settings')||'{}');Object.assign(appSettings,s);}catch(e){}}
function saveSetting(k,v){appSettings[k]=v;try{localStorage.setItem('wc_settings',JSON.stringify(appSettings));}catch(e){}}
function clearLocalCache(){try{const s=localStorage.getItem('wc_settings');localStorage.clear();if(s)localStorage.setItem('wc_settings',s);toast('Cache dibersihkan âœ…');}catch(e){}}

// ============================================================
// PANELS / TABS
// ============================================================
function openPanel(id){document.getElementById(id).classList.add('open');}
function closePanel(id){document.getElementById(id).classList.remove('open');}
function openNotifPanel(){openPanel('notif-ov');loadNotifications();}
function switchTab(tab){
  ['chats','status','live','contacts'].forEach(t=>{
    document.getElementById('tab-'+t)?.classList.toggle('active',t===tab);
    document.getElementById('panel-'+t)?.classList.toggle('active',t===tab);
  });
  document.getElementById('search-wrap-el').style.display=(tab==='status'||tab==='live')?'none':'';
  if(tab==='status')loadSidebarStatuses();
  if(tab==='live')loadLiveList();
}
function closeAllMenus(){
  document.getElementById('att-menu').classList.remove('open');
  document.getElementById('emoji-picker').classList.remove('open');
  document.getElementById('ctx-menu').style.display='none';
}

// ============================================================
// USERS
// ============================================================
async function loadUsers(){
  try{const r=await fetch('/api/users');const d=await r.json();allUsers=d.users||[];renderChatList();renderContactsList();checkNotifCount();}catch(e){}
}
function renderChatList(){
  const el=document.getElementById('chat-list');
  const others=allUsers.filter(u=>u.uid!==ME.uid);
  if(!others.length){el.innerHTML='<div style="padding:28px;text-align:center;color:var(--st);">Belum ada pengguna ðŸ‘¥</div>';return;}
  el.innerHTML=others.map(u=>chatItemHtml(u)).join('');
}
function renderContactsList(){
  const el=document.getElementById('contacts-list');
  const sorted=[...allUsers.filter(u=>u.uid!==ME.uid)].sort((a,b)=>a.username.localeCompare(b.username));
  if(!sorted.length){el.innerHTML='<div style="padding:28px;text-align:center;color:var(--st);">Tidak ada kontak</div>';return;}
  el.innerHTML=sorted.map(u=>chatItemHtml(u,true)).join('');
}
function chatItemHtml(u,isContact=false){
  const av=makeAv(u,48);
  const onlineDot=u.online?'<div class="online-dot"></div>':'';
  const preview=escHtml((isContact?(u.bio||'Tap untuk chat'):(u.last_msg||u.bio||'Tap untuk chat')).substring(0,40));
  const tm=u.last_time?fmtTime(u.last_time):'';
  const badge=u.unread_count>0?`<div class="unread-badge">${u.unread_count>99?'99+':u.unread_count}</div>`:'';
  const isActive=currentFriend&&currentFriend.uid===u.uid;
  const su=(u.username||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'");
  const sa=(u.avatar||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'");
  const sb=(u.bio||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'");
  return`<div class="chat-item${isActive?' active':''}" data-uid="${u.uid}" data-name="${escHtml(u.username)}"
    onclick="openChat('${u.uid}','${su}','${sa}','${sb}')">
    <div class="chat-av">${av}${onlineDot}</div>
    <div class="chat-info"><div class="chat-name">${escHtml(u.username)}</div><div class="chat-prev">${preview}</div></div>
    <div class="chat-meta"><div class="chat-time">${tm}</div>${badge}</div>
  </div>`;
}
function filterList(q){
  const q2=q.toLowerCase();
  document.querySelectorAll('.chat-item').forEach(el=>{el.style.display=el.dataset.name.toLowerCase().includes(q2)?'':'none';});
}

// ============================================================
// OPEN CHAT
// ============================================================
function openChat(uid,name,avatar,bio){
  currentFriend={uid,name,avatar,bio};
  document.getElementById('no-chat').style.display='none';
  document.getElementById('chat-wrap').style.display='flex';
  if(window.innerWidth<=700)document.getElementById('sidebar').classList.add('hidden');
  document.getElementById('header-av').innerHTML=makeAv(currentFriend,40);
  document.getElementById('header-name').textContent=name;
  document.getElementById('header-status').textContent='Memuat...';
  document.querySelectorAll('.chat-item').forEach(e=>e.classList.toggle('active',e.dataset.uid===uid));
  cancelReply();closeAllMenus();
  loadMessages();
  if(pollTimer)clearInterval(pollTimer);
  pollTimer=setInterval(()=>{loadMessages();checkTyping();},3000);
  fetch('/api/mark_read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({friend_uid:uid})});
  setTimeout(()=>document.getElementById('msg-input').focus(),100);
}
function showChatMenu(btn){
  const menu=document.getElementById('chat-more-menu');
  if(menu.style.display==='block'){menu.style.display='none';return;}
  const rect=btn.getBoundingClientRect();
  menu.style.display='block';menu.style.top=(rect.bottom+4)+'px';menu.style.right=(window.innerWidth-rect.right)+'px';menu.style.left='auto';
  setTimeout(()=>document.addEventListener('click',()=>menu.style.display='none',{once:true}),50);
}
function showContactInfo(){
  if(!currentFriend)return;
  const u=allUsers.find(x=>x.uid===currentFriend.uid);
  toast((u?.username||currentFriend.name)+' â€” '+(u?.bio||'No bio'),3000);
}
function searchInChat(){
  const q=prompt('Cari teks:');if(!q)return;let found=0;
  document.querySelectorAll('.bubble span').forEach(el=>{
    const match=el.textContent.toLowerCase().includes(q.toLowerCase());
    el.parentElement.style.outline=match?'2px solid var(--g)':'none';if(match)found++;
  });
  toast(found>0?found+' pesan ditemukan':'Tidak ditemukan',2000,found===0);
}
function goBack(){
  const openOvs=[...document.querySelectorAll('.overlay.open')];
  if(openOvs.length){openOvs[openOvs.length-1].classList.remove('open');if(openOvs[openOvs.length-1].id==='stview-ov')clearStvTimer();return;}
  if(document.getElementById('ai-drawer').classList.contains('open')){closeAI();return;}
  if(currentFriend){
    document.getElementById('sidebar').classList.remove('hidden');
    document.getElementById('chat-wrap').style.display='none';
    document.getElementById('no-chat').style.display='flex';
    currentFriend=null;if(pollTimer){clearInterval(pollTimer);pollTimer=null;}
  }
}

// ============================================================
// MESSAGES
// ============================================================
async function loadMessages(){
  if(!currentFriend)return;
  try{
    const r=await fetch(`/api/messages?friend_uid=${currentFriend.uid}`);const d=await r.json();
    renderMessages(d.messages||[]);
    const f=allUsers.find(u=>u.uid===currentFriend.uid);
    if(f){const st=document.getElementById('header-status');st.textContent=f.online?'ðŸŸ¢ Online':(f.last_seen?`Terakhir ${fmtTime(f.last_seen)}`:'âš« Offline');}
  }catch(e){}
}
function renderMessages(msgs){
  const area=document.getElementById('messages-area');
  const atBottom=area.scrollHeight-area.clientHeight<=area.scrollTop+120;
  if(!msgs.length){area.innerHTML='<div style="text-align:center;color:var(--st);padding:36px;font-size:13px;">Mulai percakapan! ðŸ‘‹</div>';return;}
  let html='',lastDate='';
  msgs.forEach(m=>{
    const ts_val=m.created_at||m.time||0; const d=new Date(ts_val>9999999999?ts_val:ts_val*1000);
    const ds=(!isNaN(d.getTime()))?d.toLocaleDateString('id-ID',{day:'2-digit',month:'long',year:'numeric'}):'Tanggal tidak diketahui';
    if(ds!==lastDate){html+=`<div class="date-divider"><span>${ds}</span></div>`;lastDate=ds;}
    const isOut=m.from_uid===ME.uid;
    const tstr=(!isNaN(d.getTime()))?d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0'):'--:--';
    let tick='';
    if(isOut){
      const dbl='<svg viewBox="0 0 16 11" width="16" height="11"><path d="M15.01 3.316l-.478-.372a.365.365 0 0 0-.51.063L8.666 9.88a.32.32 0 0 1-.484.032l-.358-.325a.32.32 0 0 0-.484.032l-.378.48a.418.418 0 0 0 .036.541l1.316 1.266c.143.14.361.125.484-.033l6.272-8.048a.366.366 0 0 0-.064-.512z" fill="currentColor"/><path d="M7.434 4.814l-4.405 5.026-.655-.63L7.434 4.814z" fill="currentColor"/></svg>';
      const sgl='<svg viewBox="0 0 12 11" width="12" height="11"><path d="M11.01 3.316l-.478-.372a.365.365 0 0 0-.51.063L4.666 9.88a.32.32 0 0 1-.484.032l-2.36-2.342a.32.32 0 0 0-.484.032l-.378.48a.418.418 0 0 0 .036.541l2.956 2.921c.143.14.361.125.484-.033l6.272-8.048a.366.366 0 0 0-.064-.512z" fill="currentColor"/></svg>';
      if(m.status==='read')tick=`<span class="tick read">${dbl}</span>`;
      else tick=`<span class="tick">${sgl}</span>`;
    }
    let rqHtml='';
    if(m.reply_to&&m.reply_to.text){
      const rs=m.reply_to.from_uid===ME.uid?'Kamu':(currentFriend?currentFriend.name:'?');
      rqHtml=`<div class="reply-quote"><div class="rq-name">${escHtml(rs)}</div><div class="rq-text">${escHtml(m.reply_to.text)}</div></div>`;
    }
    let content='';
    if(m.file_url){
      const ft=m.file_type||'';
      if(ft.startsWith('image/')||/\.(jpg|jpeg|png|gif|webp|bmp)$/i.test(m.file_url))
        content+=`<img src="${m.file_url}" onclick="viewImg('${m.file_url}')" loading="lazy" alt="foto">`;
      else if(ft.startsWith('video/')||/\.(mp4|webm|mov|avi|mkv)$/i.test(m.file_url))
        content+=`<video src="${m.file_url}" controls style="max-width:250px;border-radius:8px;display:block;margin-bottom:3px;"></video>`;
      else if(ft.startsWith('audio/')||/\.(ogg|m4a|wav|mp3|webm)$/i.test(m.file_url))
        content+=`<audio src="${m.file_url}" controls></audio>`;
      else{const fn=m.file_url.split('/').pop().split('?')[0].substring(0,30);content+=`<a class="file-link" href="${m.file_url}" target="_blank">ðŸ“„ ${escHtml(fn)}</a>`;}
    }
    if(m.message)content+=`<span>${escHtml(m.message)}</span>`;
    const safeTxt=(m.message||'').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/\\/g,'\\\\');
    const acts=`<div class="msg-actions">
      <button class="act-btn" onclick='setReply("${m.id}","${safeTxt}","${m.from_uid}")'>â†©</button>
      <button class="act-btn" onclick='showCtxMenu(event,"${m.id}","${safeTxt}","${m.from_uid}")'>â‹¯</button>
    </div>`;
    html+=`<div class="msg-row ${isOut?'out':'in'}" data-id="${m.id}" data-txt="${safeTxt}" data-from="${m.from_uid}"
      oncontextmenu='showCtxMenu(event,"${m.id}","${safeTxt}","${m.from_uid}")'
      ontouchstart='touchStart(event,"${m.id}","${safeTxt}","${m.from_uid}")'
      ontouchend='touchEnd()'>
      ${isOut?acts:''}
      <div class="bubble">${rqHtml}${content}<div class="bubble-time">${tstr} ${tick}</div></div>
      ${!isOut?acts:''}
    </div>`;
  });
  area.innerHTML=html;
  if(atBottom)area.scrollTop=area.scrollHeight;
}

// ============================================================
// SEND
// ============================================================
function handleMsgKey(e){if(e.key==='Enter'&&!e.shiftKey&&appSettings.enter_send){e.preventDefault();sendMessage();}}
function onMsgInput(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,120)+'px';pingTyping();}
async function sendMessage(){
  const inp=document.getElementById('msg-input');const text=inp.value.trim();
  if(!text||!currentFriend)return;
  inp.value='';inp.style.height='auto';
  const body={to_uid:currentFriend.uid,message:text};
  if(replyData)body.reply_to={id:replyData.id,text:replyData.text,from_uid:replyData.from};
  cancelReply();
  try{const r=await fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(d.ok)loadMessages();else toast('Gagal kirim',2500,true);}catch(e){toast('Gagal kirim',2500,true);}
}

// ============================================================
// REPLY / CTX
// ============================================================
function cancelReply(){replyData=null;document.getElementById('reply-preview').classList.remove('show');}
function setReply(id,txt,from){
  const decoded=txt.replace(/&#39;/g,"'").replace(/&quot;/g,'"');
  replyData={id,text:decoded,from};
  const name=from===ME.uid?'Kamu':(currentFriend?currentFriend.name:'?');
  document.getElementById('rp-name').textContent=name;
  document.getElementById('rp-text').textContent=decoded||'Media';
  document.getElementById('reply-preview').classList.add('show');
  document.getElementById('msg-input').focus();
}
let touchTimer=null;
function showCtxMenu(e,id,txt,from){e.preventDefault();e.stopPropagation();ctxMsgData={id,txt:txt.replace(/&#39;/g,"'").replace(/&quot;/g,'"'),from};posCtx(e.clientX,e.clientY);}
function posCtx(x,y){const m=document.getElementById('ctx-menu');m.style.display='block';const mw=m.offsetWidth||180,mh=m.offsetHeight||200;m.style.left=Math.min(x,window.innerWidth-mw-8)+'px';m.style.top=Math.min(y,window.innerHeight-mh-8)+'px';setTimeout(()=>document.addEventListener('click',()=>m.style.display='none',{once:true}),50);}
function touchStart(e,id,txt,from){touchTimer=setTimeout(()=>{ctxMsgData={id,txt,from};posCtx(e.touches[0].clientX,e.touches[0].clientY);},600);}
function touchEnd(){if(touchTimer){clearTimeout(touchTimer);touchTimer=null;}}
function doReply(){if(!ctxMsgData)return;setReply(ctxMsgData.id,ctxMsgData.txt,ctxMsgData.from);document.getElementById('ctx-menu').style.display='none';}
function doCopy(){if(!ctxMsgData)return;navigator.clipboard.writeText(ctxMsgData.txt).then(()=>toast('Disalin ðŸ“‹'));document.getElementById('ctx-menu').style.display='none';}
function doForward(){
  if(!ctxMsgData)return;fwText=ctxMsgData.txt;fwTargetUid=null;
  document.getElementById('fw-list').innerHTML=allUsers.filter(u=>u.uid!==ME.uid).map(u=>`<div class="fw-item" id="fw-${u.uid}" onclick="selFw('${u.uid}')"><div class="fw-av">${makeAv(u,36)}</div><span style="font-weight:700;">${escHtml(u.username)}</span></div>`).join('');
  document.getElementById('fw-send-btn').style.display='none';openPanel('fw-ov');document.getElementById('ctx-menu').style.display='none';
}
function askAIAboutMsg(){if(!ctxMsgData)return;const msg=ctxMsgData.txt;document.getElementById('ctx-menu').style.display='none';openAI();setTimeout(()=>{const inp=document.getElementById('ai-input');inp.value=`Bantu saya membalas pesan ini: "${msg}"`;autoResizeAI(inp);},300);}
function selFw(uid){document.querySelectorAll('.fw-item').forEach(e=>e.classList.remove('sel'));document.getElementById('fw-'+uid).classList.add('sel');fwTargetUid=uid;document.getElementById('fw-send-btn').style.display='block';}
async function execForward(){
  if(!fwTargetUid||!fwText)return;
  const r=await fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to_uid:fwTargetUid,message:'â†ªï¸ '+fwText})});
  const d=await r.json();if(d.ok){toast('Diteruskan');closePanel('fw-ov');}else toast('Gagal',2500,true);
}
async function doDelete(){
  if(!ctxMsgData||!currentFriend)return;document.getElementById('ctx-menu').style.display='none';if(!confirm('Hapus pesan ini?'))return;
  const r=await fetch('/api/delete_message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message_id:ctxMsgData.id,friend_uid:currentFriend.uid})});
  const d=await r.json();if(d.ok){loadMessages();toast('Dihapus');}else toast('Gagal hapus',2500,true);
}

// ============================================================
// EMOJI / ATTACH
// ============================================================
function buildEmojiGrid(){
  const grid=document.getElementById('emoji-grid');
  grid.innerHTML=EMOJIS.map(e=>`<span class="emoji-item" data-e="${encodeURIComponent(e)}">${e}</span>`).join('');
  grid.onclick=function(ev){const t=ev.target.closest('.emoji-item');if(t)insertEmoji(decodeURIComponent(t.dataset.e));};
}
function toggleEmojiPicker(){closeAllMenus();document.getElementById('emoji-picker').classList.toggle('open');}
function insertEmoji(e){const inp=document.getElementById('msg-input');const s=inp.selectionStart,end=inp.selectionEnd;inp.value=inp.value.substring(0,s)+e+inp.value.substring(end);inp.selectionStart=inp.selectionEnd=s+e.length;inp.focus();onMsgInput(inp);document.getElementById('emoji-picker').classList.remove('open');}
function toggleAttMenu(){closeAllMenus();document.getElementById('att-menu').classList.toggle('open');}
function triggerFile(type){document.getElementById('att-menu').classList.remove('open');document.getElementById(type==='photo'?'file-photo':'file-doc').click();}

function showUploadBar(){
  const bar=document.getElementById('upload-progress'),fill=document.getElementById('upload-fill');
  bar.classList.add('show');fill.style.width='0%';
  let w=0;const iv=setInterval(()=>{w+=Math.random()*8;if(w>=88)clearInterval(iv);fill.style.width=Math.min(w,88)+'%';},200);
  return()=>{fill.style.width='100%';setTimeout(()=>bar.classList.remove('show'),500);clearInterval(iv);};
}
async function handleUpload(input){
  if(!input.files[0]||!currentFriend)return;
  document.getElementById('att-menu').classList.remove('open');
  const done=showUploadBar(),fd=new FormData();
  fd.append('file',input.files[0]);fd.append('to_uid',currentFriend.uid);
  if(replyData){fd.append('reply_from',replyData.from);fd.append('reply_text',replyData.text);}
  try{const r=await fetch('/api/send_file',{method:'POST',body:fd});const d=await r.json();done();if(d.ok){cancelReply();loadMessages();}else toast('Upload gagal: '+(d.msg||''),3500,true);}
  catch(e){done();toast('Upload error',3000,true);}
  input.value='';
}

// ============================================================
// CAMERA
// ============================================================
function openCameraChat(){document.getElementById('att-menu').classList.remove('open');camMode='chat';openCamera();}
async function openCamera(){
  try{camStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:camFacing},audio:false});document.getElementById('cam-vid').srcObject=camStream;document.getElementById('cam-canvas').style.display='none';document.getElementById('cam-send-wrap').style.display='none';camPhotoBlob=null;openPanel('cam-ov');}
  catch(e){toast('Kamera tidak bisa diakses',3000,true);}
}
function switchCamFacing(){camFacing=camFacing==='user'?'environment':'user';closeCamera();setTimeout(openCamera,200);}
function snapPhoto(){const vid=document.getElementById('cam-vid'),canvas=document.getElementById('cam-canvas');canvas.width=vid.videoWidth;canvas.height=vid.videoHeight;canvas.getContext('2d').drawImage(vid,0,0);canvas.style.display='block';canvas.toBlob(b=>{camPhotoBlob=b;},'image/jpeg',0.92);document.getElementById('cam-send-wrap').style.display='block';}
async function sendCamPhoto(){
  if(!camPhotoBlob){toast('Ambil foto dulu!',2000,true);return;}
  closeCamera();const done=showUploadBar(),fd=new FormData();
  fd.append('file',new File([camPhotoBlob],'camera.jpg',{type:'image/jpeg'}));
  if(camMode==='status'){fd.append('type','image');const r=await fetch('/api/status/upload',{method:'POST',body:fd});const d=await r.json();done();if(d.ok){toast('Status diposting âœ…');loadSidebarStatuses();setTimeout(openMyStatus,600);}else toast('Gagal',2500,true);}
  else{if(!currentFriend){done();return;}fd.append('to_uid',currentFriend.uid);const r=await fetch('/api/send_file',{method:'POST',body:fd});const d=await r.json();done();if(d.ok){toast('Foto terkirim');loadMessages();}else toast('Gagal',2500,true);}
}
function closeCamera(){if(camStream)camStream.getTracks().forEach(t=>t.stop());camStream=null;closePanel('cam-ov');}

// ============================================================
// VOICE
// ============================================================
async function startVoice(e){
  if(e)e.preventDefault();if(!currentFriend){toast('Pilih chat dulu!',2000,true);return;}
  try{
    const stream=await navigator.mediaDevices.getUserMedia({audio:true});
    const mime=MediaRecorder.isTypeSupported('audio/webm')?'audio/webm':'audio/ogg';
    mediaRecorder=new MediaRecorder(stream,{mimeType:mime});recChunks=[];isRecording=true;
    mediaRecorder.ondataavailable=e=>recChunks.push(e.data);
    mediaRecorder.onstop=async()=>{
      const blob=new Blob(recChunks,{type:mime});stream.getTracks().forEach(t=>t.stop());
      if(blob.size>500&&currentFriend){const done=showUploadBar(),fd=new FormData();fd.append('file',new File([blob],'voice.webm',{type:mime}));fd.append('to_uid',currentFriend.uid);const r=await fetch('/api/send_file',{method:'POST',body:fd});const d=await r.json();done();if(d.ok){toast('Suara terkirim');loadMessages();}else toast('Gagal kirim suara',2500,true);}
    };
    mediaRecorder.start();document.getElementById('rec-btn').classList.add('recording');toast('Merekam... Lepaskan untuk kirim',15000);
  }catch(e){toast('Mikrofon tidak bisa diakses',2500,true);}
}
function stopVoice(e){if(e)e.preventDefault();if(mediaRecorder&&isRecording){mediaRecorder.stop();isRecording=false;document.getElementById('rec-btn').classList.remove('recording');toast('Mengirim...',1500);}}
function viewImg(src){document.getElementById('img-full').src=src;openPanel('img-ov');}

// ============================================================
// TYPING
// ============================================================
async function pingTyping(){
  const now=Date.now();if(now-lastTypingPing<2000||!currentFriend)return;lastTypingPing=now;
  await fetch('/api/typing',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to_uid:currentFriend.uid})});
}
async function checkTyping(){
  if(!currentFriend)return;
  try{const r=await fetch(`/api/typing_status?friend_uid=${currentFriend.uid}`);const d=await r.json();const dots=document.getElementById('typing-dots');if(d.typing){document.getElementById('typing-text').textContent=currentFriend.name+' sedang mengetik...';dots.classList.add('show');}else dots.classList.remove('show');}catch(e){}
}

// ============================================================
// STATUS
// ============================================================
async function loadSidebarStatuses(){
  try{
    const r=await fetch('/api/status/list');const d=await r.json();
    const myStats=d.my_statuses||[],otherStats=d.statuses||[];
    document.getElementById('my-status-hint').textContent=myStats.length?`${myStats.length} status Â· ${fmtTime(myStats[myStats.length-1].created_at)}`:'Ketuk untuk buat status';
    const fl=document.getElementById('friends-status-list');const lbl=document.getElementById('friends-stat-label');const empty=document.getElementById('status-empty');
    const byUser={};otherStats.forEach(s=>{if(!byUser[s.user_id])byUser[s.user_id]=[];byUser[s.user_id].push(s);});
    const entries=Object.entries(byUser);
    if(!entries.length){fl.innerHTML='';lbl.style.display='none';empty.style.display='';return;}
    lbl.style.display='';empty.style.display='none';
    fl.innerHTML=entries.map(([uid,sts])=>{
      const u=allUsers.find(x=>x.uid===uid)||{uid,username:'?',avatar:''};const latest=sts[sts.length-1];
      return`<div class="status-friend-item" onclick="viewFriendStatus('${uid}')">
        <div class="status-ring" style="flex-shrink:0;"><div class="status-ring-inner">${makeAv(u,44)}</div></div>
        <div style="flex:1;min-width:0;margin-left:12px;"><div style="font-weight:800;font-size:14px;">${escHtml(u.username)}</div><div style="font-size:12px;color:var(--st);margin-top:1px;">${fmtTime(latest.created_at)} Â· ${sts.length} status</div></div>
      </div>`;
    }).join('');
  }catch(e){}
}
async function openMyStatus(){
  try{const r=await fetch('/api/status/my');const d=await r.json();const myStats=d.statuses||[];if(!myStats.length){closePanel('stview-ov');openPanel('cstat-ov');return;}closePanel('cstat-ov');const u={uid:ME.uid,username:ME.username,avatar:''};stvData={user:u,statuses:myStats};stvIdx=0;renderSTV();openPanel('stview-ov');}
  catch(e){toast('Gagal memuat status',2000,true);openPanel('cstat-ov');}
}
async function viewFriendStatus(uid){
  try{const r=await fetch(`/api/status/user/${uid}`);const d=await r.json();if(!d.statuses||!d.statuses.length){toast('Status tidak tersedia',2000);return;}const u=allUsers.find(x=>x.uid===uid)||{uid,username:'?',avatar:''};stvData={user:u,statuses:d.statuses};stvIdx=0;renderSTV();openPanel('stview-ov');}
  catch(e){toast('Gagal memuat status',2500,true);}
}
function closeStatusViewer(){clearStvTimer();closePanel('stview-ov');}
function clearStvTimer(){if(stvTimerInt){clearInterval(stvTimerInt);stvTimerInt=null;}}
function prevStatus(){if(stvIdx>0){stvIdx--;renderSTV();}}
function nextStatus(){if(stvData&&stvIdx<stvData.statuses.length-1){stvIdx++;renderSTV();}else closeStatusViewer();}
function renderSTV(){
  if(!stvData)return;clearStvTimer();
  const{user,statuses}=stvData,s=statuses[stvIdx];
  document.getElementById('stv-av').innerHTML=makeAv(user,34);
  document.getElementById('stv-name').textContent=user.username;
  document.getElementById('stv-time').textContent=fmtTime(s.created_at);
  document.getElementById('stv-progress').innerHTML=statuses.map((_,i)=>`<div class="stv-seg"><div class="stv-fill" id="stv-f-${i}" style="width:${i<stvIdx?'100':'0'}%"></div></div>`).join('');
  let body='';
  if(s.type==='text'){const bgs=['#005c4b','#1a56db','#7c3aed','#dc2626','#d97706'];body=`<div class="stv-text" style="background:${bgs[stvIdx%bgs.length]};border-radius:12px;width:100%;min-height:160px;display:flex;align-items:center;justify-content:center;">${escHtml(s.content)}</div>`;}
  else if(s.type==='image'){body=`<img class="stv-img" src="${s.media_url}" alt="status">`;}
  else if(s.type==='video'){body=`<video src="${s.media_url}" controls autoplay playsinline style="max-width:100%;max-height:360px;border-radius:12px;"></video>`;}
  document.getElementById('stv-body').innerHTML=body;
  document.getElementById('stv-prev-btn').disabled=(stvIdx===0);
  document.getElementById('stv-next-btn').textContent=stvIdx>=statuses.length-1?'Tutup Ã—':'Next â–¶';
  requestAnimationFrame(()=>{const fill=document.getElementById(`stv-f-${stvIdx}`);if(fill){fill.style.transition='none';fill.style.width='0%';requestAnimationFrame(()=>{fill.style.transition='width 5s linear';fill.style.width='100%';});}});
  stvTimerInt=setInterval(()=>{if(stvData&&stvIdx<stvData.statuses.length-1){stvIdx++;renderSTV();}else closeStatusViewer();},5000);
}
function showTextStatusForm(){document.getElementById('text-stat-form').style.display='block';}
async function postTextStatus(){
  const txt=document.getElementById('stat-text-inp').value.trim();if(!txt){toast('Tulis status dulu!',2000,true);return;}
  const r=await fetch('/api/status/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:'text',content:txt})});
  const d=await r.json();if(d.ok){toast('Status diposting âœ…');closePanel('cstat-ov');document.getElementById('stat-text-inp').value='';document.getElementById('text-stat-form').style.display='none';await loadSidebarStatuses();setTimeout(openMyStatus,600);}else toast('Gagal: '+(d.msg||''),3000,true);
}
async function uploadStatus(input,type){
  if(!input.files[0])return;const file=input.files[0];if(file.size>20*1024*1024){toast('Max 20MB',2500,true);return;}
  const done=showUploadBar(),fd=new FormData();fd.append('file',file);fd.append('type',type);
  try{const r=await fetch('/api/status/upload',{method:'POST',body:fd});const d=await r.json();done();if(d.ok){toast('Status diposting!');closePanel('cstat-ov');await loadSidebarStatuses();setTimeout(openMyStatus,600);}else toast('Upload status gagal',3000,true);}
  catch(e){done();toast('Upload error',3000,true);}input.value='';
}

// ============================================================
// PROFILE
// ============================================================
async function uploadAvatar(input){
  if(!input.files[0])return;if(input.files[0].size>10*1024*1024){toast('Max 10MB',2500,true);return;}
  const done=showUploadBar(),fd=new FormData();fd.append('avatar',input.files[0]);
  try{const r=await fetch('/api/upload_avatar',{method:'POST',body:fd});const d=await r.json();done();if(d.ok){const url=d.url;document.getElementById('pav-big').innerHTML=`<img src="${url}" style="width:100%;height:100%;object-fit:cover;">`;document.getElementById('my-av-el').innerHTML=`<img src="${url}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;">`;toast('Foto profil diperbarui âœ…');}else toast('Gagal: '+(d.msg||''),3000,true);}
  catch(e){done();toast('Gagal upload',2500,true);}input.value='';
}
async function saveProfile(){
  const u=document.getElementById('edit-username').value.trim(),b=document.getElementById('edit-bio').value.trim();
  if(!u){toast('Username kosong!',2500,true);return;}
  const fd=new FormData();fd.append('username',u);fd.append('bio',b);
  const r=await fetch('/api/update_profile',{method:'POST',body:fd});const d=await r.json();
  if(d.ok){document.getElementById('pname').textContent=u;toast('Profil disimpan âœ…');closePanel('prof-ov');setTimeout(()=>location.reload(),800);}else toast('Gagal: '+(d.msg||''),3000,true);
}
function doLogout(){if(confirm('Logout?'))fetch('/logout',{method:'POST'}).then(()=>location.href='/');}

// ============================================================
// NOTIFICATIONS
// ============================================================
async function checkNotifCount(){try{const r=await fetch('/api/notifications');const d=await r.json();const n=(d.notifications||[]).filter(x=>!x.is_read).length;const b=document.getElementById('notif-badge');b.style.display=n>0?'':'none';b.textContent=n>9?'9+':n;}catch(e){}}
async function loadNotifications(){
  const r=await fetch('/api/notifications');const d=await r.json();
  const el=document.getElementById('notif-list');const notifs=d.notifications||[];
  if(!notifs.length){el.innerHTML='<div style="text-align:center;color:var(--st);padding:22px;">Tidak ada notifikasi</div>';return;}
  el.innerHTML=notifs.slice().reverse().map(n=>{const u=allUsers.find(x=>x.uid===n.from_uid);const nm=u?.username||'?';
    return`<div class="notif-item" onclick="closePanel('notif-ov');openChat('${n.from_uid}','${(nm).replace(/'/g,"\\'")}','${u?.avatar||''}','')">
      <div class="notif-av">${makeAv(u||{username:nm},42)}</div>
      <div style="flex:1;"><div style="font-weight:800;font-size:14px;">${escHtml(nm)}</div><div style="font-size:12px;color:var(--st);">${escHtml(n.message)}</div><div style="font-size:11px;color:var(--st);">${fmtTime(n.created_at)}</div></div>
      ${!n.is_read?'<div class="notif-dot"></div>':''}
    </div>`;
  }).join('');
}
async function markNotifsRead(){await fetch('/api/notifications/read',{method:'POST'});checkNotifCount();}

// ============================================================
// CALL UI - AGORA
// ============================================================
async function startCall(type){
  if(!currentFriend){toast('Pilih teman dulu!',2000,true);return;}
  if(!AGORA_APP_ID){toast('Agora App ID belum dikonfigurasi!',3000,true);return;}
  currentCallType=type;
  const r=await fetch('/api/call/offer',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({to_uid:currentFriend.uid,call_type:type})});
  const d=await r.json();if(!d.ok){toast('Gagal memulai panggilan',2500,true);return;}
  agoraCurrentCallId=d.call_id;
  showCallUI(currentFriend,type,'outgoing');
  await joinAgoraChannel(d.channel,type);
  pollCallAnswer();
}

async function joinAgoraChannel(channelName,type){
  try{
    agoraClient=AgoraRTC.createClient({mode:'rtc',codec:'vp8'});
    await agoraClient.join(AGORA_APP_ID,channelName,null,ME.uid.slice(0,32));
    agoraLocalAudioTrack=await AgoraRTC.createMicrophoneAudioTrack();
    await agoraClient.publish([agoraLocalAudioTrack]);
    if(type==='video'){
      agoraLocalVideoTrack=await AgoraRTC.createCameraVideoTrack();
      await agoraClient.publish([agoraLocalVideoTrack]);
      agoraLocalVideoTrack.play('agora-local');
    }
    agoraClient.on('user-published',async(user,mediaType)=>{
      await agoraClient.subscribe(user,mediaType);
      if(mediaType==='video'){
        document.getElementById('agora-remote').innerHTML='';
        user.videoTrack.play('agora-remote');
      }
      if(mediaType==='audio')user.audioTrack.play();
      document.getElementById('call-status-txt').textContent='Terhubung âœ…';
      document.getElementById('call-status-txt').style.color='#00a884';
      if(!callTimerInt)startCallTimer();
    });
    agoraClient.on('user-unpublished',(user,mediaType)=>{if(mediaType==='video'){document.getElementById('agora-remote').innerHTML='<div style="text-align:center;color:rgba(255,255,255,.4);"><div style="font-size:48px;margin-bottom:8px;">ðŸ‘¤</div>Kamera dimatikan</div>';}});
    agoraClient.on('user-left',()=>{toast('Panggilan berakhir',2000);endCall();});
  }catch(e){toast('Gagal bergabung: '+e.message,3000,true);console.error('Agora error:',e);endCall();}
}

async function pollCallAnswer(){
  if(!agoraCurrentCallId)return;
  try{
    const r=await fetch(`/api/call/status/${agoraCurrentCallId}`);const d=await r.json();
    if(d.status==='answered'){startCallTimer();}
    else if(d.status==='rejected'){toast('Panggilan ditolak ðŸ“µ',3000);endCall();}
    else if(d.status==='pending')setTimeout(pollCallAnswer,2000);
    else if(d.status==='ended')endCall();
  }catch(e){}
}

function showCallUI(friend,type,dir){
  document.getElementById('call-ui').classList.add('active');
  const name=friend.name||friend.username||'?';
  document.getElementById('call-av').innerHTML=friend.avatar?`<img src="${friend.avatar}">`:(name[0]||'?').toUpperCase();
  document.getElementById('call-name').textContent=name;
  document.getElementById('call-status-txt').textContent=dir==='outgoing'?'Memanggil...':'Menghubungkan...';
  document.getElementById('call-status-txt').style.color='rgba(255,255,255,.55)';
  document.getElementById('call-timer').style.display='none';
  const isVideo=(type==='video');
  document.getElementById('call-video-grid').classList.toggle('show',isVideo);
  document.getElementById('audio-call-info').style.display=isVideo?'none':'flex';
  document.getElementById('ccbtn-cam').style.display=isVideo?'flex':'none';
  micMuted=false;camOff=false;speakerOff=false;
  ['ccbtn-mic','ccbtn-cam','ccbtn-spk'].forEach(id=>{const b=document.getElementById(id);if(b)b.className='ccbtn btn-toggle on';});
}

async function answerCall(type){
  if(!incCallInfo)return;
  agoraCurrentCallId=incCallInfo.call_id;currentCallType=type;
  document.getElementById('incoming-call').classList.remove('show');
  const caller=allUsers.find(u=>u.uid===incCallInfo.from_uid)||{username:'?',avatar:'',uid:incCallInfo.from_uid,name:'?'};
  showCallUI(caller,type,'incoming');
  await joinAgoraChannel(incCallInfo.channel,type);
  await fetch('/api/call/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({call_id:agoraCurrentCallId})});
  document.getElementById('call-status-txt').textContent='Terhubung âœ…';
  document.getElementById('call-status-txt').style.color='#00a884';
  startCallTimer();incCallInfo=null;
}

function rejectCall(){
  if(incCallInfo)fetch('/api/call/reject',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({call_id:incCallInfo.call_id})});
  document.getElementById('incoming-call').classList.remove('show');incCallInfo=null;
}

async function endCall(){
  if(agoraLocalAudioTrack){agoraLocalAudioTrack.close();agoraLocalAudioTrack=null;}
  if(agoraLocalVideoTrack){agoraLocalVideoTrack.close();agoraLocalVideoTrack=null;}
  if(agoraClient){await agoraClient.leave();agoraClient=null;}
  if(callTimerInt){clearInterval(callTimerInt);callTimerInt=null;}callSecs=0;
  if(agoraCurrentCallId){fetch('/api/call/end',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({call_id:agoraCurrentCallId})});agoraCurrentCallId=null;}
  document.getElementById('call-ui').classList.remove('active');
  document.getElementById('call-video-grid').classList.remove('show');
  document.getElementById('agora-remote').innerHTML='<div style="text-align:center;color:rgba(255,255,255,.3);font-size:14px;"><div style="font-size:48px;margin-bottom:8px;">ðŸ‘¤</div>Menunggu video...</div>';
  document.getElementById('agora-local').innerHTML='';
}

function toggleMic(){micMuted=!micMuted;if(agoraLocalAudioTrack)agoraLocalAudioTrack.setEnabled(!micMuted);const b=document.getElementById('ccbtn-mic');b.className='ccbtn btn-toggle '+(micMuted?'off':'on');toast(micMuted?'Mic dimatikan ðŸ”‡':'Mic aktif ðŸŽ¤',1500);}
function toggleCam(){camOff=!camOff;if(agoraLocalVideoTrack)agoraLocalVideoTrack.setEnabled(!camOff);const b=document.getElementById('ccbtn-cam');b.className='ccbtn btn-toggle '+(camOff?'off':'on');toast(camOff?'Kamera dimatikan ðŸš«':'Kamera aktif ðŸ“·',1500);}
function toggleSpeaker(){speakerOff=!speakerOff;const b=document.getElementById('ccbtn-spk');b.className='ccbtn btn-toggle '+(speakerOff?'off':'on');toast(speakerOff?'Speaker dimatikan ðŸ”‡':'Speaker aktif ðŸ”Š',1500);}
function startCallTimer(){callSecs=0;document.getElementById('call-timer').style.display='block';if(callTimerInt)clearInterval(callTimerInt);callTimerInt=setInterval(()=>{callSecs++;const m=Math.floor(callSecs/60).toString().padStart(2,'0'),s=(callSecs%60).toString().padStart(2,'0');document.getElementById('call-timer').textContent=m+':'+s;},1000);}

async function checkIncomingCall(){
  if(agoraClient)return;
  try{const r=await fetch('/api/call/incoming');const d=await r.json();
    if(d.call&&(!incCallInfo||incCallInfo.call_id!==d.call.call_id)){
      incCallInfo=d.call;const caller=allUsers.find(u=>u.uid===d.call.from_uid)||{username:'Seseorang',avatar:''};
      document.getElementById('inc-av').innerHTML=makeAv(caller,56);
      document.getElementById('inc-name').textContent=caller.username;
      document.getElementById('inc-type').textContent=d.call.call_type==='video'?'ðŸ“¹ Video Call Masuk':'ðŸ“ž Panggilan Masuk';
      document.getElementById('incoming-call').classList.add('show');
      setTimeout(()=>{if(incCallInfo&&incCallInfo.call_id===d.call.call_id)rejectCall();},30000);
    }
  }catch(e){}
}

// ============================================================
// LIVE STREAMING
// ============================================================
async function startLiveStream(){
  if(!AGORA_APP_ID){toast('Agora App ID belum dikonfigurasi!',3000,true);return;}
  liveChannelName='live_'+ME.uid+'_'+Date.now();isLiveHost=true;
  await fetch('/api/live/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel:liveChannelName,host_name:ME.username})});
  document.getElementById('live-streamer-name').textContent=ME.username;document.getElementById('live-end-btn').style.display='block';document.getElementById('live-ui').classList.add('active');
  try{
    agoraLiveClient=AgoraRTC.createClient({mode:'live',codec:'vp8'});agoraLiveClient.setClientRole('host');
    await agoraLiveClient.join(AGORA_APP_ID,liveChannelName,null,ME.uid.slice(0,32));
    agoraLiveLocalVideoTrack=await AgoraRTC.createCameraVideoTrack();agoraLiveLocalAudioTrack=await AgoraRTC.createMicrophoneAudioTrack();
    agoraLiveLocalVideoTrack.play('live-local-video');
    await agoraLiveClient.publish([agoraLiveLocalVideoTrack,agoraLiveLocalAudioTrack]);
    liveCommentPollTimer=setInterval(pollLiveComments,3000);toast('Live streaming dimulai! ðŸ”´',2000);
  }catch(e){toast('Gagal mulai live: '+e.message,3000,true);closeLiveUI();}
}
async function watchLive(channelName,hostName,liveId){
  if(!AGORA_APP_ID){toast('Agora App ID belum dikonfigurasi!',3000,true);return;}
  liveChannelName=channelName;isLiveHost=false;
  document.getElementById('live-streamer-name').textContent=hostName;document.getElementById('live-end-btn').style.display='none';document.getElementById('live-ui').classList.add('active');
  await fetch('/api/live/join',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({live_id:liveId})});
  try{
    agoraLiveClient=AgoraRTC.createClient({mode:'live',codec:'vp8'});agoraLiveClient.setClientRole('audience');
    await agoraLiveClient.join(AGORA_APP_ID,liveChannelName,null,ME.uid.slice(0,32));
    agoraLiveClient.on('user-published',async(user,mediaType)=>{await agoraLiveClient.subscribe(user,mediaType);if(mediaType==='video')user.videoTrack.play('live-remote-video');if(mediaType==='audio')user.audioTrack.play();});
    agoraLiveClient.on('user-left',()=>{toast('Siaran berakhir',2000);closeLiveUI();});
    liveCommentPollTimer=setInterval(pollLiveComments,3000);toast('Bergabung ke live!',1500);
  }catch(e){toast('Gagal bergabung: '+e.message,3000,true);closeLiveUI();}
}
async function endLiveStream(){if(!isLiveHost||!confirm('Akhiri live streaming?'))return;await fetch('/api/live/end',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel:liveChannelName})});closeLiveUI();toast('Live streaming berakhir',2000);}
async function closeLiveUI(){
  if(liveCommentPollTimer){clearInterval(liveCommentPollTimer);liveCommentPollTimer=null;}
  if(agoraLiveLocalVideoTrack){agoraLiveLocalVideoTrack.close();agoraLiveLocalVideoTrack=null;}
  if(agoraLiveLocalAudioTrack){agoraLiveLocalAudioTrack.close();agoraLiveLocalAudioTrack=null;}
  if(agoraLiveClient){await agoraLiveClient.leave();agoraLiveClient=null;}
  document.getElementById('live-ui').classList.remove('active');document.getElementById('live-comments').innerHTML='';document.getElementById('live-local-video').innerHTML='';document.getElementById('live-remote-video').innerHTML='';isLiveHost=false;loadLiveList();
}
async function sendLiveComment(){const inp=document.getElementById('live-comment-input');const text=inp.value.trim();if(!text)return;inp.value='';addLiveComment(ME.username,text);await fetch('/api/live/comment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel:liveChannelName,text})});}
async function pollLiveComments(){try{const r=await fetch(`/api/live/comments/${liveChannelName}`);const d=await r.json();const comments=d.comments||[];const container=document.getElementById('live-comments');const existing=container.querySelectorAll('.live-comment').length;if(comments.length>existing){for(let i=existing;i<comments.length;i++){const c=comments[i];addLiveComment(c.username,c.text);}}}catch(e){}}
function addLiveComment(username,text){const container=document.getElementById('live-comments');const div=document.createElement('div');div.className='live-comment';div.innerHTML=`<span class="cname">${escHtml(username)}</span>${escHtml(text)}`;container.appendChild(div);while(container.children.length>8)container.removeChild(container.firstChild);container.scrollTop=container.scrollHeight;}
async function loadLiveList(){
  try{const r=await fetch('/api/live/list');const d=await r.json();const el=document.getElementById('live-list');const lives=d.lives||[];if(!lives.length){el.innerHTML='<div style="padding:24px;text-align:center;color:var(--st);font-size:13px;">Tidak ada siaran live saat ini ðŸ“º</div>';return;}
    el.innerHTML=lives.map(l=>`<div class="live-item" onclick="watchLive('${l.channel}','${escHtml(l.host_name||'?')}','${l.id}')">
      <div style="width:70px;height:44px;border-radius:8px;background:#1a0a38;display:flex;align-items:center;justify-content:center;font-size:24px;flex-shrink:0;position:relative;">ðŸ“º<span style="position:absolute;top:3px;left:3px;background:#e53e3e;color:#fff;font-size:9px;font-weight:900;padding:1px 5px;border-radius:4px;">LIVE</span></div>
      <div style="flex:1;min-width:0;"><div style="font-weight:800;font-size:14px;">${escHtml(l.host_name||'?')}</div><div style="font-size:12px;color:var(--g);">ðŸ‘ ${l.viewer_count||0} penonton</div></div>
      <div class="live-badge" style="font-size:10px;padding:3px 8px;">â— LIVE</div>
    </div>`).join('');
  }catch(e){document.getElementById('live-list').innerHTML='<div style="padding:24px;text-align:center;color:var(--st);">Gagal memuat</div>';}
}

// ============================================================
// AI ASSISTANT
// ============================================================
function openAI(){document.getElementById('ai-drawer').classList.add('open');setTimeout(()=>document.getElementById('ai-input').focus(),300);}
function closeAI(){document.getElementById('ai-drawer').classList.remove('open');}
function handleAIKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendAIFromInput();}}
function autoResizeAI(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,100)+'px';}
async function sendAIFromInput(){const inp=document.getElementById('ai-input');const text=inp.value.trim();if(!text)return;inp.value='';inp.style.height='auto';await sendAIMsg(text);}
async function sendAIMsg(text){
  if(!text)return;document.getElementById('ai-chips').style.display='none';
  const container=document.getElementById('ai-messages');
  const uDiv=document.createElement('div');uDiv.className='ai-msg user';uDiv.innerHTML=`<div class="ai-msg-av">ðŸ‘¤</div><div class="ai-bubble">${escHtml(text)}</div>`;container.appendChild(uDiv);
  aiHistory.push({role:'user',content:text});
  const thinkId='ai-t-'+Date.now();const thinkDiv=document.createElement('div');thinkDiv.className='ai-msg ai';thinkDiv.id=thinkId;thinkDiv.innerHTML=`<div class="ai-msg-av">ðŸ¤–</div><div class="ai-thinking-bubble"><span></span><span></span><span></span></div>`;container.appendChild(thinkDiv);container.scrollTop=container.scrollHeight;
  try{
    let sys='Kamu adalah WaClone AI. Jawab dalam Bahasa Indonesia yang ramah dan natural.';if(currentFriend)sys+=` Pengguna sedang chat dengan ${currentFriend.name}.`;
    let msgs=[...aiHistory].slice(-10);while(msgs.length&&msgs[0].role!=='user')msgs.shift();
    const fixed=[];for(const m of msgs){if(!fixed.length||fixed[fixed.length-1].role!==m.role)fixed.push({role:m.role,content:m.content});else fixed[fixed.length-1].content+='\n'+m.content;}
    if(!fixed.length||fixed[0].role!=='user')fixed.unshift({role:'user',content:text});
    const res=await fetch('/api/ai/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({system:sys,messages:fixed})});
    const thinkEl=document.getElementById(thinkId);if(thinkEl)thinkEl.remove();
    const rData=await res.json();
    let reply=rData.ok?(rData.reply||'Maaf, tidak ada jawaban.'):'âš ï¸ '+(rData.msg||'Tidak bisa menjawab sekarang.');
    if(rData.ok)aiHistory.push({role:'assistant',content:reply});
    const aDiv=document.createElement('div');aDiv.className='ai-msg ai';const formatted=escHtml(reply).replace(/\*\*(.*?)\*\*/gs,'<strong>$1</strong>').replace(/\n/g,'<br>');
    aDiv.innerHTML=`<div class="ai-msg-av">ðŸ¤–</div><div class="ai-bubble">${formatted}</div>`;container.appendChild(aDiv);container.scrollTop=container.scrollHeight;
  }catch(e){const thinkEl=document.getElementById(thinkId);if(thinkEl)thinkEl.remove();const errDiv=document.createElement('div');errDiv.className='ai-msg ai';errDiv.innerHTML=`<div class="ai-msg-av">ðŸ¤–</div><div class="ai-bubble" style="background:rgba(220,38,38,.1);border-color:rgba(220,38,38,.3);color:#fca5a5;">Terjadi kesalahan ðŸ˜”</div>`;container.appendChild(errDiv);container.scrollTop=container.scrollHeight;}
}

// ============================================================
// INIT
// ============================================================
buildEmojiGrid();loadSettings();loadUsers();
async function updatePresence(){try{await fetch('/api/presence',{method:'POST'});}catch(e){}}
updatePresence();
setInterval(()=>{loadUsers();checkNotifCount();updatePresence();checkIncomingCall();},5000);
document.addEventListener('click',e=>{
  if(!document.getElementById('att-menu').contains(e.target)&&!e.target.closest('[title="Lampiran"]'))document.getElementById('att-menu').classList.remove('open');
  if(!document.getElementById('emoji-picker').contains(e.target)&&!e.target.closest('.side-btn'))document.getElementById('emoji-picker').classList.remove('open');
});
window.addEventListener('popstate',e=>{e.preventDefault();goBack();history.pushState(null,'',location.href);});
history.pushState(null,'',location.href);
function checkMobile(){const isMobile=window.innerWidth<=700;const bb=document.getElementById('back-btn');if(bb)bb.style.display=isMobile?'flex':'none';if(!isMobile)document.getElementById('sidebar').classList.remove('hidden');}
checkMobile();window.addEventListener('resize',checkMobile);
</script>
</body>
</html>"""

# ============================
# HTML BUILDER
# ============================
def main_app_html(u):
    uid      = u.get("uid", "")
    username = u.get("username", "User")
    email    = u.get("email", "")
    avatar   = u.get("avatar", "")
    bio      = u.get("bio", "Hey there! I am using WaClone.")
    initial  = (username[0].upper() if username else "U")

    uh = username.replace('&','&amp;').replace('<','&lt;').replace('"','&quot;')
    eh = email.replace('&','&amp;').replace('<','&lt;').replace('"','&quot;')
    bh = bio.replace('&','&amp;').replace('<','&lt;').replace('"','&quot;')

    colors = ['#00a884','#7c3aed','#1a56db','#dc2626','#d97706','#059669']
    bg = colors[ord(username[0]) % len(colors)] if username else '#00a884'

    if avatar:
        sidebar_av = f'<img src="{avatar}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;">'
        profile_av = f'<img src="{avatar}" style="width:100%;height:100%;object-fit:cover;">'
    else:
        sidebar_av = f'<div style="width:40px;height:40px;border-radius:50%;background:{bg};display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff;">{initial}</div>'
        profile_av = f'<span style="font-size:40px;font-weight:900;">{initial}</span>'

    import json as _json
    html = MAIN_HTML
    html = html.replace('"__UID__"',      _json.dumps(uid))
    html = html.replace('"__USERNAME__"', _json.dumps(username))
    html = html.replace("__USERNAME__",   uh)
    html = html.replace("__EMAIL__",      eh)
    html = html.replace("__BIO__",        bh)
    html = html.replace("__SIDEBAR_AV__", sidebar_av)
    html = html.replace("__PROFILE_AV__", profile_av)
    html = html.replace("__AGORA_APP_ID__", AGORA_APP_ID)
    return html

# ============================
# ROUTES - AUTH
# ============================
@app.route("/")
def index():
    user = get_current_user(request)
    if user: return redirect("/home")
    resp = make_response(AUTH_PAGE)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    return resp

@app.route("/home")
def home():
    user = get_current_user(request)
    if not user: return redirect("/")
    html = main_app_html(user)
    resp = make_response(html)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    return resp

@app.route("/register", methods=["POST"])
def register():
    username = request.form.get("username","").strip()
    email    = request.form.get("email","").strip().lower()
    password = request.form.get("password","")
    if not username or not email or not password:
        return jsonify({"ok":False,"msg":"Semua field harus diisi"})
    if len(password) < 6:
        return jsonify({"ok":False,"msg":"Password minimal 6 karakter"})
    if not all(c.isalnum() or c == '_' for c in username):
        return jsonify({"ok":False,"msg":"Username hanya huruf, angka, underscore"})
    if len(username) < 3:
        return jsonify({"ok":False,"msg":"Username minimal 3 karakter"})
    # Cek koneksi Supabase
    if not SUPABASE_URL or not SUPABASE_KEY:
        return jsonify({"ok":False,"msg":"Konfigurasi database belum diset (SUPABASE_URL / SUPABASE_KEY)"})
    try:
        existing = supa_get("users", f"username=eq.{username}&select=uid")
        if existing:
            return jsonify({"ok":False,"msg":"Username sudah dipakai"})
        existing_email = supa_get("users", f"email=eq.{email}&select=uid")
        if existing_email:
            return jsonify({"ok":False,"msg":"Email sudah terdaftar"})
        uid = str(uuid.uuid4())
        pw_hash = hash_password(password)
        result = supa_post("users", {
            "uid": uid, "username": username, "email": email,
            "password": pw_hash, "bio": "Hey there! I am using WaClone.",
            "avatar": "", "online": True, "last_seen": int(time.time()),
            "created_at": int(time.time())
        })
        if result is None:
            return jsonify({"ok":False,"msg":"Gagal menyimpan ke database. Cek tabel 'users' sudah dibuat di Supabase."})
        resp = make_response(jsonify({"ok":True}))
        resp.set_cookie("uid", uid, max_age=30*24*3600, httponly=True, samesite='Lax')
        return resp
    except Exception as e:
        print("Register error:", e, file=sys.stderr)
        return jsonify({"ok":False,"msg":f"Error: {str(e)[:200]}"})

@app.route("/login", methods=["POST"])
def login():
    email    = request.form.get("email","").strip().lower()
    password = request.form.get("password","")
    if not email or not password:
        return jsonify({"ok":False,"msg":"Email/password kosong"})
    users = supa_get("users", f"email=eq.{email}&select=*")
    if not users:
        return jsonify({"ok":False,"msg":"Email tidak ditemukan"})
    u = users[0]
    if not check_password(u.get("password",""), password):
        return jsonify({"ok":False,"msg":"Password salah"})
    uid = u.get("uid")
    supa_patch("users", f"uid=eq.{uid}", {"online": True, "last_seen": int(time.time())})
    resp = make_response(jsonify({"ok":True}))
    resp.set_cookie("uid", uid, max_age=30*24*3600, httponly=True, samesite='Lax')
    return resp

@app.route("/logout", methods=["POST"])
def logout():
    user = get_current_user(request)
    if user:
        try: supa_patch("users", f"uid=eq.{user['uid']}", {"online": False, "last_seen": int(time.time())})
        except: pass
    resp = make_response(jsonify({"ok":True}))
    resp.set_cookie("uid","",expires=0)
    return resp

# ============================
# ROUTES - USERS
# ============================
@app.route("/api/users")
def api_users():
    user = get_current_user(request)
    if not user: return jsonify({"users":[]})
    try:
        uid = user["uid"]
        all_users = supa_get("users", "select=uid,username,bio,avatar,online,last_seen")
        users = []
        for u in all_users:
            if u.get("uid") == uid: continue
            chat_id = "_".join(sorted([uid, u["uid"]]))
            unread = 0
            try:
                msgs = supa_get("messages", f"chat_id=eq.{chat_id}&to_uid=eq.{uid}&status=neq.read&select=id")
                unread = len(msgs)
            except: pass
            last_msg = ""; last_time = 0
            try:
                lm = supa_get("messages", f"chat_id=eq.{chat_id}&deleted=eq.false&order=created_at.desc&limit=1&select=message,created_at,file_url")
                if lm:
                    last_msg = lm[0].get("message","") or ("[Media]" if lm[0].get("file_url") else "")
                    last_time = lm[0].get("created_at", 0)
            except: pass
            users.append({**u, "unread_count": unread, "last_msg": last_msg, "last_time": last_time})
        users.sort(key=lambda x: x.get("last_time",0) or 0, reverse=True)
        return jsonify({"users": users})
    except Exception as e:
        return jsonify({"users":[],"error":str(e)})

# ============================
# ROUTES - MESSAGES
# ============================
@app.route("/api/messages")
def api_messages():
    user = get_current_user(request)
    if not user: return jsonify({"messages":[]})
    friend_uid = request.args.get("friend_uid")
    if not friend_uid: return jsonify({"messages":[]})
    try:
        chat_id = "_".join(sorted([user["uid"], friend_uid]))
        msgs = supa_get("messages", f"chat_id=eq.{chat_id}&deleted=eq.false&order=created_at.asc&limit=200&select=*")
        return jsonify({"messages": msgs})
    except Exception as e:
        return jsonify({"messages":[]})

@app.route("/api/send", methods=["POST"])
def api_send():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    to_uid  = data.get("to_uid")
    message = data.get("message","").strip()
    reply_to = data.get("reply_to")
    if not to_uid or not message: return jsonify({"ok":False})
    try:
        chat_id = "_".join(sorted([user["uid"], to_uid]))
        ts = int(time.time())
        msg = {
            "id": str(uuid.uuid4()),
            "chat_id": chat_id, "from_uid": user["uid"], "to_uid": to_uid,
            "message": message, "status": "sent",
            "file_url": None, "file_type": None,
            "reply_to": reply_to, "deleted": False, "created_at": ts
        }
        supa_post("messages", msg)
        supa_post("notifications", {
            "to_uid": to_uid, "from_uid": user["uid"],
            "message": message[:80], "is_read": False, "created_at": ts
        })
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/send_file", methods=["POST"])
def api_send_file():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    to_uid = request.form.get("to_uid")
    f = request.files.get("file")
    if not f or not to_uid: return jsonify({"ok":False,"msg":"Data tidak lengkap"})
    ALLOWED = {'png','jpg','jpeg','gif','webp','bmp','txt','pdf','doc','docx','xls','xlsx','zip','rar','mp4','webm','ogg','m4a','wav','mp3','mov','avi','mkv','heic','heif'}
    ext = f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else 'bin'
    if ext not in ALLOWED: return jsonify({"ok":False,"msg":"Tipe file tidak diizinkan"})
    try:
        file_bytes = f.read()
        is_video = ext in {'mp4','webm','mov','avi','mkv'}
        resource_type = "video" if is_video else ("image" if ext in {'png','jpg','jpeg','gif','webp','bmp','heic','heif'} else "raw")
        file_url, file_type = cloudinary_upload(file_bytes, f.filename, resource_type, "waclone/chats")
        if not file_url: return jsonify({"ok":False,"msg":"Upload ke Cloudinary gagal"})
        reply_to = None
        rt = request.form.get("reply_text"); rf = request.form.get("reply_from")
        if rt: reply_to = {"text":rt,"from_uid":rf or ""}
        chat_id = "_".join(sorted([user["uid"], to_uid]))
        ts = int(time.time())
        msg = {
            "id": str(uuid.uuid4()),
            "chat_id": chat_id, "from_uid": user["uid"], "to_uid": to_uid,
            "message": "", "status": "sent",
            "file_url": file_url, "file_type": file_type,
            "reply_to": reply_to, "deleted": False, "created_at": ts
        }
        supa_post("messages", msg)
        supa_post("notifications", {
            "to_uid": to_uid, "from_uid": user["uid"],
            "message": "[Media]", "is_read": False, "created_at": ts
        })
        return jsonify({"ok":True,"file_url":file_url})
    except Exception as e:
        print("send_file error:", e, file=sys.stderr)
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/delete_message", methods=["POST"])
def api_delete_message():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    message_id = data.get("message_id")
    friend_uid = data.get("friend_uid")
    if not message_id or not friend_uid: return jsonify({"ok":False})
    try:
        msgs = supa_get("messages", f"id=eq.{message_id}&from_uid=eq.{user['uid']}&select=id")
        if not msgs: return jsonify({"ok":False,"msg":"Tidak bisa hapus pesan ini"})
        supa_patch("messages", f"id=eq.{message_id}", {"deleted":True,"message":"Pesan ini telah dihapus"})
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/mark_read", methods=["POST"])
def api_mark_read():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    friend_uid = data.get("friend_uid") if data else None
    if not friend_uid: return jsonify({"ok":False})
    try:
        chat_id = "_".join(sorted([user["uid"], friend_uid]))
        supa_patch("messages", f"chat_id=eq.{chat_id}&to_uid=eq.{user['uid']}&status=neq.read", {"status":"read"})
        supa_patch("notifications", f"to_uid=eq.{user['uid']}&from_uid=eq.{friend_uid}&is_read=eq.false", {"is_read":True})
        return jsonify({"ok":True})
    except: return jsonify({"ok":False})

# ============================
# ROUTES - PROFILE / AVATAR
# ============================
@app.route("/api/upload_avatar", methods=["POST"])
def api_upload_avatar():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False,"msg":"Tidak terautentikasi"})
    f = request.files.get("avatar")
    if not f: return jsonify({"ok":False,"msg":"Tidak ada file"})
    allowed_img = {'png','jpg','jpeg','gif','webp','bmp','heic','heif'}
    ext = f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
    if ext not in allowed_img: return jsonify({"ok":False,"msg":f"Format tidak didukung ({ext})"})
    try:
        file_bytes = f.read()
        url, _ = cloudinary_upload(file_bytes, f.filename, "image", "waclone/avatars")
        if not url: return jsonify({"ok":False,"msg":"Upload ke Cloudinary gagal"})
        supa_patch("users", f"uid=eq.{user['uid']}", {"avatar": url})
        return jsonify({"ok":True,"url":url})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/update_profile", methods=["POST"])
def api_update_profile():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    username = request.form.get("username","").strip()
    bio      = request.form.get("bio","").strip()
    if not username: return jsonify({"ok":False,"msg":"Username tidak boleh kosong"})
    try:
        upd = {"bio": bio}
        if username != user.get("username"):
            existing = supa_get("users", f"username=eq.{username}&select=uid")
            if existing: return jsonify({"ok":False,"msg":"Username sudah dipakai"})
            upd["username"] = username
        supa_patch("users", f"uid=eq.{user['uid']}", upd)
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

# ============================
# ROUTES - TYPING / PRESENCE
# ============================
@app.route("/api/typing", methods=["POST"])
def api_typing():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    to_uid = data.get("to_uid")
    if not to_uid: return jsonify({"ok":False})
    try:
        key = f"{user['uid']}_{to_uid}"
        existing = supa_get("typing", f"typing_key=eq.{key}&select=id")
        if existing:
            supa_patch("typing", f"typing_key=eq.{key}", {"updated_at": int(time.time())})
        else:
            supa_post("typing", {"typing_key": key, "from_uid": user["uid"], "to_uid": to_uid, "updated_at": int(time.time())})
        return jsonify({"ok":True})
    except: return jsonify({"ok":False})

@app.route("/api/typing_status")
def api_typing_status():
    user = get_current_user(request)
    if not user: return jsonify({"typing":False})
    friend_uid = request.args.get("friend_uid")
    if not friend_uid: return jsonify({"typing":False})
    try:
        key = f"{friend_uid}_{user['uid']}"
        rows = supa_get("typing", f"typing_key=eq.{key}&select=updated_at")
        if rows:
            t = rows[0].get("updated_at", 0)
            return jsonify({"typing": int(time.time())-t < 5})
        return jsonify({"typing":False})
    except: return jsonify({"typing":False})

@app.route("/api/presence", methods=["POST"])
def api_presence():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    try: supa_patch("users", f"uid=eq.{user['uid']}", {"online":True,"last_seen":int(time.time())})
    except: pass
    return jsonify({"ok":True})

# ============================
# ROUTES - NOTIFICATIONS
# ============================
@app.route("/api/notifications")
def api_notifications():
    user = get_current_user(request)
    if not user: return jsonify({"notifications":[]})
    try:
        notifs = supa_get("notifications", f"to_uid=eq.{user['uid']}&order=created_at.asc&limit=50&select=*")
        return jsonify({"notifications": notifs})
    except: return jsonify({"notifications":[]})

@app.route("/api/notifications/read", methods=["POST"])
def api_notifs_read():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    try:
        supa_patch("notifications", f"to_uid=eq.{user['uid']}&is_read=eq.false", {"is_read":True})
        return jsonify({"ok":True})
    except: return jsonify({"ok":False})

# ============================
# ROUTES - STATUS
# ============================
@app.route("/api/status/create", methods=["POST"])
def api_status_create():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    try:
        supa_post("statuses", {
            "id": str(uuid.uuid4()),
            "user_id": user["uid"], "type": data.get("type","text"),
            "content": data.get("content","")[:200], "media_url": None,
            "created_at": int(time.time())
        })
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/status/upload", methods=["POST"])
def api_status_upload():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False,"msg":"Tidak terautentikasi"})
    f = request.files.get("file")
    stype = request.form.get("type","image")
    if not f: return jsonify({"ok":False,"msg":"Tidak ada file"})
    try:
        file_bytes = f.read()
        rtype = "video" if stype == "video" else "image"
        url, ct = cloudinary_upload(file_bytes, f.filename, rtype, "waclone/statuses")
        if not url: return jsonify({"ok":False,"msg":"Upload gagal"})
        supa_post("statuses", {
            "id": str(uuid.uuid4()),
            "user_id": user["uid"], "type": stype, "content": "",
            "media_url": url, "created_at": int(time.time())
        })
        return jsonify({"ok":True,"url":url})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/status/list")
def api_status_list():
    user = get_current_user(request)
    if not user: return jsonify({"statuses":[],"my_statuses":[]})
    try:
        cutoff = int(time.time()) - 86400
        all_stats = supa_get("statuses", f"created_at=gte.{cutoff}&order=created_at.asc&select=*")
        others = [s for s in all_stats if s.get("user_id") != user["uid"]]
        mine   = [s for s in all_stats if s.get("user_id") == user["uid"]]
        return jsonify({"statuses": others, "my_statuses": mine})
    except: return jsonify({"statuses":[],"my_statuses":[]})

@app.route("/api/status/my")
def api_status_my():
    user = get_current_user(request)
    if not user: return jsonify({"statuses":[]})
    try:
        cutoff = int(time.time()) - 86400
        stats = supa_get("statuses", f"user_id=eq.{user['uid']}&created_at=gte.{cutoff}&order=created_at.asc&select=*")
        return jsonify({"statuses": stats})
    except: return jsonify({"statuses":[]})

@app.route("/api/status/user/<uid>")
def api_status_user(uid):
    user = get_current_user(request)
    if not user: return jsonify({"statuses":[]})
    try:
        cutoff = int(time.time()) - 86400
        stats = supa_get("statuses", f"user_id=eq.{uid}&created_at=gte.{cutoff}&order=created_at.asc&select=*")
        return jsonify({"statuses": stats})
    except: return jsonify({"statuses":[]})

# ============================
# ROUTES - CALLS (Agora signaling)
# ============================
@app.route("/api/call/offer", methods=["POST"])
def api_call_offer():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    call_id = str(uuid.uuid4())
    channel = f"call_{call_id[:16]}"
    try:
        supa_post("calls", {
            "id": call_id, "from_uid": user["uid"], "to_uid": data["to_uid"],
            "channel": channel, "status": "pending",
            "call_type": data.get("call_type","audio"), "created_at": int(time.time())
        })
        return jsonify({"ok":True,"call_id":call_id,"channel":channel})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/call/status/<call_id>")
def api_call_status(call_id):
    user = get_current_user(request)
    if not user: return jsonify({"status":"error"})
    try:
        rows = supa_get("calls", f"id=eq.{call_id}&select=status,channel")
        if not rows: return jsonify({"status":"ended"})
        return jsonify({"status":rows[0].get("status","pending"),"channel":rows[0].get("channel")})
    except: return jsonify({"status":"error"})

@app.route("/api/call/answer", methods=["POST"])
def api_call_answer():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    try:
        supa_patch("calls", f"id=eq.{data['call_id']}", {"status":"answered"})
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/call/reject", methods=["POST"])
def api_call_reject():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    try:
        supa_patch("calls", f"id=eq.{data['call_id']}", {"status":"rejected"})
        return jsonify({"ok":True})
    except: return jsonify({"ok":False})

@app.route("/api/call/end", methods=["POST"])
def api_call_end():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    try:
        supa_patch("calls", f"id=eq.{data['call_id']}", {"status":"ended"})
        return jsonify({"ok":True})
    except: return jsonify({"ok":False})

@app.route("/api/call/incoming")
def api_call_incoming():
    user = get_current_user(request)
    if not user: return jsonify({"call":None})
    try:
        cutoff = int(time.time()) - 60
        calls = supa_get("calls", f"to_uid=eq.{user['uid']}&status=eq.pending&created_at=gte.{cutoff}&order=created_at.desc&limit=1&select=*")
        if calls:
            return jsonify({"call": calls[0]})
        return jsonify({"call":None})
    except: return jsonify({"call":None})

# ============================
# ROUTES - LIVE
# ============================
@app.route("/api/live/start", methods=["POST"])
def api_live_start():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    live_id = str(uuid.uuid4())
    try:
        supa_post("lives", {
            "id": live_id, "channel": data.get("channel",""),
            "host_uid": user["uid"], "host_name": user.get("username", data.get("host_name","")),
            "host_avatar": user.get("avatar",""),
            "status": "live", "viewer_count": 0, "comments": [],
            "started_at": int(time.time())
        })
        return jsonify({"ok":True,"live_id":live_id})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/live/end", methods=["POST"])
def api_live_end():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    try:
        supa_patch("lives", f"channel=eq.{data.get('channel','')}&host_uid=eq.{user['uid']}", {"status":"ended","ended_at":int(time.time())})
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/live/list")
def api_live_list():
    user = get_current_user(request)
    if not user: return jsonify({"lives":[]})
    try:
        cutoff = int(time.time()) - 14400
        lives = supa_get("lives", f"status=eq.live&started_at=gte.{cutoff}&order=started_at.desc&limit=20&select=*")
        return jsonify({"lives": lives})
    except: return jsonify({"lives":[]})

@app.route("/api/live/join", methods=["POST"])
def api_live_join():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    live_id = data.get("live_id","")
    try:
        rows = supa_get("lives", f"id=eq.{live_id}&select=viewer_count")
        if rows:
            cnt = rows[0].get("viewer_count",0) or 0
            supa_patch("lives", f"id=eq.{live_id}", {"viewer_count": cnt+1})
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/live/comment", methods=["POST"])
def api_live_comment():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    channel = data.get("channel","")
    try:
        rows = supa_get("lives", f"channel=eq.{channel}&status=eq.live&select=id,comments")
        if not rows: return jsonify({"ok":False})
        live = rows[0]
        comments = live.get("comments") or []
        comments.append({"uid": user["uid"], "username": user.get("username","?"), "text": data.get("text","")[:200], "time": int(time.time())})
        comments = comments[-50:]
        supa_patch("lives", f"id=eq.{live['id']}", {"comments": comments})
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/live/comments/<channel>")
def api_live_comments(channel):
    user = get_current_user(request)
    if not user: return jsonify({"comments":[]})
    try:
        rows = supa_get("lives", f"channel=eq.{channel}&status=eq.live&select=comments")
        if rows: return jsonify({"comments": rows[0].get("comments") or []})
        return jsonify({"comments":[]})
    except: return jsonify({"comments":[]})

# ============================
# ROUTES - AI
# ============================
def get_anthropic_key():
    key = os.environ.get("ANTHROPIC_API_KEY","").strip()
    if key: return key
    for path in ["/etc/secrets/ANTHROPIC_API_KEY","/etc/secrets/anthropic_api_key"]:
        try:
            with open(path,"r") as f:
                key = f.read().strip()
                if key: return key
        except: pass
    return ""

@app.route("/api/ai/chat", methods=["POST"])
def api_ai_chat():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False,"msg":"Login dulu"})
    api_key = get_anthropic_key()
    if not api_key: return jsonify({"ok":False,"msg":"ANTHROPIC_API_KEY belum diset di environment variable."})
    data = request.get_json()
    if not data: return jsonify({"ok":False,"msg":"Request tidak valid"})
    raw_messages = data.get("messages", [])
    system = data.get("system", "Kamu adalah WaClone AI, asisten pintar dalam aplikasi chat WaClone. Jawab dalam Bahasa Indonesia yang ramah dan natural.")

    # Bersihkan messages: filter role valid dan content tidak kosong
    valid = []
    for m in raw_messages:
        role = m.get("role", "")
        content = str(m.get("content", "")).strip()
        if role in ("user", "assistant") and content:
            valid.append({"role": role, "content": content})

    # Harus dimulai dari user
    while valid and valid[0]["role"] != "user":
        valid.pop(0)

    # Gabungkan consecutive role sama
    fixed = []
    for m in valid:
        if fixed and fixed[-1]["role"] == m["role"]:
            fixed[-1]["content"] += "\n" + m["content"]
        else:
            fixed.append({"role": m["role"], "content": m["content"]})

    # Pastikan diakhiri user
    while fixed and fixed[-1]["role"] != "user":
        fixed.pop()

    if not fixed:
        return jsonify({"ok":False,"msg":"Tidak ada pesan valid"})

    try:
        payload = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1024,
            "system": system,
            "messages": fixed
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": api_key
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read().decode("utf-8"))
            reply = result.get("content", [{}])[0].get("text", "Maaf, tidak bisa menjawab.")
            return jsonify({"ok":True, "reply":reply})
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", "ignore")
        print("AI HTTPError:", e.code, err_body, file=sys.stderr)
        try:
            err_msg = json.loads(err_body).get("error", {}).get("message", err_body[:200])
        except:
            err_msg = err_body[:200]
        return jsonify({"ok":False,"msg":f"AI error {e.code}: {err_msg}"})
    except Exception as e:
        print("AI error:", e, file=sys.stderr)
        return jsonify({"ok":False,"msg":"AI error: "+str(e)[:200]})

# ============================
# SUPABASE SCHEMA HELPER
# ============================
@app.route("/api/setup_info")
def api_setup_info():
    sql = """
-- Run this SQL in Supabase SQL Editor to create all required tables

CREATE TABLE IF NOT EXISTS users (
  uid TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  email TEXT UNIQUE NOT NULL,
  password TEXT,
  bio TEXT DEFAULT 'Hey there! I am using WaClone.',
  avatar TEXT DEFAULT '',
  online BOOLEAN DEFAULT false,
  last_seen BIGINT DEFAULT 0,
  created_at BIGINT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  chat_id TEXT NOT NULL,
  from_uid TEXT NOT NULL,
  to_uid TEXT NOT NULL,
  message TEXT DEFAULT '',
  status TEXT DEFAULT 'sent',
  file_url TEXT,
  file_type TEXT,
  reply_to JSONB,
  deleted BOOLEAN DEFAULT false,
  created_at BIGINT DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, created_at);

CREATE TABLE IF NOT EXISTS notifications (
  id BIGSERIAL PRIMARY KEY,
  to_uid TEXT NOT NULL,
  from_uid TEXT NOT NULL,
  message TEXT,
  is_read BOOLEAN DEFAULT false,
  created_at BIGINT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS typing (
  id BIGSERIAL PRIMARY KEY,
  typing_key TEXT UNIQUE,
  from_uid TEXT,
  to_uid TEXT,
  updated_at BIGINT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS statuses (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  type TEXT DEFAULT 'text',
  content TEXT DEFAULT '',
  media_url TEXT,
  created_at BIGINT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS calls (
  id TEXT PRIMARY KEY,
  from_uid TEXT NOT NULL,
  to_uid TEXT NOT NULL,
  channel TEXT,
  status TEXT DEFAULT 'pending',
  call_type TEXT DEFAULT 'audio',
  created_at BIGINT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS lives (
  id TEXT PRIMARY KEY,
  channel TEXT NOT NULL,
  host_uid TEXT NOT NULL,
  host_name TEXT,
  host_avatar TEXT,
  status TEXT DEFAULT 'live',
  viewer_count INTEGER DEFAULT 0,
  comments JSONB DEFAULT '[]',
  started_at BIGINT DEFAULT 0,
  ended_at BIGINT
);
"""
    return f"<pre style='background:#111;color:#0f0;padding:20px;font-size:12px;overflow:auto;'>{sql}</pre>"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

# ============================
# DEBUG CONFIG (hapus setelah production)
# ============================
@app.route("/api/debug_config")
def api_debug_config():
    """Cek apakah semua env variable sudah terset"""
    return jsonify({
        "SUPABASE_URL": SUPABASE_URL[:30]+"..." if SUPABASE_URL else "KOSONG - belum diset!",
        "SUPABASE_KEY": SUPABASE_KEY[:20]+"..." if SUPABASE_KEY else "KOSONG - belum diset!",
        "CLOUDINARY_CLOUD_NAME": CLOUDINARY_CLOUD_NAME or "KOSONG",
        "CLOUDINARY_API_KEY": CLOUDINARY_API_KEY[:10]+"..." if CLOUDINARY_API_KEY else "KOSONG",
        "CLOUDINARY_API_SECRET": "OK (set)" if CLOUDINARY_API_SECRET else "KOSONG",
        "AGORA_APP_ID": AGORA_APP_ID[:10]+"..." if AGORA_APP_ID else "KOSONG",
        "ANTHROPIC_API_KEY": "OK (set)" if get_anthropic_key() else "KOSONG",
        "supabase_ping": _test_supabase()
    })

def _test_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return "GAGAL: SUPABASE_URL atau SUPABASE_KEY kosong"
    try:
        result = supa_get("users", "select=uid&limit=1")
        if isinstance(result, list):
            return f"OK - terhubung, {len(result)} user ditemukan"
        return f"Respon aneh: {str(result)[:100]}"
    except Exception as e:
        return f"ERROR: {str(e)[:150]}"