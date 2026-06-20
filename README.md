# 💬 Nexus — Premium Real-Time Chat App

A full-featured, production-ready chat application with persistent PostgreSQL database (Supabase), permanent cloud file storage, OTP email verification, 2FA, biometric login, voice/video calls, stories, and more.

## ✅ What Was Fixed From The Previous Version

1. **Database now persists** — switched from SQLite (which resets on every Render deploy) to Supabase PostgreSQL (permanent).
2. **Files now persist** — images, voices, avatars now upload to Supabase Storage instead of local disk (which Render wipes on every deploy).
3. **Register → Login bug fixed** — registering with email now correctly shows the OTP verification screen instead of skipping straight to chat.
4. **Database password URL-encoding bug fixed** — your password contained `@` which broke the connection string; now properly encoded.
5. **Deprecated `broadcast=True` removed** — this was silently crashing socket events on newer flask-socketio versions.
6. **Crash on DM-only messages fixed** — a null-reference bug when computing the socket room key for direct messages.
7. **Gunicorn compatibility fixed** — database tables were never being created in production because `if __name__=='__main__'` doesn't run under gunicorn. Moved init to module level.
8. **Delete option added** — for both messages and stories.
9. **2FA / OTP re-enabled** — with proper dev-mode console fallback if email isn't configured yet.

---

## 🚀 Local Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure `.env`
The `.env` file is already filled in with your Supabase credentials. Just add your Gmail credentials for OTP emails:
```
MAIL_USERNAME=youremail@gmail.com
MAIL_PASSWORD=your-16-digit-app-password
```
(Get an app password at myaccount.google.com → Security → App Passwords)

If you leave these blank, OTP codes will print to your terminal instead — useful for testing without email setup.

### 3. Run locally
```bash
python app.py
```
Visit `http://localhost:5000`

---

## ☁️ Deploy to Render

1. Push this code to GitHub (see below)
2. Go to [render.com](https://render.com) → New → Web Service
3. Connect your GitHub repo
4. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** *(leave blank — it uses the Procfile automatically)*
5. Add Environment Variables (copy each from your `.env` file):
   - `SECRET_KEY`
   - `DATABASE_URL`
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_BUCKET`
   - `MAIL_USERNAME`
   - `MAIL_PASSWORD`
6. Click **Deploy**

Your data will now persist across every redeploy since it lives in Supabase, not on Render's disk.

---

## 🐙 Push to GitHub

```bash
git init
git add .
git commit -m "Nexus chat app - production rebuild with Supabase"
git remote add origin https://github.com/YOUR_USERNAME/nexus-chat.git
git branch -M main
git push -u origin main
```

**Important:** `.env` is in `.gitignore` and will NOT be pushed — your credentials stay private. When you add environment variables on Render, paste them directly into Render's dashboard, not into the code.

---

## ✨ Features

**Auth & Security**
- Register/Login via email, phone, or username
- Email OTP verification on signup
- Optional 2FA (OTP every login)
- Biometric login (fingerprint/face via WebAuthn-style local key)
- Bcrypt password hashing

**Messaging**
- Real-time 1-on-1 DMs and group rooms
- Typing indicators, online/offline status, read receipts
- Reply to messages, emoji reactions
- Pin messages in rooms, pin entire chats
- Delete your own messages
- Search messages within a conversation
- Image, file, and voice note sharing (Supabase Storage — permanent)
- View-once photos
- Custom chat backgrounds (color or image)

**Stories**
- 24-hour disappearing stories (text or image)
- View tracking, delete your own stories

**Calls**
- Voice and video calls via WebRTC (peer-to-peer, no server relay needed)

**Profile**
- Custom avatar, bio
- Personal QR code for easy connecting
- Dark / Light mode

---

## 🧑‍💻 Tech Stack
- **Backend:** Flask, Flask-SocketIO, Flask-Login, Flask-Bcrypt, Flask-Mail
- **Database:** PostgreSQL via Supabase
- **File Storage:** Supabase Storage
- **Real-time:** Socket.IO + WebRTC
- **Frontend:** Vanilla JS, custom CSS (no framework bloat)

---

Built by Ish Dubey — [github.com/Ish1203](https://github.com/Ish1203)
