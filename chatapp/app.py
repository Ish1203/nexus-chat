import os, uuid, random, string, json, base64
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from supabase import create_client, Client

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'nexus-dev-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///nexus.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True, "pool_recycle": 300}
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@app.errorhandler(Exception)
def handle_all_errors(e):
    import traceback
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    print("="*70)
    print("UNHANDLED EXCEPTION:")
    traceback.print_exc()
    print("="*70)
    return jsonify({'error': 'Internal server error', 'detail': str(e)}), 500

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_ANON_KEY', '')
SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', 'nexus-media')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None

# ── Models ────────────────────────────────────────────────────────────────────
room_members = db.Table('room_members',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('room_id', db.Integer, db.ForeignKey('room.id'))
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    password = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.Text, default='')
    bio = db.Column(db.String(300), default='Hey there! I am using Nexus.')
    is_online = db.Column(db.Boolean, default=False)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    theme = db.Column(db.String(10), default='dark')
    chat_bg = db.Column(db.String(100), default='')
    two_fa_enabled = db.Column(db.Boolean, default=False)
    biometric_enabled = db.Column(db.Boolean, default=False)
    biometric_key = db.Column(db.String(64), nullable=True)
    qr_code = db.Column(db.Text, default='')
    is_verified = db.Column(db.Boolean, default=False)
    messages = db.relationship('Message', foreign_keys='Message.user_id', backref='author', lazy=True)
    stories = db.relationship('Story', backref='user', lazy=True)

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(300), default='')
    is_private = db.Column(db.Boolean, default=False)
    is_group = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    avatar = db.Column(db.Text, default='')
    pinned_message_id = db.Column(db.Integer, nullable=True)
    members = db.relationship('User', secondary=room_members, backref='rooms')
    messages = db.relationship('Message', foreign_keys='Message.room_id', backref='room', lazy=True)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    msg_type = db.Column(db.String(20), default='text')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=True)
    dm_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    read_by = db.Column(db.Text, default='[]')
    reply_to = db.Column(db.Integer, nullable=True)
    reply_preview = db.Column(db.Text, default='')
    reactions = db.Column(db.Text, default='{}')
    view_once_viewed = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)
    file_name = db.Column(db.String(200), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    is_pinned = db.Column(db.Boolean, default=False)

class Story(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text, nullable=False)
    story_type = db.Column(db.String(20), default='text')
    bg_color = db.Column(db.String(20), default='#8b5cf6')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    views = db.Column(db.Text, default='[]')
    def __init__(self, **kw):
        super().__init__(**kw)
        if not self.expires_at:
            self.expires_at = datetime.utcnow() + timedelta(hours=24)

class OTPStore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    otp = db.Column(db.String(6), nullable=False)
    purpose = db.Column(db.String(20), default='login')
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)

class PinnedChat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    chat_type = db.Column(db.String(10))
    chat_id = db.Column(db.Integer)

class BlockedUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    blocked_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    reported_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ── Helpers ───────────────────────────────────────────────────────────────────
@login_manager.user_loader
def load_user(uid): return User.query.get(int(uid))

def upload_to_supabase(file_bytes, filename, content_type='application/octet-stream'):
    if not supabase: return None
    try:
        path = f"{uuid.uuid4()}_{filename}"
        supabase.storage.from_(SUPABASE_BUCKET).upload(path, file_bytes, {'content-type': content_type})
        url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(path)
        return url
    except Exception as e:
        print(f"[SUPABASE UPLOAD ERROR] {e}")
        return None

def generate_otp(email, purpose='login'):
    OTPStore.query.filter_by(email=email, purpose=purpose, used=False).delete()
    db.session.commit()
    otp = ''.join(random.choices(string.digits, k=6))
    db.session.add(OTPStore(email=email, otp=otp, purpose=purpose,
                            expires_at=datetime.utcnow() + timedelta(minutes=10)))
    db.session.commit()
    return otp

def verify_otp(email, otp_input, purpose='login'):
    r = OTPStore.query.filter_by(email=email, otp=otp_input, purpose=purpose, used=False).first()
    if not r: return False, 'Invalid OTP — check and try again'
    if datetime.utcnow() > r.expires_at: return False, 'OTP expired — request a new one'
    r.used = True; db.session.commit()
    return True, 'OK'

def send_otp_email(email, otp, purpose='login'):
    """Sends OTP via Brevo's HTTPS API (not SMTP, which Render blocks).
    Brevo allows sending to ANY recipient as long as the sender address is
    verified in the Brevo dashboard — unlike Resend's test mode which only
    allows sending to the account owner's own email."""
    labels = {'login': 'Login', 'register': 'Verify Account', '2fa': '2FA'}
    api_key = os.environ.get('BREVO_API_KEY', '')
    if not api_key:
        print("[MAIL SKIPPED] No BREVO_API_KEY configured.")
        return False

    body = f"""
    <div style="font-family:Inter,sans-serif;max-width:460px;margin:0 auto;background:#0a0a1a;border-radius:16px;overflow:hidden">
      <div style="background:linear-gradient(135deg,#7c3aed,#ec4899);padding:28px;text-align:center">
        <h1 style="color:white;margin:0;font-size:26px;font-weight:700;letter-spacing:-0.5px">Nexus</h1>
        <p style="color:rgba(255,255,255,0.8);margin:4px 0 0;font-size:13px">The future of conversation</p>
      </div>
      <div style="padding:32px;text-align:center">
        <h2 style="color:white;margin:0 0 8px;font-size:18px">{labels.get(purpose,'Verification')} Code</h2>
        <p style="color:rgba(255,255,255,0.5);font-size:13px;margin:0 0 24px">Expires in 10 minutes. Do not share this code.</p>
        <div style="background:rgba(139,92,246,0.15);border:1px solid rgba(139,92,246,0.4);border-radius:14px;padding:20px 40px;display:inline-block;margin-bottom:24px">
          <span style="font-size:40px;font-weight:700;letter-spacing:12px;color:#c4b5fd;font-family:monospace">{otp}</span>
        </div>
        <p style="color:rgba(255,255,255,0.3);font-size:12px;margin:0">If you didn't request this, ignore this email.</p>
      </div>
    </div>"""

    sender_email = os.environ.get('BREVO_SENDER_EMAIL', 'nexuschat.auth@gmail.com')
    sender_name = os.environ.get('BREVO_SENDER_NAME', 'Nexus')

    try:
        import requests
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "sender": {"name": sender_name, "email": sender_email},
                "to": [{"email": email}],
                "subject": f"Nexus {labels.get(purpose,'')}: {otp}",
                "htmlContent": body,
            },
            timeout=8,
        )
        if resp.status_code in (200, 201):
            return True
        print(f"[MAIL ERROR] Brevo API returned {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        print(f"[MAIL ERROR] {e}")
        return False

def generate_qr_b64(user):
    import qrcode, io
    data = f"nexus://user/{user.id}/{user.username}"
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(data); qr.make(fit=True)
    img = qr.make_image(fill_color="#8b5cf6", back_color="white")
    buf = io.BytesIO(); img.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"

def msg_to_dict(m):
    try: reactions = json.loads(m.reactions or '{}')
    except: reactions = {}
    try: read_by = json.loads(m.read_by or '[]')
    except: read_by = []
    return {
        'id': m.id,
        'content': '🚫 This message was deleted' if m.is_deleted else m.content,
        'type': m.msg_type,
        'user': m.author.username,
        'user_id': m.user_id,
        'avatar': m.author.avatar or '',
        'timestamp': m.timestamp.strftime('%I:%M %p'),
        'timestamp_full': m.timestamp.strftime('%b %d, %Y %I:%M %p'),
        'reply_to': m.reply_to,
        'reply_preview': m.reply_preview or '',
        'reactions': reactions,
        'read_by': read_by,
        'is_deleted': m.is_deleted,
        'view_once_viewed': m.view_once_viewed,
        'file_name': m.file_name,
        'file_size': m.file_size,
        'is_pinned': m.is_pinned,
        'room_id': m.room_id,
        'dm_to': m.dm_to,
    }

def socket_room_for(room_id=None, dm_to=None, user_a=None, user_b=None):
    if room_id:
        return f'room_{room_id}'
    a = user_a if user_a is not None else None
    b = dm_to if dm_to is not None else user_b
    if a is not None and b is not None:
        return f'dm_{min(a,b)}_{max(a,b)}'
    return None

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('chat'))
    return render_template('landing.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('chat'))
    if request.method == 'POST':
        ident = request.form.get('identifier', '').strip()
        pwd = request.form.get('password', '')
        user = User.query.filter(
            (User.email == ident) | (User.phone == ident) | (User.username == ident)
        ).first()
        if not user or not bcrypt.check_password_hash(user.password, pwd):
            return render_template('auth.html', page='login', error='Wrong username or password')
        if user.two_fa_enabled and user.email:
            otp = generate_otp(user.email, '2fa')
            sent = send_otp_email(user.email, otp, '2fa')
            if not sent: print(f"\n[DEV] 2FA OTP for {user.email}: {otp}\n")
            session['pending_2fa_user'] = user.id
            return redirect(url_for('verify_2fa'))
        login_user(user, remember=True); user.is_online = True; db.session.commit()
        return redirect(url_for('chat'))
    return render_template('auth.html', page='login')

@app.route('/verify-2fa', methods=['GET', 'POST'])
def verify_2fa():
    uid = session.get('pending_2fa_user')
    if not uid: return redirect(url_for('login'))
    user = User.query.get(uid)
    if not user: return redirect(url_for('login'))
    if request.method == 'POST':
        ok, msg = verify_otp(user.email, request.form.get('otp', '').strip(), '2fa')
        if not ok: return render_template('auth.html', page='verify_2fa', error=msg, email=user.email)
        session.pop('pending_2fa_user', None)
        login_user(user, remember=True); user.is_online = True; db.session.commit()
        return redirect(url_for('chat'))
    return render_template('auth.html', page='verify_2fa', email=user.email)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('chat'))
    if request.method == 'POST':
        step = request.form.get('step', 'info')
        if step == 'info':
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip()
            phone = request.form.get('phone', '').strip()
            password = request.form.get('password', '')
            if len(username) < 3:
                return render_template('auth.html', page='register', error='Username must be at least 3 characters')
            if User.query.filter_by(username=username).first():
                return render_template('auth.html', page='register', error='Username already taken')
            if email and User.query.filter_by(email=email).first():
                return render_template('auth.html', page='register', error='Email already registered')
            session['reg'] = {'username': username, 'email': email, 'phone': phone, 'password': password}
            if email:
                otp = generate_otp(email, 'register')
                sent = send_otp_email(email, otp, 'register')
                if not sent: print(f"\n[DEV] Register OTP for {email}: {otp}\n")
                return render_template('auth.html', page='verify_register', email=email)
            hashed = bcrypt.generate_password_hash(password).decode('utf-8')
            user = User(username=username, phone=phone or None, password=hashed, is_verified=True)
            db.session.add(user); db.session.commit()
            user.qr_code = generate_qr_b64(user); db.session.commit()
            login_user(user, remember=True); user.is_online = True; db.session.commit()
            return redirect(url_for('chat'))
        elif step == 'verify':
            reg = session.get('reg', {})
            if not reg: return redirect(url_for('register'))
            ok, msg = verify_otp(reg.get('email', ''), request.form.get('otp', '').strip(), 'register')
            if not ok: return render_template('auth.html', page='verify_register', error=msg, email=reg.get('email'))
            hashed = bcrypt.generate_password_hash(reg['password']).decode('utf-8')
            user = User(username=reg['username'], email=reg['email'] or None,
                        phone=reg.get('phone') or None, password=hashed, is_verified=True)
            db.session.add(user); db.session.commit()
            user.qr_code = generate_qr_b64(user); db.session.commit()
            session.pop('reg', None)
            login_user(user, remember=True); user.is_online = True; db.session.commit()
            return redirect(url_for('chat'))
    return render_template('auth.html', page='register')

@app.route('/logout')
@login_required
def logout():
    current_user.is_online = False; current_user.last_seen = datetime.utcnow()
    db.session.commit(); logout_user()
    return redirect(url_for('login'))

# ── Chat ──────────────────────────────────────────────────────────────────────
@app.route('/chat')
@login_required
def chat():
    rooms = Room.query.filter(Room.members.any(id=current_user.id)).all()
    rooms_data = [{'id': r.id, 'name': r.name, 'description': r.description} for r in rooms]
    return render_template('chat.html', rooms=rooms_data, current_user=current_user)

# ── Rooms API ─────────────────────────────────────────────────────────────────
@app.route('/api/rooms', methods=['POST'])
@login_required
def create_room():
    d = request.json
    room = Room(name=d['name'], description=d.get('description',''),
                created_by=current_user.id, is_group=d.get('is_group', False))
    room.members.append(current_user)
    for uid in (d.get('member_ids') or []):
        u = User.query.get(uid)
        if u and u not in room.members: room.members.append(u)
    db.session.add(room); db.session.commit()
    return jsonify({'id': room.id, 'name': room.name, 'description': room.description})

@app.route('/api/rooms/<int:rid>/join', methods=['POST'])
@login_required
def join_room_api(rid):
    room = Room.query.get_or_404(rid)
    if current_user not in room.members:
        room.members.append(current_user); db.session.commit()
    return jsonify({'success': True})

@app.route('/api/rooms/<int:rid>/messages')
@login_required
def room_messages(rid):
    msgs = Message.query.filter_by(room_id=rid).order_by(Message.timestamp).limit(100).all()
    for m in msgs:
        try:
            rb = json.loads(m.read_by or '[]')
            if current_user.id not in rb: rb.append(current_user.id); m.read_by = json.dumps(rb)
        except: pass
    db.session.commit()
    return jsonify([msg_to_dict(m) for m in msgs])

@app.route('/api/rooms/search')
@login_required
def search_rooms():
    q = request.args.get('q', '')
    rooms = Room.query.filter(Room.name.ilike(f'%{q}%'), Room.is_private == False).limit(10).all()
    return jsonify([{'id': r.id, 'name': r.name, 'description': r.description} for r in rooms])

# ── DM API ────────────────────────────────────────────────────────────────────
@app.route('/api/dm/<int:uid>/messages')
@login_required
def dm_messages(uid):
    msgs = Message.query.filter(
        ((Message.user_id == current_user.id) & (Message.dm_to == uid)) |
        ((Message.user_id == uid) & (Message.dm_to == current_user.id))
    ).order_by(Message.timestamp).limit(100).all()
    for m in msgs:
        if m.dm_to == current_user.id:
            m.is_read = True
            try:
                rb = json.loads(m.read_by or '[]')
                if current_user.id not in rb: rb.append(current_user.id); m.read_by = json.dumps(rb)
            except: pass
    db.session.commit()
    return jsonify([msg_to_dict(m) for m in msgs])

# ── Messages API ──────────────────────────────────────────────────────────────
@app.route('/api/messages/<int:mid>/delete', methods=['POST'])
@login_required
def delete_message(mid):
    m = Message.query.get_or_404(mid)
    if m.user_id != current_user.id: return jsonify({'error': 'Unauthorized'}), 403
    m.is_deleted = True; db.session.commit()
    room = socket_room_for(m.room_id, m.dm_to, m.user_id)
    if room: socketio.emit('message_deleted', {'msg_id': mid}, room=room)
    return jsonify({'success': True})

@app.route('/api/messages/<int:mid>/react', methods=['POST'])
@login_required
def react_message(mid):
    m = Message.query.get_or_404(mid)
    emoji = request.json.get('emoji', '')
    try: reactions = json.loads(m.reactions or '{}')
    except: reactions = {}
    if emoji not in reactions: reactions[emoji] = []
    if current_user.id in reactions[emoji]: reactions[emoji].remove(current_user.id)
    else: reactions[emoji].append(current_user.id)
    if not reactions[emoji]: del reactions[emoji]
    m.reactions = json.dumps(reactions); db.session.commit()
    room = socket_room_for(m.room_id, m.dm_to, m.user_id)
    if room: socketio.emit('reaction_update', {'msg_id': mid, 'reactions': reactions}, room=room)
    return jsonify({'reactions': reactions})

@app.route('/api/messages/<int:mid>/pin', methods=['POST'])
@login_required
def pin_message(mid):
    m = Message.query.get_or_404(mid)
    m.is_pinned = not m.is_pinned
    if m.room_id:
        room = Room.query.get(m.room_id)
        if room: room.pinned_message_id = mid if m.is_pinned else None
        socketio.emit('message_pinned', msg_to_dict(m), room=f'room_{m.room_id}')
    db.session.commit()
    return jsonify({'success': True, 'is_pinned': m.is_pinned})

@app.route('/api/messages/<int:mid>/view-once', methods=['POST'])
@login_required
def view_once(mid):
    m = Message.query.get_or_404(mid)
    m.view_once_viewed = True; db.session.commit()
    return jsonify({'success': True})

@app.route('/api/messages/search')
@login_required
def search_messages():
    q = request.args.get('q', '')
    room_id = request.args.get('room_id')
    dm_id = request.args.get('dm_id')
    query = Message.query.filter(Message.content.ilike(f'%{q}%'), Message.is_deleted == False)
    if room_id: query = query.filter_by(room_id=int(room_id))
    elif dm_id:
        uid = int(dm_id)
        query = query.filter(
            ((Message.user_id == current_user.id) & (Message.dm_to == uid)) |
            ((Message.user_id == uid) & (Message.dm_to == current_user.id))
        )
    return jsonify([msg_to_dict(m) for m in query.order_by(Message.timestamp.desc()).limit(20).all()])

# ── Upload API ────────────────────────────────────────────────────────────────
@app.route('/api/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    msg_type = request.form.get('type', 'file')
    view_once = request.form.get('view_once', 'false') == 'true'
    room_id = request.form.get('room_id')
    dm_to = request.form.get('dm_to')
    fname = f"{uuid.uuid4()}_{f.filename}"
    file_bytes = f.read()
    url = upload_to_supabase(file_bytes, fname, f.content_type or 'application/octet-stream')
    if not url: return jsonify({'error': 'Upload failed — check Supabase storage bucket and policies'}), 500
    final_type = 'view_once' if view_once else msg_type
    msg = Message(content=url, msg_type=final_type, user_id=current_user.id,
                  room_id=int(room_id) if room_id else None,
                  dm_to=int(dm_to) if dm_to else None,
                  file_name=f.filename, file_size=len(file_bytes))
    db.session.add(msg); db.session.commit()
    payload = msg_to_dict(msg)
    room = socket_room_for(msg.room_id, msg.dm_to, current_user.id)
    if room: socketio.emit('new_message', payload, room=room)
    return jsonify({'success': True, 'url': url})

@app.route('/api/voice', methods=['POST'])
@login_required
def upload_voice():
    d = request.json
    audio_b64 = d.get('audio', '')
    audio_bytes = base64.b64decode(audio_b64.split(',')[-1])
    fname = f"{uuid.uuid4()}.webm"
    url = upload_to_supabase(audio_bytes, fname, 'audio/webm')
    if not url: return jsonify({'error': 'Upload failed — check Supabase storage bucket and policies'}), 500
    msg = Message(content=url, msg_type='voice', user_id=current_user.id,
                  room_id=d.get('room_id'), dm_to=d.get('dm_to'))
    db.session.add(msg); db.session.commit()
    payload = msg_to_dict(msg)
    room = socket_room_for(msg.room_id, msg.dm_to, current_user.id)
    if room: socketio.emit('new_message', payload, room=room)
    return jsonify({'success': True})

# ── Stories API ───────────────────────────────────────────────────────────────
@app.route('/api/stories', methods=['GET'])
@login_required
def get_stories():
    stories = Story.query.filter(Story.expires_at > datetime.utcnow()).order_by(Story.created_at.desc()).limit(50).all()
    result = []
    for s in stories:
        try: views = json.loads(s.views or '[]')
        except: views = []
        result.append({'id': s.id, 'user_id': s.user_id, 'username': s.user.username,
                       'avatar': s.user.avatar or '', 'content': s.content, 'type': s.story_type,
                       'bg_color': s.bg_color, 'created_at': s.created_at.isoformat(),
                       'viewed': current_user.id in views, 'views_count': len(views)})
    return jsonify(result)

@app.route('/api/stories', methods=['POST'])
@login_required
def create_story():
    if 'file' in request.files:
        f = request.files['file']
        url = upload_to_supabase(f.read(), f"{uuid.uuid4()}_{f.filename}", f.content_type or 'image/jpeg')
        if not url: return jsonify({'error': 'Upload failed — check Supabase storage bucket and policies'}), 500
        content, stype = url, 'image'
        bg = request.form.get('bg_color', '#0f172a')
    else:
        d = request.json or {}
        content, stype = d.get('content', ''), 'text'
        bg = d.get('bg_color', '#8b5cf6')
    if not content: return jsonify({'error': 'No content'}), 400
    story = Story(user_id=current_user.id, content=content, story_type=stype, bg_color=bg)
    db.session.add(story); db.session.commit()
    socketio.emit('new_story', {'user_id': current_user.id, 'username': current_user.username})
    return jsonify({'success': True, 'id': story.id})

@app.route('/api/stories/<int:sid>/view', methods=['POST'])
@login_required
def view_story(sid):
    s = Story.query.get_or_404(sid)
    try: views = json.loads(s.views or '[]')
    except: views = []
    if current_user.id not in views: views.append(current_user.id); s.views = json.dumps(views); db.session.commit()
    return jsonify({'success': True})

@app.route('/api/stories/<int:sid>/delete', methods=['POST'])
@login_required
def delete_story(sid):
    s = Story.query.get_or_404(sid)
    if s.user_id != current_user.id: return jsonify({'error': 'Unauthorized'}), 403
    db.session.delete(s); db.session.commit()
    return jsonify({'success': True})

# ── Users API ─────────────────────────────────────────────────────────────────
@app.route('/api/users/search')
@login_required
def search_users():
    q = request.args.get('q', '')
    users = User.query.filter(User.username.ilike(f'%{q}%'), User.id != current_user.id).limit(10).all()
    blocked = [b.blocked_id for b in BlockedUser.query.filter_by(blocker_id=current_user.id).all()]
    return jsonify([{'id': u.id, 'username': u.username, 'is_online': u.is_online,
                     'avatar': u.avatar or '', 'bio': u.bio, 'is_blocked': u.id in blocked} for u in users])

@app.route('/api/users/<int:uid>/block', methods=['POST'])
@login_required
def block_user(uid):
    existing = BlockedUser.query.filter_by(blocker_id=current_user.id, blocked_id=uid).first()
    if existing: db.session.delete(existing); db.session.commit(); return jsonify({'blocked': False})
    db.session.add(BlockedUser(blocker_id=current_user.id, blocked_id=uid)); db.session.commit()
    return jsonify({'blocked': True})

@app.route('/api/users/<int:uid>/report', methods=['POST'])
@login_required
def report_user(uid):
    reason = request.json.get('reason', 'Inappropriate behavior')
    db.session.add(Report(reporter_id=current_user.id, reported_id=uid, reason=reason)); db.session.commit()
    return jsonify({'success': True})

@app.route('/api/users/<int:uid>/qr')
@login_required
def get_user_qr(uid):
    user = User.query.get_or_404(uid)
    if not user.qr_code: user.qr_code = generate_qr_b64(user); db.session.commit()
    return jsonify({'qr': user.qr_code, 'username': user.username})

@app.route('/api/profile/update', methods=['POST'])
@login_required
def update_profile():
    if request.is_json:
        d = request.json
        if 'bio' in d: current_user.bio = d['bio']
        if 'theme' in d and d['theme'] in ('dark','light'): current_user.theme = d['theme']
        if 'chat_bg' in d: current_user.chat_bg = d['chat_bg']
    else:
        if 'bio' in request.form: current_user.bio = request.form['bio']
        if 'avatar' in request.files:
            f = request.files['avatar']
            if f.filename:
                url = upload_to_supabase(f.read(), f"{uuid.uuid4()}_{f.filename}", f.content_type or 'image/jpeg')
                if url: current_user.avatar = url
    db.session.commit()
    return jsonify({'success': True, 'avatar': current_user.avatar, 'bio': current_user.bio})

@app.route('/api/chats/pin', methods=['POST'])
@login_required
def pin_chat():
    d = request.json
    chat_type, chat_id = d.get('type'), d.get('id')
    existing = PinnedChat.query.filter_by(user_id=current_user.id, chat_type=chat_type, chat_id=chat_id).first()
    if existing: db.session.delete(existing); db.session.commit(); return jsonify({'pinned': False})
    db.session.add(PinnedChat(user_id=current_user.id, chat_type=chat_type, chat_id=chat_id)); db.session.commit()
    return jsonify({'pinned': True})

@app.route('/api/2fa/toggle', methods=['POST'])
@login_required
def toggle_2fa():
    current_user.two_fa_enabled = not current_user.two_fa_enabled; db.session.commit()
    return jsonify({'enabled': current_user.two_fa_enabled})

@app.route('/api/biometric/register', methods=['POST'])
@login_required
def reg_biometric():
    key = str(uuid.uuid4())
    current_user.biometric_enabled = True; current_user.biometric_key = key
    db.session.commit()
    return jsonify({'success': True, 'key': key})

@app.route('/api/biometric/login', methods=['POST'])
def bio_login():
    key = request.json.get('key', '')
    user = User.query.filter_by(biometric_key=key, biometric_enabled=True).first()
    if not user: return jsonify({'success': False}), 401
    login_user(user, remember=True); user.is_online = True; db.session.commit()
    return jsonify({'success': True, 'redirect': '/chat'})

@app.route('/api/send-otp', methods=['POST'])
def send_otp_route():
    email = request.json.get('email', '')
    purpose = request.json.get('purpose', 'login')
    if purpose == 'login' and not User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'error': 'Email not found'})
    otp = generate_otp(email, purpose)
    sent = send_otp_email(email, otp, purpose)
    if not sent: print(f"\n[DEV] OTP for {email}: {otp}\n")
    return jsonify({'success': True, 'dev': not sent})

@app.route('/api/theme', methods=['POST'])
@login_required
def set_theme():
    t = request.json.get('theme', 'dark')
    if t in ('dark','light'): current_user.theme = t; db.session.commit()
    return jsonify({'theme': current_user.theme})

# ── WebRTC Signaling ──────────────────────────────────────────────────────────
@socketio.on('call_offer')
def on_call_offer(d): emit('call_offer', {**d, 'caller_id': current_user.id, 'caller_name': current_user.username, 'caller_avatar': current_user.avatar}, room=f"user_{d['target_id']}")

@socketio.on('call_answer')
def on_call_answer(d): emit('call_answer', d, room=f"user_{d['target_id']}")

@socketio.on('call_ice')
def on_call_ice(d): emit('call_ice', d, room=f"user_{d['target_id']}")

@socketio.on('call_end')
def on_call_end(d): emit('call_end', d, room=f"user_{d['target_id']}")

# ── WebSocket ─────────────────────────────────────────────────────────────────
@socketio.on('connect')
def on_connect():
    if current_user.is_authenticated:
        current_user.is_online = True; db.session.commit()
        join_room(f'user_{current_user.id}')
        emit('user_status', {'user_id': current_user.id, 'is_online': True})

@socketio.on('disconnect')
def on_disconnect():
    if current_user.is_authenticated:
        current_user.is_online = False; current_user.last_seen = datetime.utcnow(); db.session.commit()
        emit('user_status', {'user_id': current_user.id, 'is_online': False})

@socketio.on('join_room')
def on_join(d): join_room(d['room'])

@socketio.on('leave_room')
def on_leave(d): leave_room(d['room'])

@socketio.on('join_dm')
def on_join_dm(d):
    other = d.get('user_id')
    if other is None: return
    join_room(f'dm_{min(current_user.id,other)}_{max(current_user.id,other)}')

@socketio.on('send_message')
def handle_message(d):
    content = d.get('content','').strip()
    if not content: return
    reply_preview = ''
    if d.get('reply_to'):
        orig = Message.query.get(d['reply_to'])
        if orig: reply_preview = orig.content[:60]
    msg = Message(content=content, user_id=current_user.id,
                  room_id=d.get('room_id'), dm_to=d.get('dm_to'),
                  reply_to=d.get('reply_to'), reply_preview=reply_preview)
    db.session.add(msg); db.session.commit()
    payload = msg_to_dict(msg)
    room = socket_room_for(msg.room_id, msg.dm_to, current_user.id)
    if room: emit('new_message', payload, room=room)

@socketio.on('typing')
def handle_typing(d):
    emit('user_typing', {'user': current_user.username, 'typing': d.get('typing')},
         room=d.get('room'), include_self=False)

# ── DB Init (module level, runs under gunicorn too) ────────────────────────────
with app.app_context():
    try:
        db.create_all()
        if not Room.query.filter_by(name='General').first():
            g = Room(name='General', description='Welcome to Nexus! 👋', created_by=1)
            db.session.add(g)
            db.session.commit()
    except Exception as e:
        print(f"[DB INIT WARNING] {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    socketio.run(app, debug=debug_mode, host='0.0.0.0', port=port)