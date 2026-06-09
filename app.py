"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         SUNRISE ACADEMY - School Management System                          ║
║         Professional Edition for Malawi Schools                             ║
║                                                                              ║
║  SETUP:                                                                      ║
║    pip install flask flask-cors bcrypt weasyprint pillow pytesseract        ║
║                                                                              ║
║  ENV VARIABLES (optional for email/whatsapp):                                ║
║    EMAIL_USER, EMAIL_PASS, EMAIL_HOST, EMAIL_PORT                           ║
║    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_WHATSAPP             ║
║                                                                              ║
║  DEFAULT ADMIN: admin@school.mw / Admin@2025                                ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from flask import (Flask, render_template_string, request, jsonify,
                   send_file, session, redirect, url_for)
from flask_cors import CORS
import bcrypt, os, base64, io, re, json, smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor

# ── Database configuration (PostgreSQL only) ─────────────────────────────────
DATABASE_URL = os.environ.get('DATABASE_URL', '')

USE_POSTGRES = DATABASE_URL and DATABASE_URL.startswith('postgres')

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    conn.autocommit = False
    return conn

def q(conn, sql, params=()):
    """Execute a query and return the cursor. Converts ? → %s for PostgreSQL."""
    pg_sql = sql.replace('?', '%s')
    cur = conn.cursor()
    cur.execute(pg_sql, params)
    return cur
# ── Optional heavy dependencies ───────────────────────────────────────────────
try:
    from weasyprint import HTML as WeasyHTML; HAS_PDF = True
except Exception: HAS_PDF = False

try:
    from PIL import Image; HAS_PIL = True
except Exception: HAS_PIL = False

try:
    import pytesseract; HAS_OCR = True
except Exception: HAS_OCR = False

# ══════════════════════════════════════════════════════════════════════════════
# APP CONFIG
# ══════════════════════════════════════════════════════════════════════════════
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'sunrise-sms-secret-2025-mw')
CORS(app, supports_credentials=True)

SCHOOL_NAME = os.environ.get('SCHOOL_NAME', 'Sunrise Academy')
EMAIL_USER  = os.environ.get('EMAIL_USER', '')
EMAIL_PASS  = os.environ.get('EMAIL_PASS', '')
EMAIL_HOST  = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT  = int(os.environ.get('EMAIL_PORT', 587))
TWILIO_SID  = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_TKN  = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_FROM = os.environ.get('TWILIO_FROM_WHATSAPP', 'whatsapp:+14155238886')

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # Create tables - PostgreSQL compatible
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password BYTEA NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            whatsapp TEXT,
            role TEXT NOT NULL CHECK(role IN ('admin','teacher')),
            approved INTEGER DEFAULT 0,
            subjects_note TEXT,
            avatar_color TEXT DEFAULT '#4f46e5',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS classes (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            grade_level INTEGER DEFAULT 1,
            stream TEXT,
            academic_year TEXT DEFAULT '2025',
            class_teacher_id INTEGER,
            FOREIGN KEY(class_teacher_id) REFERENCES users(id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS subjects (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT,
            max_marks INTEGER DEFAULT 100,
            pass_mark INTEGER DEFAULT 50
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            admission_number TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            gender TEXT,
            date_of_birth TEXT,
            class_id INTEGER,
            parent_name TEXT,
            parent_email TEXT,
            parent_phone TEXT,
            parent_whatsapp TEXT,
            address TEXT,
            photo_url TEXT,
            enrolled_date TEXT DEFAULT CURRENT_DATE,
            active INTEGER DEFAULT 1,
            FOREIGN KEY(class_id) REFERENCES classes(id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS teacher_subjects (
            id SERIAL PRIMARY KEY,
            teacher_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            UNIQUE(teacher_id, subject_id, class_id),
            FOREIGN KEY(teacher_id) REFERENCES users(id),
            FOREIGN KEY(subject_id) REFERENCES subjects(id),
            FOREIGN KEY(class_id) REFERENCES classes(id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS grades (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            teacher_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            score REAL,
            max_score REAL DEFAULT 100,
            method TEXT DEFAULT 'manual',
            term TEXT NOT NULL,
            academic_year TEXT DEFAULT '2025',
            comment TEXT,
            entered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, subject_id, term, academic_year),
            FOREIGN KEY(student_id) REFERENCES students(id),
            FOREIGN KEY(subject_id) REFERENCES subjects(id),
            FOREIGN KEY(teacher_id) REFERENCES users(id),
            FOREIGN KEY(class_id) REFERENCES classes(id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            teacher_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('present','absent','late','excused')),
            note TEXT,
            UNIQUE(student_id, date),
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS report_deliveries (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL,
            term TEXT NOT NULL,
            academic_year TEXT DEFAULT '2025',
            channel TEXT NOT NULL,
            recipient TEXT,
            status TEXT DEFAULT 'sent',
            error_msg TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS announcements (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            author_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS fees (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL,
            academic_year TEXT DEFAULT '2025',
            term TEXT NOT NULL,
            amount_due REAL DEFAULT 0,
            amount_paid REAL DEFAULT 0,
            due_date TEXT,
            paid_date TEXT,
            status TEXT DEFAULT 'unpaid',
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS homework (
            id SERIAL PRIMARY KEY,
            teacher_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            due_date TEXT,
            max_marks INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(teacher_id) REFERENCES users(id),
            FOREIGN KEY(class_id) REFERENCES classes(id),
            FOREIGN KEY(subject_id) REFERENCES subjects(id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS homework_submissions (
            id SERIAL PRIMARY KEY,
            homework_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            marks INTEGER,
            note TEXT,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(homework_id, student_id),
            FOREIGN KEY(homework_id) REFERENCES homework(id),
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS school_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS timetable (
            id SERIAL PRIMARY KEY,
            class_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            teacher_id INTEGER,
            day_of_week INTEGER NOT NULL CHECK(day_of_week BETWEEN 1 AND 5),
            period INTEGER NOT NULL CHECK(period BETWEEN 1 AND 10),
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            room TEXT,
            academic_year TEXT DEFAULT '2025',
            UNIQUE(class_id, day_of_week, period, academic_year),
            FOREIGN KEY(class_id) REFERENCES classes(id),
            FOREIGN KEY(subject_id) REFERENCES subjects(id),
            FOREIGN KEY(teacher_id) REFERENCES users(id)
        )
    ''')

    # Seed admin
    pwd = bcrypt.hashpw('Admin@2025'.encode(), bcrypt.gensalt())
    try:
        c.execute("INSERT INTO users (username, password, full_name, email, role, approved, avatar_color) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                  ('admin@school.mw', pwd, 'System Administrator', 'admin@school.mw', 'admin', 1, '#4f46e5'))
    except:
        pass

    # Seed subjects
    for name, code, mx in [
        ('Mathematics','MATH',100),('English Language','ENG',100),
        ('Chichewa','CHICH',100),('Integrated Science','SCI',100),
        ('Social Studies','SOC',100),('Religious Education','RE',100),
        ('Expressive Arts','ARTS',100),('Life Skills','LIFE',100)]:
        try:
            c.execute("INSERT OR IGNORE INTO subjects(name, code, max_marks) VALUES(%s,%s,%s)", (name, code, mx))
        except:
            pass

    # Seed classes
    for name, gl, st in [
        ('Standard 1 A',1,'A'),('Standard 1 B',1,'B'),
        ('Standard 2 A',2,'A'),('Standard 3 A',3,'A'),
        ('Standard 4 A',4,'A'),('Standard 5 A',5,'A'),
        ('Standard 6 A',6,'A'),('Standard 7 A',7,'A'),('Standard 8 A',8,'A')]:
        try:
            c.execute("INSERT OR IGNORE INTO classes(name, grade_level, stream) VALUES(%s,%s,%s)", (name, gl, st))
        except:
            pass

    conn.commit()
    conn.close()
    print("✅ Database initialised (PostgreSQL)")

init_db()

# ══════════════════════════════════════════════════════════════════════════════
# DECORATORS
# ══════════════════════════════════════════════════════════════════════════════
def login_required(f):
    @wraps(f)
    def d(*a, **kw):
        if 'user_id' not in session:
            return (jsonify({'error':'Login required'}),401) if request.is_json else redirect('/')
        return f(*a, **kw)
    return d

def admin_required(f):
    @wraps(f)
    def d(*a, **kw):
        if session.get('role') != 'admin':
            return jsonify({'error':'Admin access required'}), 403
        return f(*a, **kw)
    return d

# ══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════════════════════════
def grade_letter(score, max_s=100):
    pct = (score / max_s) * 100 if max_s else 0
    if pct >= 80: return 'A', 'Distinction',   '#059669'
    if pct >= 65: return 'B', 'Credit',         '#0284c7'
    if pct >= 50: return 'C', 'Pass',           '#d97706'
    if pct >= 40: return 'D', 'Satisfactory',   '#ea580c'
    return             'F', 'Fail',             '#dc2626'

def send_email(to, subject, body_html, attachments=None):
    """Send email using Brevo API"""
    api_key = os.environ.get('BREVO_API_KEY')
    if not api_key:
        print("Brevo API key not configured")
        return False, "Brevo API key not configured"
    
    try:
        import sib_api_v3_sdk
        from sib_api_v3_sdk.rest import ApiException
        import base64
        
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = api_key
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))
        
        # Prepare email data
        email_data = {
            'to': [{'email': to}],
            'sender': {'email': os.environ.get('EMAIL_USER', 'reports@school.com'), 'name': SCHOOL_NAME},
            'subject': subject,
            'html_content': body_html
        }
        
        # Add attachment if provided
        if attachments:
            attachment_list = []
            for name, data in attachments:
                attachment_list.append({
                    'content': base64.b64encode(data).decode(),
                    'name': name
                })
            email_data['attachment'] = attachment_list
        
        # Create and send email
        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(**email_data)
        api_response = api_instance.send_transac_email(send_smtp_email)
        
        print(f"✅ Email sent to {to}")
        return True, f"Sent via Brevo"
        
    except Exception as e:
        print(f"Email error: {e}")
        return False, str(e)

def send_whatsapp(to, body):
    if not TWILIO_SID:
        return False, "Twilio not configured (set TWILIO_ACCOUNT_SID env var)"
    try:
        from twilio.rest import Client
        Client(TWILIO_SID, TWILIO_TKN).messages.create(
            from_=TWILIO_FROM, to=f"whatsapp:{to}", body=body)
        return True, "Sent"
    except Exception as e:
        return False, str(e)

def build_report_pdf(student, grades, cls_name, term, acad_year):
    if not grades:
        return None
    total = sum(g['score'] or 0 for g in grades)
    avg   = total / len(grades)
    ltr, rmk, clr = grade_letter(avg)

    rows = ''.join(f"""
      <tr>
        <td class="sub">{g['subject_name']}</td>
        <td class="num">{int(g['max_score'] or 100)}</td>
        <td class="num fw">{int(g['score'] or 0)}</td>
        <td class="num">{int((g['score'] or 0)/(g['max_score'] or 100)*100)}%</td>
        <td class="num">
          <span class="chip" style="background:{'#d1fae5' if (g['score'] or 0)>=(g['max_score'] or 100)*0.8 else '#dbeafe' if (g['score'] or 0)>=(g['max_score'] or 100)*0.65 else '#fef3c7' if (g['score'] or 0)>=(g['max_score'] or 100)*0.5 else '#fee2e2'};
          color:{'#065f46' if (g['score'] or 0)>=(g['max_score'] or 100)*0.8 else '#1e40af' if (g['score'] or 0)>=(g['max_score'] or 100)*0.65 else '#78350f' if (g['score'] or 0)>=(g['max_score'] or 100)*0.5 else '#7f1d1d'}">
          {grade_letter(g['score'] or 0, g['max_score'] or 100)[0]}</span>
        </td>
        <td class="com">{g.get('comment','') or '—'}</td>
      </tr>""" for g in grades)

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:Arial,sans-serif;background:#fff;color:#1a1a2e;font-size:13px;padding:30px}}
  .hdr{{text-align:center;border-bottom:3px solid #4f46e5;padding-bottom:16px;margin-bottom:22px}}
  .school{{font-size:24px;font-weight:900;color:#4f46e5;letter-spacing:1px}}
  .motto{{font-size:12px;color:#6b7280;margin:4px 0 10px}}
  .rtitle{{display:inline-block;background:#4f46e5;color:#fff;padding:5px 22px;border-radius:20px;font-size:14px;font-weight:700}}
  .info-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:18px}}
  .info-box{{background:#f5f3ff;border-left:4px solid #4f46e5;padding:10px 14px;border-radius:4px}}
  .il{{font-size:10px;font-weight:700;color:#4f46e5;text-transform:uppercase;letter-spacing:.5px}}
  .iv{{font-size:14px;font-weight:700;color:#111;margin-top:3px}}
  table{{width:100%;border-collapse:collapse;margin-bottom:18px}}
  th{{background:#4f46e5;color:#fff;padding:9px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.4px}}
  td{{padding:9px 12px;border-bottom:1px solid #f0f0f8}}
  tr:nth-child(even) td{{background:#fafafe}}
  .sub{{font-weight:600}}.num{{text-align:center}}.fw{{font-weight:800}}.com{{font-size:11px;color:#6b7280}}
  .chip{{padding:2px 9px;border-radius:10px;font-size:12px;font-weight:800}}
  .summary{{background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#fff;padding:16px 20px;border-radius:12px;
    display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}}
  .sl{{font-size:10px;opacity:.8;text-transform:uppercase;letter-spacing:.4px}}
  .sv{{font-size:22px;font-weight:900;margin-top:4px}}
  .sigs{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-top:24px}}
  .sig{{text-align:center;padding-top:8px;border-top:1.5px solid #4f46e5;font-size:11px;color:#6b7280}}
  .footer{{text-align:center;margin-top:20px;font-size:10px;color:#9ca3af;border-top:1px solid #e5e7eb;padding-top:12px}}
  .conduct{{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:12px;margin-bottom:14px}}
  .conduct h4{{font-size:12px;color:#059669;font-weight:700;margin-bottom:6px;text-transform:uppercase}}
</style>
</head><body>
<div class="hdr">
  <div style="font-size:40px;margin-bottom:6px">🏫</div>
  <div class="school">{SCHOOL_NAME}</div>
  <div class="motto">Excellence · Integrity · Service</div>
  <div class="rtitle">📋 {term} — Academic Report Card {acad_year}</div>
</div>

<div class="info-grid">
  <div class="info-box"><div class="il">Student Name</div><div class="iv">{student['full_name']}</div></div>
  <div class="info-box"><div class="il">Admission No.</div><div class="iv">{student['admission_number']}</div></div>
  <div class="info-box"><div class="il">Class</div><div class="iv">{cls_name}</div></div>
  <div class="info-box"><div class="il">Date of Issue</div><div class="iv">{datetime.now().strftime('%d %B %Y')}</div></div>
</div>

<table>
  <thead><tr><th>Subject</th><th>Max</th><th>Score</th><th>%</th><th>Grade</th><th>Teacher's Remark</th></tr></thead>
  <tbody>{rows}</tbody>
</table>

<div class="summary">
  <div><div class="sl">Subjects</div><div class="sv">{len(grades)}</div></div>
  <div><div class="sl">Total Score</div><div class="sv">{int(total)}</div></div>
  <div><div class="sl">Average</div><div class="sv">{avg:.1f}%</div></div>
  <div><div class="sl">Overall Grade</div>
    <div class="sv"><span style="background:rgba(255,255,255,.25);padding:2px 12px;border-radius:10px">{ltr} — {rmk}</span></div>
  </div>
</div>

<div class="conduct">
  <h4>🌟 Conduct &amp; Comments</h4>
  <p style="font-size:12px;color:#374151">Overall performance: <strong>{rmk}</strong>.
  {'Excellent work! Keep it up and continue striving for the best.' if ltr == 'A' else
   'Good performance. With more effort, distinction is achievable.' if ltr == 'B' else
   'Satisfactory. More dedication and practice will improve results.' if ltr == 'C' else
   'Needs improvement. Please seek extra help and study regularly.' if ltr == 'D' else
   'Results are below expectation. Urgent improvement needed. Parents are advised to provide additional support.'}</p>
</div>

<div class="sigs">
  <div class="sig">Class Teacher<br><br>__________________</div>
  <div class="sig">Head Teacher<br><br>__________________</div>
  <div class="sig">Parent / Guardian<br><br>__________________</div>
</div>

<div class="footer">
  This report was generated by {SCHOOL_NAME} School Management System on {datetime.now().strftime('%d %B %Y at %H:%M')}.<br>
  For enquiries contact the school office.
</div>
</body></html>"""

    if HAS_PDF:
        return WeasyHTML(string=html).write_pdf()
    return html.encode('utf-8')   # fallback: return HTML

# ══════════════════════════════════════════════════════════════════════════════
# ROUTES: PAGES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect('/admin' if session['role'] == 'admin' else '/teacher')
    return render_template_string(LOGIN_HTML)

@app.route('/admin')
@login_required
@admin_required
def admin_page():
    return render_template_string(ADMIN_HTML,
        name=session.get('full_name','Admin'), school=SCHOOL_NAME)

@app.route('/teacher')
@login_required
def teacher_page():
    if session.get('role') != 'teacher':
        return redirect('/')
    if not session.get('approved'):
        return render_template_string(PENDING_HTML,
            name=session.get('full_name','Teacher'), school=SCHOOL_NAME)
    return render_template_string(TEACHER_HTML,
        name=session.get('full_name','Teacher'), school=SCHOOL_NAME)

# ══════════════════════════════════════════════════════════════════════════════
# AUTH APIs
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/login', methods=['POST'])
def api_login():
    d = request.json or {}
    conn = get_db()
    u = q(conn, "SELECT * FROM users WHERE username=?", (d.get('username',''),)).fetchone()
    conn.close()
    if u and bcrypt.checkpw(d.get('password','').encode(), u['password'].encode() if isinstance(u['password'], str) else u['password']):
        session.update({'user_id':u['id'],'username':u['username'],
                        'full_name':u['full_name'],'role':u['role'],
                        'approved':bool(u['approved'])})
        return jsonify({'ok':True,'role':u['role'],'approved':bool(u['approved'])})
    return jsonify({'ok':False,'msg':'Invalid email or password'}), 401

@app.route('/api/logout')
def api_logout():
    session.clear(); return redirect('/')

@app.route('/api/register', methods=['POST'])
def api_register():
    d = request.json or {}
    if not all(d.get(k) for k in ['full_name','email','password']):
        return jsonify({'ok':False,'msg':'Name, email and password are required'}), 400
    try:
        conn = get_db()
        # Hash the password and store as string
        pwd = bcrypt.hashpw(d['password'].encode('utf-8'), bcrypt.gensalt())
        pwd_str = pwd.decode('utf-8')
        
        if USE_POSTGRES:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO users (username, password, full_name, email, phone, whatsapp, role, approved, subjects_note)
                VALUES (%s, %s, %s, %s, %s, %s, 'teacher', 0, %s)
            """, (d['email'], pwd_str, d['full_name'], d['email'],
                  d.get('phone',''), d.get('whatsapp',''), d.get('subjects_note','')))
        else:
            q(conn, """INSERT INTO users(username,password,full_name,email,phone,whatsapp,
                       role,approved,subjects_note) VALUES(?,?,?,?,?,?,'teacher',0,?)""",
              (d['email'], pwd_str, d['full_name'], d['email'],
               d.get('phone',''), d.get('whatsapp',''), d.get('subjects_note','')))
        conn.commit()
        conn.close()
        return jsonify({'ok':True,'msg':'Registration submitted. Await admin approval.'})
    except Exception as e:
        print(f"Registration error: {e}")
        return jsonify({'ok':False,'msg':'Email already registered' if 'UNIQUE' in str(e) else str(e)}), 409

@app.route('/api/change-password', methods=['POST'])
@login_required
def api_change_password():
    d = request.json or {}
    conn = get_db()
    u = q(conn,"SELECT password FROM users WHERE id=?",(session['user_id'],)).fetchone()
    if not u or not bcrypt.checkpw(d.get('old','').encode(), u['password']):
        conn.close(); return jsonify({'ok':False,'msg':'Current password is wrong'}), 401
    q(conn,"UPDATE users SET password=%s WHERE id=%s",
                 (bcrypt.hashpw(d['new'].encode(), bcrypt.gensalt()), session['user_id']))
    conn.commit(); conn.close()
    return jsonify({'ok':True,'msg':'Password changed!'})

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN APIs
# ══════════════════════════════════════════════════════════════════════════════

# ── TEACHERS ─────────────────────────────────────────────────────────────────
@app.route('/api/admin/teachers')
@login_required
@admin_required
def admin_teachers():
    conn = get_db()
    rows = q(conn,"""SELECT id,full_name,username,phone,whatsapp,approved,
                     subjects_note,avatar_color,created_at
                     FROM users WHERE role='teacher' ORDER BY full_name""").fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route('/api/admin/teachers/add', methods=['POST'])
@login_required
@admin_required
def admin_add_teacher():
    d = request.json or {}
    try:
        conn = get_db()
        pwd = bcrypt.hashpw((d.get('password','Teacher@123')).encode(), bcrypt.gensalt())
        q(conn,"""INSERT INTO users(username,password,full_name,email,phone,whatsapp,
                  role,approved,subjects_note) VALUES(?,?,?,?,?,?,'teacher',1,?)""",
          (d['email'], pwd, d['full_name'], d['email'],
           d.get('phone',''), d.get('whatsapp',''), d.get('subjects_note','')))
        conn.commit(); conn.close()
        return jsonify({'ok':True})
    except Exception as e:
        return jsonify({'ok':False,'msg':'Email already exists' if 'UNIQUE' in str(e) else str(e)}), 409

@app.route('/api/admin/teachers/<int:tid>/approve', methods=['POST'])
@login_required
@admin_required
def admin_approve_teacher(tid):
    conn = get_db()
    q(conn,"UPDATE users SET approved=1 WHERE id=%s AND role='teacher'",(tid,))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

@app.route('/api/admin/teachers/<int:tid>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_teacher(tid):
    conn = get_db()
    q(conn,"DELETE FROM teacher_subjects WHERE teacher_id=%s",(tid,))
    q(conn,"DELETE FROM users WHERE id=%s AND role='teacher'",(tid,))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

# ── CLASSES ───────────────────────────────────────────────────────────────────
@app.route('/api/admin/classes')
@login_required
@admin_required
def admin_classes():
    conn = get_db()
    rows = q(conn,"""SELECT c.*, u.full_name as teacher_name,
                     (SELECT COUNT(*) FROM students s WHERE s.class_id=c.id AND s.active=1) as student_count
                     FROM classes c LEFT JOIN users u ON c.class_teacher_id=u.id
                     ORDER BY c.grade_level, c.stream""").fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route('/api/admin/classes', methods=['POST'])
@login_required
@admin_required
def admin_add_class():
    d = request.json or {}
    conn = get_db()
    q(conn,"INSERT INTO classes(name,grade_level,stream,academic_year,class_teacher_id) VALUES(?,?,?,?,?)",
      (d['name'], d.get('grade_level',1), d.get('stream',''),
       d.get('academic_year','2025'), d.get('class_teacher_id') or None))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

@app.route('/api/admin/classes/<int:cid>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_class(cid):
    conn = get_db()
    q(conn,"DELETE FROM classes WHERE id=%s",(cid,))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

# ── SUBJECTS ──────────────────────────────────────────────────────────────────
@app.route('/api/admin/subjects')
@login_required
@admin_required
def admin_subjects():
    conn = get_db()
    rows = q(conn,"SELECT * FROM subjects ORDER BY name").fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route('/api/admin/subjects', methods=['POST'])
@login_required
@admin_required
def admin_add_subject():
    d = request.json or {}
    try:
        conn = get_db()
        q(conn,"INSERT INTO subjects(name,code,max_marks,pass_mark) VALUES(?,?,?,?)",
          (d['name'], d.get('code',''), d.get('max_marks',100), d.get('pass_mark',50)))
        conn.commit(); conn.close()
        return jsonify({'ok':True})
    except Exception as e:
        return jsonify({'ok':False,'msg':str(e)}), 409

@app.route('/api/admin/subjects/<int:sid>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_subject(sid):
    conn = get_db()
    q(conn,"DELETE FROM subjects WHERE id=%s",(sid,))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

# ── STUDENTS ──────────────────────────────────────────────────────────────────
@app.route('/api/admin/students')
@login_required
@admin_required
def admin_students():
    cid = request.args.get('class_id')
    conn = get_db()
    if cid:
        rows = q(conn,"""SELECT s.*,c.name as class_name FROM students s
                         LEFT JOIN classes c ON s.class_id=c.id
                         WHERE s.class_id=? AND s.active=1 ORDER BY s.full_name""",(cid,)).fetchall()
    else:
        rows = q(conn,"""SELECT s.*,c.name as class_name FROM students s
                         LEFT JOIN classes c ON s.class_id=c.id
                         WHERE s.active=1 ORDER BY s.full_name""").fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route('/api/admin/students', methods=['POST'])
@login_required
@admin_required
def admin_add_student():
    d = request.json or {}
    try:
        conn = get_db()
        q(conn,"""INSERT INTO students(admission_number,full_name,gender,date_of_birth,
                  class_id,parent_name,parent_email,parent_phone,parent_whatsapp,address)
                  VALUES(?,?,?,?,?,?,?,?,?,?)""",
          (d['admission_number'], d['full_name'], d.get('gender',''),
           d.get('date_of_birth',''), d.get('class_id'),
           d.get('parent_name',''), d.get('parent_email',''),
           d.get('parent_phone',''), d.get('parent_whatsapp',''),
           d.get('address','')))
        conn.commit(); conn.close()
        return jsonify({'ok':True})
    except Exception as e:
        return jsonify({'ok':False,'msg':'Admission number already exists' if 'UNIQUE' in str(e) else str(e)}), 409

@app.route('/api/admin/students/<int:sid>', methods=['PUT'])
@login_required
@admin_required
def admin_update_student(sid):
    d = request.json or {}
    conn = get_db()
    q(conn,"""UPDATE students SET full_name=%s,class_id=%s,gender=%s,parent_name=%s,
                    parent_email=%s,parent_phone=%s,parent_whatsapp=%s,address=%s WHERE id=%s""",
                 (d['full_name'], d.get('class_id'), d.get('gender',''),
                  d.get('parent_name',''), d.get('parent_email',''),
                  d.get('parent_phone',''), d.get('parent_whatsapp',''),
                  d.get('address',''), sid))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

@app.route('/api/admin/students/<int:sid>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_student(sid):
    conn = get_db()
    q(conn,"UPDATE students SET active=0 WHERE id=%s",(sid,))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

# ── ASSIGNMENTS ────────────────────────────────────────────────────────────────
@app.route('/api/admin/assignments')
@login_required
@admin_required
def admin_assignments():
    conn = get_db()
    rows = q(conn,"""SELECT ts.*,u.full_name as teacher_name,
                     s.name as subject_name,c.name as class_name
                     FROM teacher_subjects ts
                     JOIN users u ON ts.teacher_id=u.id
                     JOIN subjects s ON ts.subject_id=s.id
                     JOIN classes c ON ts.class_id=c.id
                     ORDER BY u.full_name""").fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route('/api/admin/assignments', methods=['POST'])
@login_required
@admin_required
def admin_assign():
    d = request.json or {}
    try:
        conn = get_db()
        q(conn,"INSERT INTO teacher_subjects(teacher_id,subject_id,class_id) VALUES(?,?,?) ON CONFLICT(teacher_id,subject_id,class_id) DO NOTHING",
          (d['teacher_id'], d['subject_id'], d['class_id']))
        conn.commit(); conn.close()
        return jsonify({'ok':True})
    except Exception as e:
        return jsonify({'ok':False,'msg':str(e)}), 409

@app.route('/api/admin/assignments/<int:aid>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_assignment(aid):
    conn = get_db()
    q(conn,"DELETE FROM teacher_subjects WHERE id=%s",(aid,))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

# ── GRADES OVERVIEW ────────────────────────────────────────────────────────────
@app.route('/api/admin/grades')
@login_required
@admin_required
def admin_grades():
    cid  = request.args.get('class_id')
    term = request.args.get('term','End of Term 1')
    conn = get_db()
    rows = q(conn,"""SELECT g.score,g.max_score,g.method,g.class_id,
                     s.id as student_id, s.full_name as student_name,
                     sub.id as subject_id, sub.name as subject_name,
                     c.name as class_name
                     FROM grades g
                     JOIN students s ON g.student_id=s.id
                     JOIN subjects sub ON g.subject_id=sub.id
                     JOIN classes c ON g.class_id=c.id
                     WHERE g.term=?""" + (" AND g.class_id=?" if cid else "") +
                     " ORDER BY c.name, s.full_name, sub.name",
              [term] + ([cid] if cid else [])).fetchall()
    from collections import OrderedDict
    classes = OrderedDict()
    for r in rows:
        cn = r['class_name']
        if cn not in classes:
            classes[cn] = {'subjects': [], 'students': OrderedDict()}
        if r['subject_name'] not in classes[cn]['subjects']:
            classes[cn]['subjects'].append(r['subject_name'])
        sn = r['student_name']
        if sn not in classes[cn]['students']:
            classes[cn]['students'][sn] = {'student_id': r['student_id']}
        classes[cn]['students'][sn][r['subject_name']] = {
            'score': r['score'], 'max': r['max_score'] or 100, 'method': r['method']
        }
    result = []
    for cn, cd in classes.items():
        students_out = []
        for sname, sdata in cd['students'].items():
            row = {'student_name': sname, 'student_id': sdata['student_id'], 'subjects': {}}
            scores = []
            for sub in cd['subjects']:
                sg = sdata.get(sub)
                row['subjects'][sub] = sg
                if sg and sg['score'] is not None:
                    scores.append((sg['score'] / sg['max']) * 100)
            row['average'] = round(sum(scores)/len(scores), 1) if scores else None
            students_out.append(row)
        result.append({'class_name': cn, 'subjects': cd['subjects'], 'students': students_out})
    conn.close()
    return jsonify(result)

# ── REPORTS ────────────────────────────────────────────────────────────────────
@app.route('/api/admin/reports/generate', methods=['POST'])
@login_required
@admin_required
def admin_generate_reports():
    d = request.json or {}
    class_id    = d.get('class_id')
    term        = d.get('term','End of Term 1')
    acad_year   = str(d.get('academic_year','2025'))
    do_email    = d.get('send_email', False)
    do_whatsapp = d.get('send_whatsapp', False)

    conn = get_db()
    sql = """SELECT s.*,c.name as class_name FROM students s
             LEFT JOIN classes c ON s.class_id=c.id WHERE s.active=1"""
    params = []
    if class_id:
        sql += " AND s.class_id=?"; params.append(class_id)
    sql += " ORDER BY c.name, s.full_name"
    students = q(conn, sql, params).fetchall()

    os.makedirs('reports', exist_ok=True)
    results = []

    for stu in students:
        # Try with academic_year filter first; fall back without it so old data still works
        grades = q(conn,"""SELECT g.*,sub.name as subject_name
                           FROM grades g JOIN subjects sub ON g.subject_id=sub.id
                           WHERE g.student_id=? AND g.term=? AND g.academic_year=?
                           ORDER BY sub.name""",
                   (stu['id'], term, acad_year)).fetchall()
        if not grades:
            grades = q(conn,"""SELECT g.*,sub.name as subject_name
                               FROM grades g JOIN subjects sub ON g.subject_id=sub.id
                               WHERE g.student_id=? AND g.term=?
                               ORDER BY sub.name""",
                       (stu['id'], term)).fetchall()

        if not grades:
            results.append({'name':stu['full_name'],'class':stu['class_name']or'—',
                            'status':'skipped','reason':'No grades entered'})
            continue

        grades_data = [dict(g) for g in grades]
        scores_pct  = [(g['score'] or 0)/(g.get('max_score') or 100)*100 for g in grades_data]
        avg         = sum(scores_pct)/len(scores_pct)
        ltr, rmk, _ = grade_letter(avg)

        pdf_bytes = build_report_pdf(dict(stu), grades_data,
                                     stu['class_name'] or '—', term, acad_year)
        pdf_name  = f"report_{stu['id']}_{term.replace(' ','_')}_{acad_year}.pdf"
        pdf_path  = f"reports/{pdf_name}"
        with open(pdf_path,'wb') as fp: fp.write(pdf_bytes)

        row = {'id':stu['id'],'name':stu['full_name'],'class':stu['class_name'] or '—',
               'avg':round(avg,1),'grade':ltr,'remark':rmk,
               'subjects':len(grades_data),'pdf':pdf_name,
               'email_status':'—','wa_status':'—',
               'has_email': bool(stu['parent_email']),
               'has_phone': bool(stu['parent_whatsapp'] or stu['parent_phone'])}

        if do_email:
            if stu['parent_email']:
                email_body = f"""<html><body style="font-family:Arial,sans-serif;background:#f8f7ff;margin:0;padding:0">
<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08)">
  <div style="background:linear-gradient(135deg,#4f46e5,#7c3aed);padding:28px 32px;text-align:center">
    <div style="font-size:36px">🏫</div>
    <h1 style="color:#fff;margin:8px 0 4px;font-size:20px">{SCHOOL_NAME}</h1>
    <p style="color:rgba(255,255,255,.8);margin:0;font-size:13px">Academic Report Card</p>
  </div>
  <div style="padding:28px 32px">
    <p style="font-size:15px;color:#374151">Dear <strong>{stu['parent_name'] or 'Parent/Guardian'}</strong>,</p>
    <p style="color:#6b7280;font-size:14px">We are pleased to share the <strong>{term}</strong> academic report for your child.</p>
    <div style="background:#f5f3ff;border-left:4px solid #4f46e5;border-radius:8px;padding:16px 20px;margin:20px 0">
      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <tr><td style="padding:5px 0;color:#6b7280;width:140px">Student</td><td style="font-weight:700;color:#111">{stu['full_name']}</td></tr>
        <tr><td style="padding:5px 0;color:#6b7280">Class</td><td style="font-weight:700;color:#111">{stu['class_name'] or '—'}</td></tr>
        <tr><td style="padding:5px 0;color:#6b7280">Term</td><td style="font-weight:700;color:#111">{term} — {acad_year}</td></tr>
        <tr><td style="padding:5px 0;color:#6b7280">Overall Average</td><td style="font-weight:700;color:#4f46e5;font-size:16px">{avg:.1f}%</td></tr>
        <tr><td style="padding:5px 0;color:#6b7280">Grade</td><td><span style="background:#4f46e5;color:#fff;padding:2px 12px;border-radius:10px;font-weight:700">{ltr} — {rmk}</span></td></tr>
      </table>
    </div>
    <p style="color:#6b7280;font-size:13px">The full PDF report card is attached to this email. Please review it carefully and sign the parent/guardian section.</p>
    <p style="color:#6b7280;font-size:13px">For any queries, please contact the school office.</p>
    <p style="color:#374151;font-size:14px;margin-top:20px">Kind regards,<br><strong>{SCHOOL_NAME}</strong></p>
  </div>
  <div style="background:#f9f9f9;padding:14px 32px;text-align:center;font-size:11px;color:#9ca3af;border-top:1px solid #f0f0f0">
    This report was generated by {SCHOOL_NAME} School Management System
  </div>
</div>
</body></html>"""
                ok, msg = send_email(
                    stu['parent_email'],
                    f"📋 {term} Report Card — {stu['full_name']} | {SCHOOL_NAME}",
                    email_body,
                    attachments=[(f"Report_{stu['full_name'].replace(' ','_')}_{term.replace(' ','_')}.pdf", pdf_bytes)]
                )
                row['email_status'] = '✅ Sent' if ok else f'❌ {msg[:80]}'
                q(conn,"""INSERT INTO report_deliveries(student_id,term,academic_year,channel,recipient,status,error_msg)
                          VALUES(?,?,?,'email',?,?,?)""",
                  (stu['id'],term,acad_year,stu['parent_email'],
                   'sent' if ok else 'failed', None if ok else msg[:200]))
            else:
                row['email_status'] = '⚠️ No email'

        if do_whatsapp:
            num = stu['parent_whatsapp'] or stu['parent_phone']
            if num:
                wa_lines = [
                    f"📋 *{term} Report Card — {SCHOOL_NAME}*",
                    "",
                    f"Dear {stu['parent_name'] or 'Parent/Guardian'},",
                    "",
                    f"Here is the academic summary for *{stu['full_name']}*:",
                    "",
                    f"  🏛️ Class: {stu['class_name'] or '—'}",
                    f"  📅 Term: {term} ({acad_year})",
                    f"  📈 Average: *{avg:.1f}%*",
                    f"  🏅 Grade: *{ltr} — {rmk}*",
                    f"  📚 Subjects: {len(grades_data)}",
                    "",
                    "The full PDF report card has been sent via email." if stu['parent_email'] else "Please visit the school to collect the printed report card.",
                    "",
                    "For enquiries contact the school office. 🏫"
                ]
                wa_body = "\n".join(wa_lines)
                ok, msg = send_whatsapp(num, wa_body)
                row['wa_status'] = '✅ Sent' if ok else f'❌ {msg[:80]}'
                q(conn,"""INSERT INTO report_deliveries(student_id,term,academic_year,channel,recipient,status,error_msg)
                          VALUES(?,?,?,'whatsapp',?,?,?)""",
                  (stu['id'],term,acad_year,num,
                   'sent' if ok else 'failed', None if ok else msg[:200]))
            else:
                row['wa_status'] = '⚠️ No number'

        conn.commit()
        results.append(row)

    conn.close()
    generated = [r for r in results if r.get('grade')]
    return jsonify({'ok':True,'results':results,'total':len(results),
                    'generated':len(generated),'skipped':len(results)-len(generated)})


@app.route('/api/admin/reports/resend', methods=['POST'])
@login_required
@admin_required
def admin_resend_report(): 
    """Resend report for a single student."""
    d = request.json or {}
    sid         = d.get('student_id')
    term        = d.get('term','End of Term 1')
    acad_year   = str(d.get('academic_year','2025'))
    do_email    = d.get('send_email', False)
    do_whatsapp = d.get('send_whatsapp', False)

    conn = get_db()
    stu = q(conn,"""SELECT s.*,c.name as class_name FROM students s
                    LEFT JOIN classes c ON s.class_id=c.id
                    WHERE s.id=?""",(sid,)).fetchone()
    if not stu:
        conn.close(); return jsonify({'ok':False,'error':'Student not found'}),404

    grades = q(conn,"""SELECT g.*,sub.name as subject_name
                       FROM grades g JOIN subjects sub ON g.subject_id=sub.id
                       WHERE g.student_id=? AND g.term=? ORDER BY sub.name""",
               (sid, term)).fetchall()
    if not grades:
        conn.close(); return jsonify({'ok':False,'error':'No grades found for this term'})

    grades_data = [dict(g) for g in grades]
    scores_pct  = [(g['score'] or 0)/(g.get('max_score') or 100)*100 for g in grades_data]
    avg         = sum(scores_pct)/len(scores_pct)
    ltr, rmk, _ = grade_letter(avg)

    pdf_bytes = build_report_pdf(dict(stu), grades_data, stu['class_name'] or '—', term, acad_year)
    pdf_path  = f"reports/report_{sid}_{term.replace(' ','_')}_{acad_year}.pdf"
    os.makedirs('reports', exist_ok=True)
    with open(pdf_path,'wb') as fp: fp.write(pdf_bytes)

    result = {'name':stu['full_name'],'email_status':'—','wa_status':'—'}

    if do_email and stu['parent_email']:
        email_body = f"<html><body><p>Dear {stu['parent_name'] or 'Parent/Guardian'},</p><p>Please find attached the {term} report card for <strong>{stu['full_name']}</strong>. Average: {avg:.1f}% | Grade: {ltr} — {rmk}</p><p>Regards, {SCHOOL_NAME}</p></body></html>"
        ok, msg = send_email(stu['parent_email'], f"📋 {term} Report – {stu['full_name']}", email_body,
                             attachments=[(f"Report_{stu['full_name']}.pdf", pdf_bytes)])
        result['email_status'] = '✅ Sent' if ok else f'❌ {msg[:80]}'
        q(conn,"""INSERT INTO report_deliveries(student_id,term,academic_year,channel,recipient,status,error_msg)
                  VALUES(?,?,?,'email',?,?,?)""",
          (sid,term,acad_year,stu['parent_email'],'sent' if ok else 'failed', None if ok else msg[:200]))
        conn.commit()

    if do_whatsapp:
        num = stu['parent_whatsapp'] or stu['parent_phone']
        if num:
            wa = f"📋 *{term} Report — {stu['full_name']}*\nAverage: {avg:.1f}% | Grade: {ltr} — {rmk}\n{SCHOOL_NAME}"
            ok, msg = send_whatsapp(num, wa)
            result['wa_status'] = '✅ Sent' if ok else f'❌ {msg[:80]}'
            q(conn,"""INSERT INTO report_deliveries(student_id,term,academic_year,channel,recipient,status,error_msg)
                      VALUES(?,?,?,'whatsapp',?,?,?)""",
              (sid,term,acad_year,num,'sent' if ok else 'failed', None if ok else msg[:200]))
            conn.commit()

    conn.close()
    return jsonify({'ok':True,'result':result})

@app.route('/api/admin/reports/download/<int:sid>')
@login_required
@admin_required
def admin_download_report(sid):
    term = request.args.get('term','End of Term 1')
    acad = request.args.get('year','2025')
    path = f"reports/report_{sid}_{term.replace(' ','_')}_{acad}.pdf"
    if os.path.exists(path):
        return send_file(path, as_attachment=True,
                         download_name=f"Report_{sid}.pdf",
                         mimetype='application/pdf')
    return jsonify({'error':'Not generated yet. Generate reports first.'}), 404

@app.route('/api/admin/reports/deliveries')
@login_required
@admin_required
def admin_delivery_log():
    conn = get_db()
    rows = q(conn,"""SELECT rd.*,s.full_name as student_name
                     FROM report_deliveries rd JOIN students s ON rd.student_id=s.id
                     ORDER BY rd.sent_at DESC LIMIT 200""").fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

# ── DASHBOARD STATS ────────────────────────────────────────────────────────────
@app.route('/api/admin/stats')
@login_required
@admin_required
def admin_stats():
    conn = get_db()
    stats = {
        'teachers':   q(conn,"SELECT COUNT(*) FROM users WHERE role='teacher' AND approved=1").fetchone()[0],
        'pending':    q(conn,"SELECT COUNT(*) FROM users WHERE role='teacher' AND approved=0").fetchone()[0],
        'students':   q(conn,"SELECT COUNT(*) FROM students WHERE active=1").fetchone()[0],
        'classes':    q(conn,"SELECT COUNT(*) FROM classes").fetchone()[0],
        'subjects':   q(conn,"SELECT COUNT(*) FROM subjects").fetchone()[0],
        'grades':     q(conn,"SELECT COUNT(*) FROM grades").fetchone()[0],
        'reports_sent': q(conn,"SELECT COUNT(*) FROM report_deliveries WHERE status='sent'").fetchone()[0],
    }
    conn.close(); return jsonify(stats)

@app.route('/api/announcements')
@login_required
def get_announcements():
    conn = get_db()
    rows = q(conn,"""SELECT a.*,u.full_name as author_name
                     FROM announcements a LEFT JOIN users u ON a.author_id=u.id
                     ORDER BY a.created_at DESC LIMIT 30""").fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route('/api/admin/announcements', methods=['POST'])
@login_required
@admin_required
def admin_add_announcement():
    d = request.json or {}
    conn = get_db()
    q(conn,"INSERT INTO announcements(title,body,author_id) VALUES(?,?,?)",
      (d['title'], d['body'], session['user_id']))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

# ══════════════════════════════════════════════════════════════════════════════
# TEACHER APIs
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/teacher/dashboard')
@login_required
def teacher_dashboard():
    tid = session['user_id']
    conn = get_db()
    data = {
        'classes':   q(conn,"SELECT COUNT(DISTINCT class_id) FROM teacher_subjects WHERE teacher_id=?",(tid,)).fetchone()[0],
        'subjects':  q(conn,"SELECT COUNT(DISTINCT subject_id) FROM teacher_subjects WHERE teacher_id=?",(tid,)).fetchone()[0],
        'students':  q(conn,"""SELECT COUNT(DISTINCT s.id) FROM students s
                               JOIN teacher_subjects ts ON ts.class_id=s.class_id
                               WHERE ts.teacher_id=? AND s.active=1""",(tid,)).fetchone()[0],
        'grades_entered': q(conn,"SELECT COUNT(*) FROM grades WHERE teacher_id=?",(tid,)).fetchone()[0],
        'att_today': q(conn,"SELECT COUNT(*) FROM attendance WHERE teacher_id=? AND date=?",
                       (tid, datetime.now().strftime('%Y-%m-%d'))).fetchone()[0],
        'recent_grades': [dict(r) for r in q(conn,"""
                           SELECT g.score, g.term, s.full_name as student_name, sub.name as subject_name
                           FROM grades g
                           JOIN students s ON g.student_id=s.id
                           JOIN subjects sub ON g.subject_id=sub.id
                           WHERE g.teacher_id=? ORDER BY g.id DESC LIMIT 5""",(tid,)).fetchall()],
        'announcements': [dict(r) for r in q(conn,"""
                           SELECT a.title, a.body, a.created_at, u.full_name as author
                           FROM announcements a LEFT JOIN users u ON a.author_id=u.id
                           ORDER BY a.created_at DESC LIMIT 5""").fetchall()],
    }
    conn.close()
    return jsonify(data)

@app.route('/api/teacher/profile')
@login_required
def teacher_profile():
    conn = get_db()
    u = q(conn,"SELECT id,full_name,username,email,phone,whatsapp,approved FROM users WHERE id=?",
          (session['user_id'],)).fetchone()
    conn.close()
    return jsonify(dict(u)) if u else (jsonify({'error':'Not found'}),404)

@app.route('/api/teacher/assignments')
@login_required
def teacher_assignments():
    tid = session['user_id']
    conn = get_db()
    rows = q(conn,"""SELECT DISTINCT c.id as class_id, c.name as class_name,
                     c.grade_level, s.id as subject_id, s.name as subject_name,
                     s.max_marks,
                     (SELECT COUNT(*) FROM students st WHERE st.class_id=c.id AND st.active=1) as student_count
                     FROM teacher_subjects ts
                     JOIN classes c ON ts.class_id=c.id
                     JOIN subjects s ON ts.subject_id=s.id
                     WHERE ts.teacher_id=? ORDER BY c.grade_level,c.name""",
              (tid,)).fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route('/api/teacher/students/<int:class_id>')
@login_required
def teacher_students(class_id):
    conn = get_db()
    rows = q(conn,"SELECT * FROM students WHERE class_id=? AND active=1 ORDER BY full_name",
             (class_id,)).fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

# ── ATTENDANCE ─────────────────────────────────────────────────────────────────
@app.route('/api/teacher/attendance', methods=['POST'])
@login_required
def teacher_save_attendance():
    d   = request.json or {}
    tid = session['user_id']
    conn = get_db()
    saved = 0
    for rec in d.get('records',[]):
        try:
            q(conn,"""INSERT INTO attendance
                      (student_id,class_id,teacher_id,date,status,note)
                      VALUES(?,?,?,?,?,?)
                      ON CONFLICT(student_id,date) DO UPDATE SET
                      class_id=EXCLUDED.class_id, teacher_id=EXCLUDED.teacher_id,
                      status=EXCLUDED.status, note=EXCLUDED.note""",
              (rec['student_id'], d['class_id'], tid,
               d.get('date', datetime.now().strftime('%Y-%m-%d')),
               rec['status'], rec.get('note','')))
            saved += 1
        except Exception: pass
    conn.commit(); conn.close()
    return jsonify({'ok':True,'saved':saved})

@app.route('/api/teacher/attendance/<int:class_id>')
@login_required
def teacher_get_attendance(class_id):
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    conn = get_db()
    rows = q(conn,"""SELECT a.*,s.full_name as student_name
                     FROM attendance a JOIN students s ON a.student_id=s.id
                     WHERE a.class_id=? AND a.date=? ORDER BY s.full_name""",
             (class_id, date)).fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route('/api/teacher/attendance/summary/<int:class_id>')
@login_required
def teacher_att_summary(class_id):
    conn = get_db()
    rows = q(conn,"""SELECT s.id,s.full_name,
                     SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) as present,
                     SUM(CASE WHEN a.status='absent'  THEN 1 ELSE 0 END) as absent,
                     SUM(CASE WHEN a.status='late'    THEN 1 ELSE 0 END) as late,
                     SUM(CASE WHEN a.status='excused' THEN 1 ELSE 0 END) as excused,
                     COUNT(a.id) as total_days
                     FROM students s
                     LEFT JOIN attendance a ON s.id=a.student_id AND a.class_id=?
                     WHERE s.class_id=? AND s.active=1
                     GROUP BY s.id ORDER BY s.full_name""",
             (class_id, class_id)).fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

# ── GRADES ─────────────────────────────────────────────────────────────────────
@app.route('/api/teacher/grades', methods=['POST'])
@login_required
def teacher_save_grades():
    d   = request.json or {}
    tid = session['user_id']
    conn = get_db()
    saved = 0
    for g in d.get('grades',[]):
        try:
            q(conn,"""INSERT INTO grades
                      (student_id,subject_id,teacher_id,class_id,score,max_score,
                       method,term,academic_year,comment)
                      VALUES(?,?,?,?,?,?,?,?,?,?)
                      ON CONFLICT(student_id,subject_id,term,academic_year) DO UPDATE SET
                      teacher_id=EXCLUDED.teacher_id, class_id=EXCLUDED.class_id,
                      score=EXCLUDED.score, max_score=EXCLUDED.max_score,
                      method=EXCLUDED.method, comment=EXCLUDED.comment,
                      entered_at=CURRENT_TIMESTAMP""",
              (g['student_id'], g['subject_id'], tid, g['class_id'],
               g['score'], g.get('max_score',100),
               g.get('method','manual'), g.get('term','End of Term 1'),
               g.get('academic_year','2025'), g.get('comment','')))
            saved += 1
        except Exception: pass
    conn.commit(); conn.close()
    return jsonify({'ok':True,'saved':saved})

@app.route('/api/teacher/grades/<int:class_id>/<int:subject_id>')
@login_required
def teacher_get_grades(class_id, subject_id):
    term = request.args.get('term','End of Term 1')
    tid  = session['user_id']
    conn = get_db()
    rows = q(conn,"""SELECT g.*,s.full_name as student_name
                     FROM grades g JOIN students s ON g.student_id=s.id
                     WHERE g.class_id=? AND g.subject_id=? AND g.teacher_id=? AND g.term=?
                     ORDER BY s.full_name""",
             (class_id, subject_id, tid, term)).fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route('/api/teacher/gradebook/<int:class_id>')
@login_required
def teacher_gradebook(class_id):
    term = request.args.get('term','End of Term 1')
    conn = get_db()
    rows = q(conn,"""SELECT g.score,g.max_score,g.method,
                     s.full_name as student_name,sub.name as subject_name
                     FROM grades g
                     JOIN students s ON g.student_id=s.id
                     JOIN subjects sub ON g.subject_id=sub.id
                     WHERE g.class_id=? AND g.term=? ORDER BY s.full_name,sub.name""",
             (class_id, term)).fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

# ── OCR SCAN ───────────────────────────────────────────────────────────────────
@app.route('/api/teacher/scan', methods=['POST'])
@login_required
def teacher_scan():
    d = request.json or {}
    img_b64 = d.get('image','')
    class_id = d.get('class_id')
    if not img_b64:
        return jsonify({'ok':False,'error':'No image provided'}), 400
    if not (HAS_PIL and HAS_OCR):
        return jsonify({'ok':False,'error':'OCR not available. Install Pillow + pytesseract.'}), 501
    try:
        raw = img_b64.split(',')[-1]
        img = Image.open(io.BytesIO(base64.b64decode(raw))).convert('RGB')
        text = pytesseract.image_to_string(img)
    except Exception as e:
        return jsonify({'ok':False,'error':str(e)}), 500

    candidates = []
    for pat in [r'([A-Za-z][A-Za-z\s]{2,30})[\s:\-]+(\d{1,3})',
                r'(\d{4,8})\s+(\d{1,3})', r'(\w+)\s+(\d{1,3})\b']:
        for ident, score in re.findall(pat, text):
            v = int(score)
            if 0 <= v <= 100:
                candidates.append({'id': ident.strip().lower(), 'score': v})

    conn = get_db()
    matches = []; seen = set()
    for c in candidates[:30]:
        s = q(conn,"""SELECT id,full_name FROM students
                      WHERE class_id=? AND active=1 AND
                      (LOWER(full_name) LIKE ? OR admission_number=?) LIMIT 1""",
              (class_id, f'%{c["id"]}%', c['id'])).fetchone()
        if s and s['id'] not in seen:
            seen.add(s['id'])
            matches.append({'student_id':s['id'],'student_name':s['full_name'],'score':c['score']})
    conn.close()
    return jsonify({'ok':True,'matches':matches,'raw_text':text[:500]})

# ══════════════════════════════════════════════════════════════════════════════
# SHARED
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/classes')
@login_required
def all_classes():
    conn = get_db()
    rows = q(conn,"SELECT * FROM classes ORDER BY grade_level,stream").fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route('/api/subjects')
@login_required
def all_subjects():
    conn = get_db()
    rows = q(conn,"SELECT * FROM subjects ORDER BY name").fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])


# ══════════════════════════════════════════════════════════════════════════════
# STUDENT PROFILE API
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/admin/student/<int:sid>/profile')
@login_required
def student_profile_full(sid):
    conn = get_db()
    stu = q(conn,"""SELECT s.*,c.name as class_name FROM students s
                    LEFT JOIN classes c ON s.class_id=c.id WHERE s.id=?""",(sid,)).fetchone()
    if not stu: conn.close(); return jsonify({'error':'Not found'}),404
    grades = q(conn,"""SELECT g.*,sub.name as subject_name, sub.code,
                        u.full_name as teacher_name
                        FROM grades g
                        JOIN subjects sub ON g.subject_id=sub.id
                        LEFT JOIN users u ON g.teacher_id=u.id
                        WHERE g.student_id=? ORDER BY g.academic_year DESC, g.term, sub.name""",(sid,)).fetchall()
    att = q(conn,"""SELECT date,status,note FROM attendance
                    WHERE student_id=? ORDER BY date DESC LIMIT 90""",(sid,)).fetchall()
    att_summary = q(conn,"""SELECT status, COUNT(*) as cnt FROM attendance
                             WHERE student_id=? GROUP BY status""",(sid,)).fetchall()
    fees = q(conn,"SELECT * FROM fees WHERE student_id=? ORDER BY academic_year DESC,term",(sid,)).fetchall()
    hw = q(conn,"""SELECT hs.*, h.title, h.due_date, sub.name as subject_name
                   FROM homework_submissions hs
                   JOIN homework h ON hs.homework_id=h.id
                   JOIN subjects sub ON h.subject_id=sub.id
                   WHERE hs.student_id=? ORDER BY h.due_date DESC LIMIT 20""",(sid,)).fetchall()
    conn.close()
    return jsonify({
        'student': dict(stu),
        'grades':  [dict(g) for g in grades],
        'attendance': [dict(a) for a in att],
        'att_summary': {r['status']:r['cnt'] for r in att_summary},
        'fees': [dict(f) for f in fees],
        'homework': [dict(h) for h in hw],
    })

# ══════════════════════════════════════════════════════════════════════════════
# FEES APIs
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/admin/fees')
@login_required
@admin_required
def admin_fees():
    term  = request.args.get('term','')
    year  = request.args.get('year','2025')
    cid   = request.args.get('class_id','')
    conn  = get_db()
    sql   = """SELECT f.*,s.full_name as student_name,s.admission_number,
                      c.name as class_name
               FROM fees f
               JOIN students s ON f.student_id=s.id
               LEFT JOIN classes c ON s.class_id=c.id
               WHERE f.academic_year=?"""
    params = [year]
    if term:  sql += " AND f.term=?";     params.append(term)
    if cid:   sql += " AND s.class_id=?"; params.append(cid)
    sql += " ORDER BY c.name, s.full_name"
    rows = q(conn, sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/fees/summary')
@login_required
@admin_required
def admin_fees_summary():
    year = request.args.get('year','2025')
    conn = get_db()
    total_due  = q(conn,"SELECT COALESCE(SUM(amount_due),0) FROM fees WHERE academic_year=?",(year,)).fetchone()[0]
    total_paid = q(conn,"SELECT COALESCE(SUM(amount_paid),0) FROM fees WHERE academic_year=?",(year,)).fetchone()[0]
    paid_count = q(conn,"SELECT COUNT(*) FROM fees WHERE academic_year=? AND status='paid'",(year,)).fetchone()[0]
    unpaid_count=q(conn,"SELECT COUNT(*) FROM fees WHERE academic_year=? AND status!='paid'",(year,)).fetchone()[0]
    conn.close()
    return jsonify({'total_due':total_due,'total_paid':total_paid,
                    'paid_count':paid_count,'unpaid_count':unpaid_count,
                    'balance':total_due-total_paid})

@app.route('/api/admin/fees/bulk', methods=['POST'])
@login_required
@admin_required
def admin_fees_bulk():
    """Create fee records for all students in a class/all classes."""
    d = request.json or {}
    class_id  = d.get('class_id')
    term      = d.get('term','Term 1')
    year      = d.get('year','2025')
    amount    = d.get('amount',0)
    due_date  = d.get('due_date','')
    conn = get_db()
    sql = "SELECT id FROM students WHERE active=1"
    params = []
    if class_id: sql += " AND class_id=?"; params.append(class_id)
    students = q(conn, sql, params).fetchall()
    created = 0
    for s in students:
        try:
            q(conn,"""INSERT INTO fees(student_id,academic_year,term,amount_due,due_date,status)
                      VALUES(?,?,?,?,?,'unpaid') ON CONFLICT DO NOTHING""",(s['id'],year,term,amount,due_date))
            created += 1
        except: pass
    conn.commit(); conn.close()
    return jsonify({'ok':True,'created':created})

@app.route('/api/admin/fees/<int:fid>/pay', methods=['POST'])
@login_required
@admin_required
def admin_fees_pay(fid):
    d = request.json or {}
    amount = d.get('amount',0)
    conn = get_db()
    fee = q(conn,"SELECT * FROM fees WHERE id=?",(fid,)).fetchone()
    if not fee: conn.close(); return jsonify({'error':'Not found'}),404
    new_paid = (fee['amount_paid'] or 0) + amount
    status = 'paid' if new_paid >= fee['amount_due'] else 'partial'
    q(conn,"""UPDATE fees SET amount_paid=?,status=?,paid_date=?,note=?
              WHERE id=?""",(new_paid,status,datetime.now().strftime('%Y-%m-%d'),
              d.get('note',''),fid))
    conn.commit(); conn.close()
    return jsonify({'ok':True,'status':status,'paid':new_paid})

@app.route('/api/admin/fees/<int:fid>', methods=['DELETE'])
@login_required
@admin_required
def admin_fees_delete(fid):
    conn = get_db()
    q(conn,"DELETE FROM fees WHERE id=?",(fid,))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

# ══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE / ANALYTICS APIs
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/admin/analytics/class-performance')
@login_required
@admin_required
def analytics_class_performance():
    term = request.args.get('term','End of Term 1')
    year = request.args.get('year','2025')
    conn = get_db()
    rows = q(conn,"""SELECT c.name as class_name,
                     AVG((g.score*1.0/g.max_score)*100) as avg_pct,
                     COUNT(DISTINCT g.student_id) as student_count,
                     COUNT(g.id) as grade_count
                     FROM grades g JOIN classes c ON g.class_id=c.id
                     WHERE g.term=?
                     GROUP BY g.class_id ORDER BY avg_pct DESC""",(term,)).fetchall()
    subj = q(conn,"""SELECT sub.name as subject_name,
                     AVG((g.score*1.0/g.max_score)*100) as avg_pct,
                     COUNT(g.id) as count
                     FROM grades g JOIN subjects sub ON g.subject_id=sub.id
                     WHERE g.term=?
                     GROUP BY g.subject_id ORDER BY avg_pct DESC""",(term,)).fetchall()
    conn.close()
    return jsonify({'by_class':[dict(r) for r in rows],'by_subject':[dict(r) for r in subj]})

@app.route('/api/admin/analytics/attendance')
@login_required
@admin_required
def analytics_attendance():
    conn = get_db()
    # Attendance by class this month
    by_class = q(conn,"""SELECT c.name as class_name,
                  SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END)*100.0/COUNT(a.id) as rate,
                  COUNT(a.id) as total
                  FROM attendance a JOIN students s ON a.student_id=s.id
                  LEFT JOIN classes c ON s.class_id=c.id
                  GROUP BY s.class_id ORDER BY rate DESC""").fetchall()
    # Students with low attendance (below 80%)
    low_att = q(conn,"""SELECT s.full_name,s.id,c.name as class_name,
                 SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END)*100.0/COUNT(a.id) as rate,
                 COUNT(a.id) as total_days,
                 SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) as absences,
                 s.parent_name, s.parent_phone, s.parent_whatsapp
                 FROM attendance a JOIN students s ON a.student_id=s.id
                 LEFT JOIN classes c ON s.class_id=c.id
                 GROUP BY a.student_id
                 HAVING rate < 80 AND total_days >= 5
                 ORDER BY rate ASC LIMIT 30""").fetchall()
    conn.close()
    return jsonify({'by_class':[dict(r) for r in by_class],'low_attendance':[dict(r) for r in low_att]})

# ══════════════════════════════════════════════════════════════════════════════
# HOMEWORK APIs (Teacher)
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/teacher/homework', methods=['GET'])
@login_required
def teacher_get_homework():
    tid = session['user_id']
    conn = get_db()
    rows = q(conn,"""SELECT h.*,c.name as class_name, sub.name as subject_name,
                     COUNT(hs.id) as submission_count,
                     SUM(CASE WHEN hs.status='submitted' THEN 1 ELSE 0 END) as submitted_count
                     FROM homework h
                     LEFT JOIN classes c ON h.class_id=c.id
                     LEFT JOIN subjects sub ON h.subject_id=sub.id
                     LEFT JOIN homework_submissions hs ON hs.homework_id=h.id
                     WHERE h.teacher_id=?
                     GROUP BY h.id ORDER BY h.created_at DESC""",(tid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/teacher/homework', methods=['POST'])
@login_required
def teacher_add_homework():
    d = request.json or {}
    tid = session['user_id']
    conn = get_db()
    cur = q(conn,"""INSERT INTO homework(teacher_id,class_id,subject_id,title,description,due_date,max_marks)
                    VALUES(?,?,?,?,?,?,?) RETURNING id""",
            (tid,d['class_id'],d['subject_id'],d['title'],d.get('description',''),
             d.get('due_date',''),d.get('max_marks',0)))
    hw_id = cur.fetchone()['id']
    # Auto-create submission slots for all students in the class
    students = q(conn,"SELECT id FROM students WHERE class_id=? AND active=1",(d['class_id'],)).fetchall()
    for s in students:
        q(conn,"INSERT INTO homework_submissions(homework_id,student_id,status) VALUES(?,?,'pending') ON CONFLICT(homework_id,student_id) DO NOTHING",
          (hw_id, s['id']))
    conn.commit(); conn.close()
    return jsonify({'ok':True,'id':hw_id})

@app.route('/api/teacher/homework/<int:hw_id>', methods=['DELETE'])
@login_required
def teacher_delete_homework(hw_id):
    tid = session['user_id']
    conn = get_db()
    q(conn,"DELETE FROM homework_submissions WHERE homework_id=?",(hw_id,))
    q(conn,"DELETE FROM homework WHERE id=? AND teacher_id=?",(hw_id,tid))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

@app.route('/api/teacher/homework/<int:hw_id>/submissions')
@login_required
def teacher_hw_submissions(hw_id):
    conn = get_db()
    rows = q(conn,"""SELECT hs.*,s.full_name as student_name,s.admission_number
                     FROM homework_submissions hs
                     JOIN students s ON hs.student_id=s.id
                     WHERE hs.homework_id=? ORDER BY s.full_name""",(hw_id,)).fetchall()
    hw   = q(conn,"SELECT * FROM homework WHERE id=?",(hw_id,)).fetchone()
    conn.close()
    return jsonify({'homework':dict(hw) if hw else {},'submissions':[dict(r) for r in rows]})

@app.route('/api/teacher/homework/submission/<int:sub_id>', methods=['PUT'])
@login_required
def teacher_update_submission(sub_id):
    d = request.json or {}
    conn = get_db()
    q(conn,"""UPDATE homework_submissions SET status=?,marks=?,note=? WHERE id=?""",
      (d.get('status','submitted'),d.get('marks'),d.get('note',''),sub_id))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

# ══════════════════════════════════════════════════════════════════════════════
# ATTENDANCE ALERT API
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/teacher/attendance/alerts/<int:class_id>')
@login_required
def teacher_att_alerts(class_id):
    conn = get_db()
    rows = q(conn,"""SELECT s.id,s.full_name,s.parent_name,s.parent_phone,s.parent_whatsapp,
                     COUNT(a.id) as total_days,
                     SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) as absences,
                     SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END)*100.0/COUNT(a.id) as rate
                     FROM students s
                     LEFT JOIN attendance a ON a.student_id=s.id
                     WHERE s.class_id=? AND s.active=1
                     GROUP BY s.id HAVING total_days>=5 AND rate < 80
                     ORDER BY rate ASC""",(class_id,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/teacher/attendance/notify', methods=['POST'])
@login_required
def teacher_att_notify():
    d = request.json or {}
    sid  = d.get('student_id')
    conn = get_db()
    stu  = q(conn,"SELECT * FROM students WHERE id=?",(sid,)).fetchone()
    if not stu: conn.close(); return jsonify({'ok':False,'error':'Student not found'})
    att  = q(conn,"""SELECT COUNT(*) as total,
                     SUM(CASE WHEN status='absent' THEN 1 ELSE 0 END) as absences
                     FROM attendance WHERE student_id=?""",(sid,)).fetchone()
    rate = 0
    if att['total']>0:
        rate = round((att['total']-att['absences'])/att['total']*100,1)
    num  = stu['parent_whatsapp'] or stu['parent_phone']
    if not num: conn.close(); return jsonify({'ok':False,'error':'No phone number on record'})
    lines = [
        f"⚠️ *Attendance Alert — {SCHOOL_NAME}*",
        "",
        f"Dear {stu['parent_name'] or 'Parent/Guardian'},",
        "",
        f"This is to inform you that *{stu['full_name']}* currently has an attendance rate of *{rate}%*",
        f"({att['absences']} absences out of {att['total']} school days).",
        "",
        "Regular attendance is important for your child's academic progress.",
        "Please ensure your child attends school regularly.",
        "",
        "For any concerns, contact the school office. 🏫"
    ]
    msg = "\n".join(lines)
    ok, err = send_whatsapp(num, msg)
    conn.close()
    return jsonify({'ok':ok,'error':err if not ok else None,'rate':rate})

# ══════════════════════════════════════════════════════════════════════════════
# SCHOOL SETTINGS API
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/admin/settings', methods=['GET'])
@login_required
@admin_required
def admin_get_settings():
    conn = get_db()
    rows = q(conn,"SELECT key,value FROM school_settings").fetchall()
    conn.close()
    return jsonify({r['key']:r['value'] for r in rows})

@app.route('/api/admin/settings', methods=['POST'])
@login_required
@admin_required
def admin_save_settings():
    d = request.json or {}
    conn = get_db()
    for key,val in d.items():
        q(conn,"INSERT INTO school_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",(key,str(val)))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

# ══════════════════════════════════════════════════════════════════════════════
# STUDENT PROMOTION API
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/admin/settings/test-email', methods=['POST'])
@login_required
@admin_required
def test_email_settings():
    d = request.json or {}
    email = d.get('email') or EMAIL_USER
    if not email:
        return jsonify({'ok':False,'error':'No email configured'})
    ok, msg = send_email(email, f'Test Email — {SCHOOL_NAME}',
        f'<p>This is a test email from {SCHOOL_NAME} School Management System.</p>')
    return jsonify({'ok':ok,'error':msg if not ok else None})

@app.route('/api/admin/settings/test-whatsapp', methods=['POST'])
@login_required
@admin_required
def test_whatsapp_settings():
    if not TWILIO_SID:
        return jsonify({'ok':False,'error':'Twilio not configured'})
    ok, msg = send_whatsapp(TWILIO_FROM.replace('whatsapp:',''),
        f'Test message from {SCHOOL_NAME} School Management System.')
    return jsonify({'ok':ok,'error':msg if not ok else None})

@app.route('/api/admin/students/promote', methods=['POST'])
@login_required
@admin_required
def admin_promote_students():
    d = request.json or {}
    from_class = d.get('from_class_id')
    to_class   = d.get('to_class_id')
    student_ids= d.get('student_ids',[])
    if not from_class or not to_class:
        return jsonify({'ok':False,'error':'from_class_id and to_class_id required'})
    conn = get_db()
    count = 0
    for sid in student_ids:
        q(conn,"UPDATE students SET class_id=? WHERE id=? AND class_id=?",(to_class,sid,from_class))
        count += 1
    conn.commit(); conn.close()
    return jsonify({'ok':True,'promoted':count})

# ══════════════════════════════════════════════════════════════════════════════
# HTML TEMPLATES
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# TIMETABLE APIs
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/admin/timetable')
@login_required
def get_timetable():
    class_id = request.args.get('class_id')
    year     = request.args.get('academic_year', '2025')
    conn = get_db()
    sql = """SELECT t.*, c.name as class_name, s.name as subject_name,
                    s.code as subject_code, u.full_name as teacher_name
             FROM timetable t
             JOIN classes c ON t.class_id=c.id
             JOIN subjects s ON t.subject_id=s.id
             LEFT JOIN users u ON t.teacher_id=u.id
             WHERE t.academic_year=?"""
    params = [year]
    if class_id:
        sql += " AND t.class_id=?"; params.append(class_id)
    sql += " ORDER BY t.day_of_week, t.period"
    rows = q(conn, sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/timetable', methods=['POST'])
@login_required
@admin_required
def save_timetable_slot():
    d = request.json or {}
    conn = get_db()
    try:
        q(conn, """INSERT INTO timetable
                   (class_id,subject_id,teacher_id,day_of_week,period,start_time,end_time,room,academic_year)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(class_id,day_of_week,period,academic_year) DO UPDATE SET
                   subject_id=EXCLUDED.subject_id, teacher_id=EXCLUDED.teacher_id,
                   start_time=EXCLUDED.start_time, end_time=EXCLUDED.end_time, room=EXCLUDED.room""",
          (d['class_id'], d['subject_id'], d.get('teacher_id') or None,
           d['day_of_week'], d['period'], d['start_time'], d['end_time'],
           d.get('room',''), d.get('academic_year','2025')))
        conn.commit(); conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        conn.close(); return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/admin/timetable/<int:tid>', methods=['DELETE'])
@login_required
@admin_required
def delete_timetable_slot(tid):
    conn = get_db()
    q(conn, "DELETE FROM timetable WHERE id=?", (tid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/admin/timetable/clear', methods=['POST'])
@login_required
@admin_required
def clear_timetable():
    d = request.json or {}
    conn = get_db()
    q(conn, "DELETE FROM timetable WHERE class_id=? AND academic_year=?",
      (d['class_id'], d.get('academic_year','2025')))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/teacher/timetable')
@login_required
def teacher_timetable():
    tid = session['user_id']
    year = request.args.get('academic_year','2025')
    conn = get_db()
    rows = q(conn, """SELECT t.*, c.name as class_name, s.name as subject_name,
                             s.code as subject_code
                      FROM timetable t
                      JOIN classes c ON t.class_id=c.id
                      JOIN subjects s ON t.subject_id=s.id
                      WHERE t.teacher_id=? AND t.academic_year=?
                      ORDER BY t.day_of_week, t.period""",
             (tid, year)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── Global CSS and JS injected into every page ──────────────────────────────
GLOBAL = """
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --pri:#4f46e5;--pri-d:#3730a3;--pri-l:#ede9fe;--pri-xl:#f5f3ff;
  --grn:#059669;--grn-l:#d1fae5;--red:#dc2626;--red-l:#fee2e2;
  --amb:#d97706;--amb-l:#fef3c7;--sky:#0284c7;--sky-l:#e0f2fe;
  --pur:#7c3aed;--pur-l:#ede9fe;--pnk:#db2777;--pnk-l:#fce7f3;
  --g50:#f9fafb;--g100:#f3f4f6;--g200:#e5e7eb;--g300:#d1d5db;
  --g400:#9ca3af;--g500:#6b7280;--g700:#374151;--g900:#111827;
  --sh:0 1px 3px rgba(0,0,0,.08),0 1px 2px rgba(0,0,0,.04);
  --sh-md:0 4px 12px rgba(0,0,0,.1);--sh-lg:0 20px 50px rgba(0,0,0,.15);
  --r6:6px;--r8:8px;--r12:12px;--r16:16px;--r20:20px;--r50:50px;
}
body{font-family:'Inter',system-ui,sans-serif;background:var(--g50);color:var(--g900);min-height:100vh;font-size:14px;line-height:1.5}
a{text-decoration:none;color:inherit}
button{cursor:pointer;font-family:inherit}
/* Inputs */
input,select,textarea{font-family:inherit;font-size:14px;border:1.5px solid var(--g200);
  border-radius:var(--r8);padding:10px 14px;width:100%;outline:none;
  transition:border .18s,box-shadow .18s;background:#fff;color:var(--g900)}
input:focus,select:focus,textarea:focus{border-color:var(--pri);
  box-shadow:0 0 0 3px rgba(79,70,229,.12)}
input::placeholder,textarea::placeholder{color:var(--g400)}
/* Buttons */
.btn{display:inline-flex;align-items:center;gap:7px;padding:9px 18px;border-radius:var(--r8);
  border:none;font-size:13px;font-weight:600;transition:all .18s;white-space:nowrap;cursor:pointer;line-height:1}
.btn:active{transform:scale(.97)}
.btn-pri{background:var(--pri);color:#fff;box-shadow:0 2px 8px rgba(79,70,229,.3)}
.btn-pri:hover{background:var(--pri-d);box-shadow:0 4px 12px rgba(79,70,229,.4);transform:translateY(-1px)}
.btn-grn{background:var(--grn);color:#fff;box-shadow:0 2px 8px rgba(5,150,105,.25)}
.btn-grn:hover{background:#047857;transform:translateY(-1px)}
.btn-red{background:var(--red);color:#fff}
.btn-red:hover{background:#b91c1c;transform:translateY(-1px)}
.btn-amb{background:var(--amb);color:#fff}
.btn-amb:hover{background:#b45309}
.btn-ghost{background:#fff;color:var(--g700);border:1.5px solid var(--g200)}
.btn-ghost:hover{background:var(--g50);border-color:var(--g300)}
.btn-pri-out{background:transparent;color:var(--pri);border:1.5px solid var(--pri)}
.btn-pri-out:hover{background:var(--pri);color:#fff}
.btn-sm{padding:6px 13px;font-size:12px}
.btn-lg{padding:13px 26px;font-size:15px}
.btn-icon{padding:8px;border-radius:var(--r8)}
/* Cards */
.card{background:#fff;border-radius:var(--r16);box-shadow:var(--sh);border:1px solid var(--g200)}
.card-hdr{padding:18px 22px;border-bottom:1px solid var(--g100);display:flex;
  align-items:center;justify-content:space-between;gap:12px}
.card-hdr h3{font-size:15px;font-weight:700;color:var(--g900)}
.card-bod{padding:22px}
/* Badges */
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;
  font-size:11px;font-weight:700;letter-spacing:.2px}
.badge-pri{background:var(--pri-l);color:var(--pri)}
.badge-grn{background:var(--grn-l);color:var(--grn)}
.badge-red{background:var(--red-l);color:var(--red)}
.badge-amb{background:var(--amb-l);color:var(--amb)}
.badge-sky{background:var(--sky-l);color:var(--sky)}
.badge-pur{background:var(--pur-l);color:var(--pur)}
.badge-pnk{background:var(--pnk-l);color:var(--pnk)}
/* Tables */
.tbl-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse}
thead tr{background:var(--g50)}
th{padding:10px 14px;text-align:left;font-size:11px;font-weight:700;color:var(--g500);
  text-transform:uppercase;letter-spacing:.5px;border-bottom:1.5px solid var(--g200);white-space:nowrap}
td{padding:13px 14px;border-bottom:1px solid var(--g100);color:var(--g700);vertical-align:middle}
tr:last-child td{border-bottom:none}
tbody tr:hover td{background:var(--pri-xl)}
/* Layout */
.layout{display:flex;min-height:100vh}
.sidebar{width:248px;min-width:248px;background:linear-gradient(180deg,#1e1b4b 0%,#312e81 100%);
  display:flex;flex-direction:column;position:sticky;top:0;height:100vh;overflow-y:auto;z-index:100}
.sb-logo{padding:24px 20px 18px}
.sb-logo h1{color:#fff;font-size:17px;font-weight:800;line-height:1.2}
.sb-logo p{color:rgba(255,255,255,.45);font-size:11px;margin-top:3px}
.sb-divider{height:1px;background:rgba(255,255,255,.1);margin:8px 14px}
.sb-label{font-size:10px;font-weight:700;color:rgba(255,255,255,.3);
  text-transform:uppercase;letter-spacing:1px;padding:10px 18px 4px}
.nav-btn{display:flex;align-items:center;gap:11px;padding:11px 16px;border-radius:10px;
  margin:2px 10px;border:none;background:transparent;color:rgba(255,255,255,.6);
  font-size:13px;font-weight:500;transition:all .18s;text-align:left;width:calc(100% - 20px);cursor:pointer}
.nav-btn:hover{background:rgba(255,255,255,.1);color:#fff}
.nav-btn.active{background:rgba(79,70,229,.55);color:#fff;font-weight:700}
.nav-btn .ni{width:18px;font-size:15px;text-align:center;flex-shrink:0}
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
.topbar{background:#fff;border-bottom:1px solid var(--g200);padding:13px 28px;
  display:flex;align-items:center;justify-content:space-between;gap:12px;
  position:sticky;top:0;z-index:50;min-height:60px}
.main-body{flex:1;overflow-y:auto;padding:28px}
/* Sections */
.sec{display:none}.sec.active{display:block}
/* Page header */
.pg-hdr{display:flex;justify-content:space-between;align-items:flex-start;
  flex-wrap:wrap;gap:14px;margin-bottom:24px}
.pg-hdr-left h2{font-size:22px;font-weight:800;color:var(--g900)}
.pg-hdr-left p{font-size:13px;color:var(--g500);margin-top:3px}
/* Stat cards */
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:28px}
.stat-card{background:#fff;border-radius:var(--r16);padding:20px;border:1px solid var(--g200);
  display:flex;align-items:center;gap:16px;transition:box-shadow .2s,transform .2s}
.stat-card:hover{box-shadow:var(--sh-md);transform:translateY(-2px)}
.stat-ic{width:48px;height:48px;border-radius:14px;display:flex;align-items:center;
  justify-content:center;font-size:22px;flex-shrink:0}
.stat-inf .val{font-size:28px;font-weight:900;color:var(--g900);line-height:1}
.stat-inf .lbl{font-size:11px;font-weight:600;color:var(--g500);text-transform:uppercase;
  letter-spacing:.4px;margin-top:4px}
/* Modal */
.modal-bg{position:fixed;inset:0;background:rgba(15,10,40,.55);backdrop-filter:blur(4px);
  z-index:500;display:flex;align-items:center;justify-content:center;padding:20px;opacity:0;
  pointer-events:none;transition:opacity .2s}
.modal-bg.open{opacity:1;pointer-events:all}
.modal{background:#fff;border-radius:var(--r20);box-shadow:var(--sh-lg);
  width:min(620px,100%);max-height:92vh;overflow-y:auto;
  transform:scale(.92) translateY(20px);transition:transform .22s cubic-bezier(.34,1.56,.64,1)}
.modal-bg.open .modal{transform:scale(1) translateY(0)}
.modal-hdr{padding:20px 26px;border-bottom:1px solid var(--g100);
  display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;background:#fff;z-index:1}
.modal-hdr h3{font-size:17px;font-weight:800}
.modal-hdr .close{background:var(--g100);border:none;border-radius:var(--r8);
  padding:6px 11px;font-size:16px;color:var(--g500)}
.modal-hdr .close:hover{background:var(--g200)}
.modal-bod{padding:24px 26px}
.modal-ftr{padding:16px 26px;border-top:1px solid var(--g100);
  display:flex;gap:10px;justify-content:flex-end}
/* Forms */
.fg{margin-bottom:16px}
.flbl{font-size:11px;font-weight:700;color:var(--g500);text-transform:uppercase;
  letter-spacing:.5px;display:block;margin-bottom:6px}
.frow{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px}
.frow2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
/* Tabs */
.tabs{display:flex;gap:3px;background:var(--g100);padding:4px;border-radius:10px;
  width:fit-content;margin-bottom:20px}
.tab-btn{padding:8px 16px;border-radius:var(--r8);font-size:13px;font-weight:600;
  cursor:pointer;border:none;background:transparent;color:var(--g500);transition:all .18s}
.tab-btn.active{background:#fff;color:var(--pri);box-shadow:var(--sh)}
/* Toast */
.toast-area{position:fixed;bottom:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px}
.toast{padding:13px 18px;border-radius:var(--r12);font-size:13px;font-weight:600;
  color:#fff;box-shadow:0 8px 24px rgba(0,0,0,.2);display:flex;align-items:center;gap:10px;
  animation:toastIn .3s cubic-bezier(.34,1.56,.64,1);max-width:360px;cursor:pointer}
.toast.success{background:linear-gradient(135deg,#059669,#047857)}
.toast.error{background:linear-gradient(135deg,#dc2626,#b91c1c)}
.toast.warn{background:linear-gradient(135deg,#d97706,#b45309)}
.toast.info{background:linear-gradient(135deg,#0284c7,#0369a1)}
@keyframes toastIn{from{opacity:0;transform:translateY(20px) scale(.9)}to{opacity:1;transform:translateY(0) scale(1)}}
/* Empty state */
.empty{text-align:center;padding:52px 20px;color:var(--g400)}
.empty .ei{font-size:44px;margin-bottom:10px}
.empty h4{font-size:15px;font-weight:700;color:var(--g500);margin-bottom:5px}
/* Misc */
.sep{height:1px;background:var(--g100);margin:20px 0}
.avatar{border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-weight:800;color:#fff;flex-shrink:0;font-size:14px}
.chip{display:inline-block;padding:2px 9px;border-radius:12px;font-size:12px;font-weight:800}
.chip-A{background:#d1fae5;color:#065f46}.chip-B{background:#dbeafe;color:#1e40af}
.chip-C{background:#fef3c7;color:#78350f}.chip-D{background:#ffedd5;color:#9a3412}
.chip-F{background:#fee2e2;color:#7f1d1d}
.filter-bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:18px}
.filter-bar select,.filter-bar input{width:auto;min-width:150px}
.voice-btn{border-radius:50%;width:50px;height:50px;font-size:20px;border:none;
  display:flex;align-items:center;justify-content:center;transition:all .2s;flex-shrink:0}
.voice-btn.idle{background:var(--pri-l);color:var(--pri)}
.voice-btn.idle:hover{background:var(--pri);color:#fff;transform:scale(1.08)}
.voice-btn.rec{background:var(--red);color:#fff;animation:vpulse 1.2s ease infinite}
@keyframes vpulse{0%,100%{box-shadow:0 0 0 0 rgba(220,38,38,.4)}60%{box-shadow:0 0 0 14px rgba(220,38,38,0)}}
/* Grade input */
.gi{width:72px;padding:7px 9px;text-align:center;font-size:13px;font-weight:700;
  border:1.5px solid var(--g200);border-radius:var(--r8)}
.gi:focus{border-color:var(--pri);outline:none}
/* Attendance buttons */
.att-grp button{padding:6px 14px;border:1.5px solid var(--g200);border-radius:20px;
  font-size:12px;font-weight:700;background:#fff;cursor:pointer;transition:all .18s}
.att-grp .att-P{border-color:var(--grn);color:var(--grn)}
.att-grp .att-P.on{background:var(--grn);color:#fff}
.att-grp .att-A{border-color:var(--red);color:var(--red)}
.att-grp .att-A.on{background:var(--red);color:#fff}
.att-grp .att-L{border-color:var(--amb);color:var(--amb)}
.att-grp .att-L.on{background:var(--amb);color:#fff}
.att-grp .att-E{border-color:var(--sky);color:var(--sky)}
.att-grp .att-E.on{background:var(--sky);color:#fff}
/* Canvas toolbar */
.canv-tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;
  padding:10px 14px;background:var(--g50);border-bottom:1px solid var(--g200)}
/* Report badge */
.rep-row{display:flex;align-items:center;gap:12px;padding:12px 16px;
  border-radius:var(--r12);background:var(--g50);border:1px solid var(--g200);margin-bottom:8px}
/* Responsive */
@media(max-width:900px){
  .sidebar{position:fixed;left:-260px;top:0;bottom:0;transition:left .25s;z-index:200}
  .sidebar.open{left:0}
  .sb-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:199}
  .sb-overlay.open{display:block}
  .main-body{padding:16px}
  .frow{grid-template-columns:1fr}
  .frow2{grid-template-columns:1fr}
  .stat-grid{grid-template-columns:1fr 1fr}
}
@media(max-width:520px){
  .stat-grid{grid-template-columns:1fr}
  .tabs{width:100%;overflow-x:auto}
  .filter-bar select,.filter-bar input{min-width:120px}
}
</style>
<div class="toast-area" id="toasts"></div>
<script>
const $ = id => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);

const API = {
  async get(url) {
    try {
      const r = await fetch(url,{credentials:'include'});
      if(r.status===401){location.href='/';return null;}
      if(!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } catch(e){ console.error('API.get',url,e); return null; }
  },
  async post(url,body={}) {
    try {
      const r = await fetch(url,{method:'POST',credentials:'include',
        headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(r.status===401){location.href='/';return null;}
      if(!r.ok){
        let msg='Server error '+r.status;
        try{ const d=await r.json(); msg=d.error||d.message||msg; }catch(e){}
        throw new Error(msg);
      }
      return await r.json();
    } catch(e){ console.error('API.post',url,e); return {ok:false,error:e.message}; }
  },
  async put(url,body={}) {
    try {
      const r = await fetch(url,{method:'PUT',credentials:'include',
        headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } catch(e){ console.error('API.put',url,e); return {ok:false,error:e.message}; }
  },
  async del(url) {
    try {
      const r = await fetch(url,{method:'DELETE',credentials:'include'});
      if(!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } catch(e){ console.error('API.del',url,e); return {ok:false,error:e.message}; }
  }
};

// ── DARK MODE ─────────────────────────────────────────────────────────────────
function applyTheme(theme){
  if(theme==='dark'){
    document.documentElement.style.setProperty('--g50','#111827');
    document.documentElement.style.setProperty('--g100','#1f2937');
    document.documentElement.style.setProperty('--g200','#374151');
    document.documentElement.style.setProperty('--g300','#4b5563');
    document.documentElement.style.setProperty('--g500','#9ca3af');
    document.documentElement.style.setProperty('--g700','#d1d5db');
    document.documentElement.style.setProperty('--g900','#f9fafb');
    document.body.style.background='#0f172a';
  } else {
    document.documentElement.style.setProperty('--g50','#f9fafb');
    document.documentElement.style.setProperty('--g100','#f3f4f6');
    document.documentElement.style.setProperty('--g200','#e5e7eb');
    document.documentElement.style.setProperty('--g300','#d1d5db');
    document.documentElement.style.setProperty('--g500','#6b7280');
    document.documentElement.style.setProperty('--g700','#374151');
    document.documentElement.style.setProperty('--g900','#111827');
    document.body.style.background='';
  }
}
function toggleTheme(){
  const cur = localStorage.getItem('theme')||'light';
  const next = cur==='light'?'dark':'light';
  localStorage.setItem('theme',next);
  applyTheme(next);
  const btn=$('themeBtn'); if(btn) btn.textContent=next==='dark'?'☀️':'🌙';
}
// Apply on load
(function(){ applyTheme(localStorage.getItem('theme')||'light'); })();

// ── OFFLINE INDICATOR ─────────────────────────────────────────────────────────
(function(){
  function updateOnline(){
    const bar = $('offlineBar');
    if(!bar) return;
    bar.style.display = navigator.onLine ? 'none' : 'flex';
  }
  window.addEventListener('online', updateOnline);
  window.addEventListener('offline', updateOnline);
  document.addEventListener('DOMContentLoaded', updateOnline);
})();

function toast(msg, type='success', dur=3800) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icons = {success:'✅',error:'❌',warn:'⚠️',info:'ℹ️'};
  el.innerHTML = `<span style="font-size:17px">${icons[type]||'✅'}</span><span>${msg}</span>`;
  el.onclick = () => el.remove();
  $('toasts').appendChild(el);
  setTimeout(()=>el.remove(), dur);
}

function openModal(id){$(id).classList.add('open')}
function closeModal(id){$(id).classList.remove('open')}

function gradeChip(score, max=100){
  const p = max ? (score/max)*100 : 0;
  const l = p>=80?'A':p>=65?'B':p>=50?'C':p>=40?'D':'F';
  return `<span class="chip chip-${l}">${l}</span>`;
}

function pct(score,max){return max?(score/max*100).toFixed(1)+'%':'—';}

function fmtDate(d){
  if(!d) return '—';
  return new Date(d).toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric'});
}

function confirm_del(msg){ return window.confirm(msg||'Are you sure?'); }

const TERMS = ['Mid Term 1','End of Term 1','Mid Term 2','End of Term 2','Mid Term 3','End of Term 3'];
</script>
"""

# ─────────────────────────────────────────────────────────────────────────────
# LOGIN PAGE
# ─────────────────────────────────────────────────────────────────────────────
LOGIN_HTML = """<!DOCTYPE html><html lang="en"><head>
<title>Login – School Management System</title>
{{ GLOBAL }}
<style>
body{background:linear-gradient(135deg,#1e1b4b 0%,#312e81 60%,#4f46e5 100%);
  min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.auth-wrap{width:min(500px,100%)}
.auth-card{background:#fff;border-radius:24px;box-shadow:0 30px 80px rgba(0,0,0,.35);overflow:hidden}
.auth-hdr{background:linear-gradient(135deg,#4f46e5,#7c3aed);padding:36px 40px 30px;text-align:center}
.auth-hdr .ico{font-size:52px;margin-bottom:12px}
.auth-hdr h1{color:#fff;font-size:24px;font-weight:900;margin-bottom:4px}
.auth-hdr p{color:rgba(255,255,255,.7);font-size:13px}
.auth-body{padding:32px 40px 36px}
.auth-tabs{display:flex;border:1.5px solid var(--g200);border-radius:var(--r12);
  overflow:hidden;margin-bottom:28px}
.auth-tab{flex:1;padding:11px;text-align:center;font-size:13px;font-weight:700;
  cursor:pointer;border:none;background:transparent;color:var(--g500);transition:all .2s}
.auth-tab.active{background:var(--pri);color:#fff}
.fg{margin-bottom:16px}
.flbl{font-size:11px;font-weight:700;color:var(--g500);text-transform:uppercase;
  letter-spacing:.5px;display:block;margin-bottom:6px}
.hint{font-size:11px;color:var(--g400);margin-top:5px}
.divider{display:flex;align-items:center;gap:12px;margin:16px 0;color:var(--g400);font-size:12px}
.divider::before,.divider::after{content:'';flex:1;height:1px;background:var(--g200)}
</style>
</head><body>
<div class="auth-wrap">
  <div style="text-align:center;margin-bottom:20px">
    <div style="font-size:13px;color:rgba(255,255,255,.6);font-weight:500">🇲🇼 Made for Malawi Schools</div>
  </div>
  <div class="auth-card">
    <div class="auth-hdr">
      <div class="ico">🏫</div>
      <h1>School Management System</h1>
      <p>Excellence · Integrity · Service</p>
    </div>
    <div class="auth-body">
      <div class="auth-tabs">
        <button class="auth-tab active" id="tab-login" onclick="switchAuthTab('login')">🔑 Sign In</button>
        <button class="auth-tab" id="tab-reg" onclick="switchAuthTab('reg')">✍️ Teacher Register</button>
      </div>

      <!-- LOGIN -->
      <div id="form-login">
        <div class="fg">
          <label class="flbl">Email Address</label>
          <input id="li-email" type="email" placeholder="admin@school.mw" autocomplete="username">
        </div>
        <div class="fg">
          <label class="flbl">Password</label>
          <input id="li-pwd" type="password" placeholder="••••••••" autocomplete="current-password">
          <div class="hint">Admin default: admin@school.mw / Admin@2025</div>
        </div>
        <button class="btn btn-pri btn-lg" style="width:100%;justify-content:center;margin-top:6px"
          onclick="doLogin()">Sign In →</button>
      </div>

      <!-- REGISTER -->
      <div id="form-reg" style="display:none">
        <div class="frow2">
          <div class="fg"><label class="flbl">Full Name *</label>
            <input id="rg-name" placeholder="Your full name"></div>
          <div class="fg"><label class="flbl">Email *</label>
            <input id="rg-email" type="email" placeholder="teacher@email.com"></div>
        </div>
        <div class="frow2">
          <div class="fg"><label class="flbl">Password *</label>
            <input id="rg-pwd" type="password" placeholder="Min 6 characters"></div>
          <div class="fg"><label class="flbl">Phone</label>
            <input id="rg-phone" placeholder="+265 999 000 000"></div>
        </div>
        <div class="fg"><label class="flbl">WhatsApp Number</label>
          <input id="rg-wa" placeholder="+265 999 000 000"></div>
        <div class="fg"><label class="flbl">Subjects you can teach</label>
          <textarea id="rg-subj" rows="2" placeholder="e.g. Mathematics, English, Science"></textarea></div>
        <button class="btn btn-pri btn-lg" style="width:100%;justify-content:center"
          onclick="doRegister()">Submit Registration →</button>
        <p class="hint" style="margin-top:10px;text-align:center">
          Your account will be reviewed and approved by the admin before you can access the system.</p>
      </div>
    </div>
  </div>
</div>
""" + GLOBAL + """
<script>
function switchAuthTab(t){
  $('form-login').style.display = t==='login'?'block':'none';
  $('form-reg').style.display   = t==='reg'?'block':'none';
  $('tab-login').classList.toggle('active', t==='login');
  $('tab-reg').classList.toggle('active', t==='reg');
}
async function doLogin(){
  const r = await API.post('/api/login',{username:$('li-email').value, password:$('li-pwd').value});
  if(!r) return;
  if(r.ok){ location.href = r.role==='admin'?'/admin':'/teacher'; }
  else toast(r.msg||'Login failed','error');
}
async function doRegister(){
  const r = await API.post('/api/register',{
    full_name:$('rg-name').value, email:$('rg-email').value, password:$('rg-pwd').value,
    phone:$('rg-phone').value, whatsapp:$('rg-wa').value, subjects_note:$('rg-subj').value});
  if(!r) return;
  if(r.ok){ toast(r.msg); setTimeout(()=>switchAuthTab('login'),1800); }
  else toast(r.msg||'Error','error');
}
document.addEventListener('keydown',e=>{ if(e.key==='Enter') doLogin(); });
</script></body></html>"""

LOGIN_HTML = LOGIN_HTML.replace('{{ GLOBAL }}', GLOBAL)

# ─────────────────────────────────────────────────────────────────────────────
# PENDING PAGE
# ─────────────────────────────────────────────────────────────────────────────
PENDING_HTML = """<!DOCTYPE html><html><head><title>Awaiting Approval</title>
{{ GLOBAL }}
<style>body{background:var(--pri-xl);display:flex;align-items:center;justify-content:center;min-height:100vh}</style>
</head><body>
<div class="card" style="max-width:440px;margin:20px;text-align:center;padding:48px 36px">
  <div style="font-size:60px;margin-bottom:16px">⏳</div>
  <h2 style="font-size:22px;font-weight:800;margin-bottom:10px;color:var(--g900)">Awaiting Approval</h2>
  <p style="color:var(--g500);margin-bottom:8px">Hello <strong style="color:var(--pri)">{{ name }}</strong>,</p>
  <p style="color:var(--g500);margin-bottom:28px;line-height:1.7">
    Your teacher account has been submitted and is pending review by the school administrator.
    You will receive access once your account is approved.</p>
  <a href="/api/logout" class="btn btn-ghost" style="justify-content:center">← Sign Out</a>
</div>
""" + GLOBAL + "</body></html>"
PENDING_HTML = PENDING_HTML.replace('{{ GLOBAL }}', GLOBAL)

# ─────────────────────────────────────────────────────────────────────────────
# ADMIN PAGE (full SPA)
# ─────────────────────────────────────────────────────────────────────────────
ADMIN_HTML = """<!DOCTYPE html><html lang="en"><head>
<title>Admin Portal – {{ school }}</title>
{{ GLOBAL }}
</head><body>
<div class="sb-overlay" id="sbOverlay" onclick="closeSb()"></div>
<div class="layout">

<!-- ══ SIDEBAR ══════════════════════════════════════════════════════════════ -->
<div class="sidebar" id="sidebar">
  <div class="sb-logo">
    <div style="font-size:28px;margin-bottom:8px">🏫</div>
    <h1>{{ school }}</h1>
    <p>Admin Portal</p>
  </div>
  <div class="sb-label">Main Menu</div>
  <button class="nav-btn active" data-sec="dashboard" onclick="sec(this)">
    <span class="ni">📊</span>Dashboard</button>
  <button class="nav-btn" data-sec="teachers" onclick="sec(this)">
    <span class="ni">👩‍🏫</span>Teachers</button>
  <button class="nav-btn" data-sec="students" onclick="sec(this)">
    <span class="ni">👨‍🎓</span>Students</button>
  <div class="sb-divider"></div>
  <div class="sb-label">Academics</div>
  <button class="nav-btn" data-sec="classes" onclick="sec(this)">
    <span class="ni">🏛️</span>Classes</button>
  <button class="nav-btn" data-sec="subjects" onclick="sec(this)">
    <span class="ni">📚</span>Subjects</button>
  <button class="nav-btn" data-sec="assignments" onclick="sec(this)">
    <span class="ni">🔗</span>Assignments</button>
  <button class="nav-btn" data-sec="grades" onclick="sec(this)">
    <span class="ni">📈</span>Grades View</button>
  <div class="sb-divider"></div>
  <div class="sb-label">Reports</div>
  <button class="nav-btn" data-sec="reports" onclick="sec(this)">
    <span class="ni">📋</span>Generate Reports</button>
  <button class="nav-btn" data-sec="deliveries" onclick="sec(this)">
    <span class="ni">📨</span>Deliveries Log</button>
  <div class="sb-divider"></div>
  <div class="sb-label">Analytics &amp; Finance</div>
  <button class="nav-btn" data-sec="timetable" onclick="sec(this)">
    <span class="ni">🗓️</span>Timetable</button>
  <button class="nav-btn" data-sec="analytics" onclick="sec(this)">
    <span class="ni">📊</span>Analytics</button>
  <button class="nav-btn" data-sec="fees" onclick="sec(this)">
    <span class="ni">💰</span>Fee Management</button>
  <div class="sb-divider"></div>
  <div class="sb-label">Admin</div>
  <button class="nav-btn" data-sec="promote" onclick="sec(this)">
    <span class="ni">🎓</span>Promote Students</button>
  <button class="nav-btn" data-sec="settings" onclick="sec(this)">
    <span class="ni">⚙️</span>Settings</button>
  <div class="sb-divider"></div>
  <a href="/api/logout" class="nav-btn" style="margin-top:auto">
    <span class="ni">🚪</span>Sign Out</a>
</div>

<!-- ══ MAIN ═════════════════════════════════════════════════════════════════ -->
<div class="main">
<div id="offlineBar" style="display:none;background:#dc2626;color:#fff;padding:8px 20px;font-size:13px;font-weight:600;align-items:center;gap:8px;justify-content:center">
  📡 You are offline — changes may not be saved
</div>
<div class="topbar">
  <div style="display:flex;align-items:center;gap:12px">
    <button onclick="toggleSb()" style="background:none;border:none;font-size:22px;cursor:pointer;color:var(--g500)">☰</button>
    <div>
      <div style="font-size:15px;font-weight:800;color:var(--g900)" id="pageTitle">Dashboard</div>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:10px">
    <div class="badge badge-pri" id="dateTag"></div>
    <button id="themeBtn" onclick="toggleTheme()" style="background:none;border:none;font-size:20px;cursor:pointer" title="Toggle dark mode">🌙</button>
    <div class="avatar" style="width:36px;height:36px;background:var(--pri);font-size:14px">A</div>
    <span style="font-size:13px;font-weight:600;display:none" class="show-lg">{{ name }}</span>
  </div>
</div>

<div class="main-body">

<!-- ─── DASHBOARD ────────────────────────────────────────────────────────── -->
<div class="sec active" id="sec-dashboard">
  <div class="pg-hdr">
    <div class="pg-hdr-left">
      <h2>📊 Dashboard</h2>
      <p>Welcome back, <strong>{{ name }}</strong>. Here's your school overview.</p>
    </div>
  </div>
  <div class="stat-grid" id="statsRow"></div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px">
    <div class="card">
      <div class="card-hdr"><h3>⏳ Pending Teacher Approvals</h3>
        <button class="btn btn-sm btn-pri-out" onclick="sec(document.querySelector('[data-sec=teachers]'))">View All</button></div>
      <div class="card-bod" id="pendingList"></div>
    </div>
    <div class="card">
      <div class="card-hdr"><h3>📨 Recent Report Deliveries</h3>
        <button class="btn btn-sm btn-pri-out" onclick="sec(document.querySelector('[data-sec=deliveries]'))">View All</button></div>
      <div class="card-bod" id="recentDeliveries" style="padding:0"></div>
    </div>
  </div>
</div>

<!-- ─── TEACHERS ─────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-teachers">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>👩‍🏫 Teachers</h2><p>Manage teacher accounts and approvals</p></div>
    <button class="btn btn-pri" onclick="openModal('m-addTeacher')">➕ Add Teacher</button>
  </div>
  <div class="card">
    <div class="tbl-wrap">
      <table><thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>WhatsApp</th>
        <th>Subjects Note</th><th>Status</th><th>Joined</th><th>Actions</th></tr></thead>
        <tbody id="teacherTbody"></tbody></table>
    </div>
  </div>
</div>

<!-- ─── STUDENTS ─────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-students">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>👨‍🎓 Students</h2><p>Manage student records and parent contacts</p></div>
    <button class="btn btn-pri" onclick="openModal('m-addStudent')">➕ Add Student</button>
  </div>
  <div class="filter-bar">
    <select id="flt-class" onchange="loadStudents()" style="min-width:200px">
      <option value="">All Classes</option></select>
    <input id="flt-stu-search" placeholder="🔍 Search students…" oninput="renderStudents()" style="max-width:260px">
  </div>
  <div class="card">
    <div class="tbl-wrap">
      <table><thead><tr><th>Adm #</th><th>Name</th><th>Gender</th><th>Class</th>
        <th>Parent</th><th>Parent Email</th><th>Parent Phone</th><th>Actions</th></tr></thead>
        <tbody id="studentTbody"></tbody></table>
    </div>
  </div>
</div>

<!-- ─── CLASSES ──────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-classes">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>🏛️ Classes</h2><p>Manage all classes and assign class teachers</p></div>
    <button class="btn btn-pri" onclick="openModal('m-addClass')">➕ Add Class</button>
  </div>
  <div class="card">
    <div class="tbl-wrap">
      <table><thead><tr><th>Class Name</th><th>Grade</th><th>Stream</th><th>Year</th>
        <th>Class Teacher</th><th>Students</th><th>Actions</th></tr></thead>
        <tbody id="classTbody"></tbody></table>
    </div>
  </div>
</div>

<!-- ─── SUBJECTS ─────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-subjects">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>📚 Subjects</h2><p>Subjects offered in the curriculum</p></div>
    <button class="btn btn-pri" onclick="openModal('m-addSubject')">➕ Add Subject</button>
  </div>
  <div class="card">
    <div class="tbl-wrap">
      <table><thead><tr><th>Subject Name</th><th>Code</th><th>Max Marks</th><th>Pass Mark</th><th>Actions</th></tr></thead>
        <tbody id="subjectTbody"></tbody></table>
    </div>
  </div>
</div>

<!-- ─── ASSIGNMENTS ────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-assignments">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>🔗 Assignments</h2><p>Allocate teachers to subjects per class</p></div>
    <button class="btn btn-pri" onclick="openModal('m-assign')">➕ Assign</button>
  </div>
  <div class="card">
    <div class="tbl-wrap">
      <table><thead><tr><th>Teacher</th><th>Subject</th><th>Class</th><th>Actions</th></tr></thead>
        <tbody id="assignTbody"></tbody></table>
    </div>
  </div>
</div>

<!-- ─── GRADES VIEW ───────────────────────────────────────────────────────── -->
<div class="sec" id="sec-grades">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>📈 Grades Overview</h2><p>View grades per class — rows = students, columns = subjects</p></div>
    <button class="btn btn-ghost" onclick="loadGradesView()">🔄 Refresh</button>
  </div>
  <div class="filter-bar">
    <select id="gv-class" onchange="loadGradesView()" style="min-width:220px">
      <option value="">All Classes</option></select>
    <select id="gv-term" onchange="loadGradesView()" style="min-width:200px">
      <option>Mid Term 1</option><option selected>End of Term 1</option>
      <option>Mid Term 2</option><option>End of Term 2</option>
      <option>Mid Term 3</option><option>End of Term 3</option>
    </select>
    <input id="gv-search" type="search" placeholder="🔍 Search student…" oninput="filterGradesTable()" style="min-width:200px">
  </div>
  <div id="gradeViewContainer"></div>
</div>

<!-- ─── REPORTS ───────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-reports">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>📋 Report Cards</h2><p>Generate PDF reports and send to parents via Email or WhatsApp</p></div>
  </div>
  <div class="card" style="margin-bottom:20px">
    <div class="card-hdr"><h3>⚙️ Configuration</h3></div>
    <div class="card-bod">
      <div class="frow">
        <div class="fg"><label class="flbl">Class</label>
          <select id="rp-class"><option value="">All Classes</option></select></div>
        <div class="fg"><label class="flbl">Term</label>
          <select id="rp-term">
            <option>Mid Term 1</option><option selected>End of Term 1</option>
            <option>Mid Term 2</option><option>End of Term 2</option>
            <option>Mid Term 3</option><option>End of Term 3</option>
          </select></div>
        <div class="fg"><label class="flbl">Academic Year</label>
          <input id="rp-year" value="2025" type="number" style="max-width:120px"></div>
      </div>
      <div style="background:var(--g50);border-radius:var(--r12);padding:16px 20px;margin:16px 0">
        <div style="font-size:13px;font-weight:700;color:var(--g700);margin-bottom:12px">📤 Delivery Options</div>
        <div style="display:flex;gap:28px;flex-wrap:wrap">
          <label style="display:flex;align-items:center;gap:9px;font-size:14px;font-weight:600;cursor:pointer">
            <input type="checkbox" id="rp-email" style="width:17px;height:17px;accent-color:var(--pri)">
            <span>📧 Email PDF to parent</span>
          </label>
          <label style="display:flex;align-items:center;gap:9px;font-size:14px;font-weight:600;cursor:pointer">
            <input type="checkbox" id="rp-wa" style="width:17px;height:17px;accent-color:var(--grn)">
            <span>💬 WhatsApp notification</span>
          </label>
        </div>
        <div style="margin-top:10px;font-size:12px;color:var(--g500)">
          ⚠️ Requires EMAIL_USER / TWILIO env vars to be set. Reports are also saved as PDFs for manual download.
        </div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <button class="btn btn-pri btn-lg" id="genBtn" onclick="generateReports()">🚀 Generate Reports</button>
        <button class="btn btn-ghost" onclick="sec(document.querySelector('[data-sec=deliveries]'))">📜 Delivery Log</button>
      </div>
    </div>
  </div>
  <!-- Progress bar -->
  <div id="rp-progress" style="display:none;margin-bottom:20px">
    <div class="card">
      <div class="card-bod">
        <div style="display:flex;justify-content:space-between;font-size:13px;font-weight:600;margin-bottom:8px">
          <span id="rp-prog-label">Generating reports…</span>
          <span id="rp-prog-pct">0%</span>
        </div>
        <div style="background:var(--g100);border-radius:999px;height:10px;overflow:hidden">
          <div id="rp-prog-bar" style="background:linear-gradient(90deg,var(--pri),var(--vio));height:100%;width:0%;transition:width .3s;border-radius:999px"></div>
        </div>
        <div id="rp-prog-current" style="font-size:12px;color:var(--g500);margin-top:6px"></div>
      </div>
    </div>
  </div>
  <div id="rp-results"></div>
</div>

<!-- ─── DELIVERIES LOG ────────────────────────────────────────────────────── -->
<div class="sec" id="sec-deliveries">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>📨 Deliveries Log</h2><p>History of all report deliveries to parents</p></div>
    <button class="btn btn-ghost" onclick="loadDeliveries()">🔄 Refresh</button>
  </div>
  <div class="card">
    <div class="tbl-wrap">
      <table><thead><tr><th>Student</th><th>Term</th><th>Year</th>
        <th>Channel</th><th>Recipient</th><th>Status</th><th>Date</th></tr></thead>
        <tbody id="delivTbody"></tbody></table>
    </div>
  </div>
</div>


<!-- ─── TIMETABLE ─────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-timetable">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>🗓️ Class Timetable</h2><p>Build and manage weekly schedules for each class</p></div>
    <div style="display:flex;gap:8px">
      <button class="btn btn-ghost" onclick="printTimetable()">🖨️ Print</button>
      <button class="btn btn-red" onclick="clearTimetable()">🗑 Clear Class</button>
    </div>
  </div>
  <div class="filter-bar">
    <select id="tt-class" onchange="loadTimetable()" style="min-width:220px">
      <option value="">Select Class…</option>
    </select>
    <select id="tt-year" onchange="loadTimetable()" style="min-width:120px">
      <option value="2025">2025</option>
      <option value="2026">2026</option>
    </select>
    <button class="btn btn-pri" onclick="openModal('m-addSlot')">➕ Add Slot</button>
  </div>
  <div id="ttGrid"></div>
</div>

<!-- ─── ANALYTICS ──────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-analytics">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>📊 Analytics</h2><p>Class performance and attendance insights</p></div>
    <button class="btn btn-ghost" onclick="loadAnalytics()">🔄 Refresh</button>
  </div>
  <div class="filter-bar">
    <select id="an-term" onchange="loadAnalytics()" style="min-width:200px">
      <option>Mid Term 1</option><option selected>End of Term 1</option>
      <option>Mid Term 2</option><option>End of Term 2</option>
      <option>Mid Term 3</option><option>End of Term 3</option>
    </select>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px">
    <div class="card">
      <div class="card-hdr"><h3>📈 Class Performance (Avg %)</h3></div>
      <div class="card-bod" id="perfChart" style="min-height:260px"></div>
    </div>
    <div class="card">
      <div class="card-hdr"><h3>📋 Attendance by Class (%)</h3></div>
      <div class="card-bod" id="attChart" style="min-height:260px"></div>
    </div>
  </div>
  <div class="card">
    <div class="card-hdr"><h3>🏆 Class Leaderboard</h3></div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>#</th><th>Class</th><th>Students</th><th>Avg Score</th><th>Grade</th><th>Attendance</th><th>Top Student</th></tr></thead>
      <tbody id="leaderTbody"></tbody>
    </table></div>
  </div>
</div>

<!-- ─── FEES ───────────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-fees">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>💰 Fee Management</h2><p>Track school fees, payments and defaulters</p></div>
    <button class="btn btn-pri" onclick="openModal('m-bulkFees')">➕ Set Fees for Class</button>
  </div>
  <div class="stat-grid" id="feeSummaryRow"></div>
  <div class="filter-bar" style="margin-top:16px">
    <select id="fee-class" onchange="loadFees()" style="min-width:200px"><option value="">All Classes</option></select>
    <select id="fee-term" onchange="loadFees()" style="min-width:200px">
      <option>Mid Term 1</option><option selected>End of Term 1</option>
      <option>Mid Term 2</option><option>End of Term 2</option>
      <option>Mid Term 3</option><option>End of Term 3</option>
    </select>
    <select id="fee-status" onchange="loadFees()" style="min-width:160px">
      <option value="">All Statuses</option>
      <option value="unpaid">Unpaid</option>
      <option value="partial">Partial</option>
      <option value="paid">Paid</option>
    </select>
  </div>
  <div class="card">
    <div class="tbl-wrap"><table>
      <thead><tr><th>Student</th><th>Class</th><th>Term</th><th>Amount Due</th><th>Amount Paid</th><th>Balance</th><th>Status</th><th>Actions</th></tr></thead>
      <tbody id="feeTbody"></tbody>
    </table></div>
  </div>
</div>

<!-- ─── PROMOTE ────────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-promote">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>🎓 Promote Students</h2><p>Move students to next class at end of year</p></div>
  </div>
  <div class="card" style="max-width:700px;margin-bottom:20px">
    <div class="card-hdr"><h3>⚙️ Promotion Settings</h3></div>
    <div class="card-bod">
      <div class="frow">
        <div class="fg"><label class="flbl">From Class</label>
          <select id="promo-from"><option value="">Select class…</option></select></div>
        <div class="fg"><label class="flbl">To Class</label>
          <select id="promo-to"><option value="">Select class…</option></select></div>
        <div class="fg"><label class="flbl">Min Average % to promote</label>
          <input id="promo-min" type="number" value="40" min="0" max="100"></div>
      </div>
      <div style="display:flex;gap:10px;margin-top:8px">
        <button class="btn btn-ghost" onclick="previewPromotion()">👁 Preview</button>
        <button class="btn btn-pri" onclick="runPromotion()">🎓 Promote Students</button>
      </div>
    </div>
  </div>
  <div id="promoPreview"></div>
</div>

<!-- ─── SETTINGS ───────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-settings">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>⚙️ School Settings</h2><p>Configure school details and integrations</p></div>
    <button class="btn btn-pri" onclick="saveSettings()">💾 Save Settings</button>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;max-width:960px">
    <div class="card">
      <div class="card-hdr"><h3>🏫 School Info</h3></div>
      <div class="card-bod">
        <div class="fg"><label class="flbl">School Name</label><input id="s-name" placeholder="School name"></div>
        <div class="fg"><label class="flbl">Motto</label><input id="s-motto" placeholder="Excellence · Integrity · Service"></div>
        <div class="fg"><label class="flbl">Address</label><input id="s-address" placeholder="School address"></div>
        <div class="fg"><label class="flbl">Phone</label><input id="s-phone" placeholder="+265 …"></div>
        <div class="fg"><label class="flbl">Current Academic Year</label><input id="s-year" placeholder="2025"></div>
      </div>
    </div>
    <div class="card">
      <div class="card-hdr"><h3>📧 Email Config (SMTP)</h3></div>
      <div class="card-bod">
        <div class="fg"><label class="flbl">Email Address</label><input id="s-email-user" type="email" placeholder="school@gmail.com"></div>
        <div class="fg"><label class="flbl">App Password</label><input id="s-email-pass" type="password" placeholder="Gmail app password"></div>
        <div class="fg"><label class="flbl">SMTP Host</label><input id="s-smtp-host" placeholder="smtp.gmail.com"></div>
        <div class="fg"><label class="flbl">SMTP Port</label><input id="s-smtp-port" placeholder="587"></div>
        <button class="btn btn-ghost" onclick="testEmail()" style="margin-top:4px">📧 Send Test Email</button>
      </div>
    </div>
    <div class="card">
      <div class="card-hdr"><h3>💬 WhatsApp Config (Twilio)</h3></div>
      <div class="card-bod">
        <div class="fg"><label class="flbl">Account SID</label><input id="s-twilio-sid" placeholder="ACxxxxxxxx"></div>
        <div class="fg"><label class="flbl">Auth Token</label><input id="s-twilio-token" type="password" placeholder="Auth token"></div>
        <div class="fg"><label class="flbl">From Number</label><input id="s-twilio-from" placeholder="whatsapp:+14155238886"></div>
        <button class="btn btn-ghost" onclick="testWhatsApp()" style="margin-top:4px">💬 Send Test Message</button>
      </div>
    </div>
    <div class="card">
      <div class="card-hdr"><h3>🎨 Appearance</h3></div>
      <div class="card-bod">
        <div class="fg"><label class="flbl">Theme</label>
          <select id="s-theme">
            <option value="light">☀️ Light</option>
            <option value="dark">🌙 Dark</option>
          </select>
        </div>
        <div style="margin-top:12px;padding:12px;background:var(--g50);border-radius:var(--r8);font-size:13px;color:var(--g500)">
          Theme applies immediately and is saved in your browser.
        </div>
      </div>
    </div>
  </div>
</div>

</div><!-- main-body -->
</div><!-- main -->
</div><!-- layout -->

<!-- ══ MODALS ════════════════════════════════════════════════════════════════ -->

<!-- Add Timetable Slot Modal -->
<div class="modal-bg" id="m-addSlot" onclick="if(event.target===this)closeModal(this.id)">
<div class="modal"><div class="modal-hdr"><h3>➕ Add Timetable Slot</h3>
  <button class="close" onclick="closeModal('m-addSlot')">✕</button></div>
<div class="modal-bod">
  <div class="frow2">
    <div class="fg"><label class="flbl">Day</label>
      <select id="sl-day">
        <option value="1">Monday</option><option value="2">Tuesday</option>
        <option value="3">Wednesday</option><option value="4">Thursday</option>
        <option value="5">Friday</option>
      </select></div>
    <div class="fg"><label class="flbl">Period</label>
      <select id="sl-period">
        <option value="1">Period 1</option><option value="2">Period 2</option>
        <option value="3">Period 3</option><option value="4">Period 4</option>
        <option value="5">Period 5</option><option value="6">Period 6</option>
        <option value="7">Period 7</option><option value="8">Period 8</option>
      </select></div>
  </div>
  <div class="frow2">
    <div class="fg"><label class="flbl">Start Time</label>
      <input id="sl-start" type="time" value="07:30"></div>
    <div class="fg"><label class="flbl">End Time</label>
      <input id="sl-end" type="time" value="08:10"></div>
  </div>
  <div class="frow2">
    <div class="fg"><label class="flbl">Subject</label>
      <select id="sl-subject"></select></div>
    <div class="fg"><label class="flbl">Teacher</label>
      <select id="sl-teacher"><option value="">Not assigned</option></select></div>
  </div>
  <div class="fg"><label class="flbl">Room / Location (optional)</label>
    <input id="sl-room" placeholder="e.g. Room 3A, Library, Science Lab"></div>
</div>
<div class="modal-ftr">
  <button class="btn btn-ghost" onclick="closeModal('m-addSlot')">Cancel</button>
  <button class="btn btn-pri" onclick="saveSlot()">💾 Save Slot</button>
</div></div></div>

<!-- Bulk Fees Modal -->
<div class="modal-bg" id="m-bulkFees" onclick="if(event.target===this)closeModal(this.id)">
<div class="modal"><div class="modal-hdr"><h3>💰 Set Fees for Class</h3>
  <button class="close" onclick="closeModal('m-bulkFees')">✕</button></div>
<div class="modal-bod">
  <div class="frow2">
    <div class="fg"><label class="flbl">Class</label>
      <select id="bf-class"><option value="">All Classes</option></select></div>
    <div class="fg"><label class="flbl">Term</label>
      <select id="bf-term">
        <option>Mid Term 1</option><option selected>End of Term 1</option>
        <option>Mid Term 2</option><option>End of Term 2</option>
        <option>Mid Term 3</option><option>End of Term 3</option>
      </select></div>
  </div>
  <div class="frow2">
    <div class="fg"><label class="flbl">Amount Due (MK)</label><input id="bf-amount" type="number" placeholder="e.g. 15000"></div>
    <div class="fg"><label class="flbl">Due Date</label><input id="bf-due" type="date"></div>
  </div>
  <div class="fg"><label class="flbl">Note (optional)</label><input id="bf-note" placeholder="e.g. Term 1 school fees 2025"></div>
</div>
<div class="modal-ftr">
  <button class="btn btn-ghost" onclick="closeModal('m-bulkFees')">Cancel</button>
  <button class="btn btn-pri" onclick="setBulkFees()">💰 Set Fees</button>
</div></div></div>

<!-- Student Profile Modal -->
<div class="modal-bg" id="m-studentProfile" onclick="if(event.target===this)closeModal(this.id)">
<div class="modal" style="max-width:820px;width:95vw"><div class="modal-hdr"><h3 id="profileModalTitle">👤 Student Profile</h3>
  <button class="close" onclick="closeModal('m-studentProfile')">✕</button></div>
<div class="modal-bod" id="profileModalBody" style="max-height:75vh;overflow-y:auto"></div>
</div></div>

<!-- Add Teacher -->
<div class="modal-bg" id="m-addTeacher" onclick="if(event.target===this)closeModal(this.id)">
<div class="modal"><div class="modal-hdr"><h3>➕ Add Teacher</h3>
  <button class="close" onclick="closeModal('m-addTeacher')">✕</button></div>
<div class="modal-bod">
  <div class="frow2">
    <div class="fg"><label class="flbl">Full Name *</label><input id="t-name" placeholder="Full name"></div>
    <div class="fg"><label class="flbl">Email *</label><input id="t-email" type="email" placeholder="teacher@email.com"></div>
  </div>
  <div class="frow2">
    <div class="fg"><label class="flbl">Password</label><input id="t-pwd" type="password" placeholder="Default: Teacher@123"></div>
    <div class="fg"><label class="flbl">Phone</label><input id="t-phone" placeholder="+265 999 000 000"></div>
  </div>
  <div class="fg"><label class="flbl">WhatsApp</label><input id="t-wa" placeholder="+265 999 000 000"></div>
  <div class="fg"><label class="flbl">Subjects note</label>
    <textarea id="t-subj" rows="2" placeholder="e.g. Mathematics, English…"></textarea></div>
</div>
<div class="modal-ftr">
  <button class="btn btn-ghost" onclick="closeModal('m-addTeacher')">Cancel</button>
  <button class="btn btn-pri" onclick="addTeacher()">Add Teacher</button>
</div></div></div>

<!-- Add Student -->
<div class="modal-bg" id="m-addStudent" onclick="if(event.target===this)closeModal(this.id)">
<div class="modal"><div class="modal-hdr"><h3>➕ Add Student</h3>
  <button class="close" onclick="closeModal('m-addStudent')">✕</button></div>
<div class="modal-bod">
  <div class="frow2">
    <div class="fg"><label class="flbl">Full Name *</label><input id="s-name" placeholder="Student full name"></div>
    <div class="fg"><label class="flbl">Admission No. *</label><input id="s-adm" placeholder="e.g. 2025-001"></div>
  </div>
  <div class="frow2">
    <div class="fg"><label class="flbl">Class *</label><select id="s-class"></select></div>
    <div class="fg"><label class="flbl">Gender</label>
      <select id="s-gender"><option value="">Select</option><option>Male</option><option>Female</option></select></div>
  </div>
  <div class="fg"><label class="flbl">Date of Birth</label><input id="s-dob" type="date"></div>
  <div class="sep"></div>
  <p style="font-size:12px;font-weight:800;color:var(--pri);text-transform:uppercase;letter-spacing:.5px;margin-bottom:14px">
    Parent / Guardian Details</p>
  <div class="frow2">
    <div class="fg"><label class="flbl">Parent Name</label><input id="p-name" placeholder="Parent full name"></div>
    <div class="fg"><label class="flbl">Parent Email</label><input id="p-email" type="email" placeholder="parent@email.com"></div>
  </div>
  <div class="frow2">
    <div class="fg"><label class="flbl">Parent Phone</label><input id="p-phone" placeholder="+265 999 000 000"></div>
    <div class="fg"><label class="flbl">Parent WhatsApp</label><input id="p-wa" placeholder="+265 999 000 000"></div>
  </div>
  <div class="fg"><label class="flbl">Home Address</label>
    <input id="s-addr" placeholder="Village / Area, District"></div>
</div>
<div class="modal-ftr">
  <button class="btn btn-ghost" onclick="closeModal('m-addStudent')">Cancel</button>
  <button class="btn btn-pri" onclick="addStudent()">Add Student</button>
</div></div></div>

<!-- Add Class -->
<div class="modal-bg" id="m-addClass" onclick="if(event.target===this)closeModal(this.id)">
<div class="modal"><div class="modal-hdr"><h3>➕ Add Class</h3>
  <button class="close" onclick="closeModal('m-addClass')">✕</button></div>
<div class="modal-bod">
  <div class="frow2">
    <div class="fg"><label class="flbl">Class Name *</label><input id="c-name" placeholder="e.g. Standard 1 A"></div>
    <div class="fg"><label class="flbl">Grade Level</label>
      <select id="c-grade">
        <option value="1">Standard 1</option><option value="2">Standard 2</option>
        <option value="3">Standard 3</option><option value="4">Standard 4</option>
        <option value="5">Standard 5</option><option value="6">Standard 6</option>
        <option value="7">Standard 7</option><option value="8">Standard 8</option>
      </select></div>
  </div>
  <div class="frow2">
    <div class="fg"><label class="flbl">Stream</label><input id="c-stream" placeholder="A, B, C…"></div>
    <div class="fg"><label class="flbl">Academic Year</label><input id="c-year" value="2025"></div>
  </div>
  <div class="fg"><label class="flbl">Class Teacher</label><select id="c-teacher"><option value="">None</option></select></div>
</div>
<div class="modal-ftr">
  <button class="btn btn-ghost" onclick="closeModal('m-addClass')">Cancel</button>
  <button class="btn btn-pri" onclick="addClass()">Add Class</button>
</div></div></div>

<!-- Add Subject -->
<div class="modal-bg" id="m-addSubject" onclick="if(event.target===this)closeModal(this.id)">
<div class="modal"><div class="modal-hdr"><h3>➕ Add Subject</h3>
  <button class="close" onclick="closeModal('m-addSubject')">✕</button></div>
<div class="modal-bod">
  <div class="frow2">
    <div class="fg"><label class="flbl">Subject Name *</label><input id="sub-name" placeholder="e.g. Mathematics"></div>
    <div class="fg"><label class="flbl">Subject Code</label><input id="sub-code" placeholder="e.g. MATH"></div>
  </div>
  <div class="frow2">
    <div class="fg"><label class="flbl">Max Marks</label><input id="sub-max" type="number" value="100"></div>
    <div class="fg"><label class="flbl">Pass Mark</label><input id="sub-pass" type="number" value="50"></div>
  </div>
</div>
<div class="modal-ftr">
  <button class="btn btn-ghost" onclick="closeModal('m-addSubject')">Cancel</button>
  <button class="btn btn-pri" onclick="addSubject()">Add Subject</button>
</div></div></div>

<!-- Assign Teacher -->
<div class="modal-bg" id="m-assign" onclick="if(event.target===this)closeModal(this.id)">
<div class="modal"><div class="modal-hdr"><h3>🔗 Assign Teacher to Subject</h3>
  <button class="close" onclick="closeModal('m-assign')">✕</button></div>
<div class="modal-bod">
  <div class="fg"><label class="flbl">Teacher *</label><select id="a-teacher"></select></div>
  <div class="fg"><label class="flbl">Subject *</label><select id="a-subject"></select></div>
  <div class="fg"><label class="flbl">Class *</label><select id="a-class"></select></div>
</div>
<div class="modal-ftr">
  <button class="btn btn-ghost" onclick="closeModal('m-assign')">Cancel</button>
  <button class="btn btn-pri" onclick="doAssign()">Assign</button>
</div></div></div>

<script>
// ── Navigation ────────────────────────────────────────────────────────────────
let allTeachers=[], allClasses=[], allSubjects=[], allStudents=[];

function sec(btn){
  const id = btn.dataset.sec;
  const target = $('sec-'+id);
  if(!target){ toast('Section not found: '+id,'error'); return; }
  $$('.sec').forEach(s=>s.classList.remove('active'));
  $$('.nav-btn').forEach(b=>b.classList.remove('active'));
  target.classList.add('active');
  btn.classList.add('active');
  $('pageTitle').textContent = btn.textContent.trim();
  closeSb();
  if(id==='dashboard') loadDashboard();
  else if(id==='teachers') loadTeachers();
  else if(id==='students') loadStudents();
  else if(id==='classes') loadClasses();
  else if(id==='subjects') loadSubjects();
  else if(id==='assignments') loadAssignments();
  else if(id==='grades') loadGradesView();
  else if(id==='reports') initReports();
  else if(id==='deliveries') loadDeliveries();
  else if(id==='timetable') loadTimetablePage();
  else if(id==='analytics') loadAnalytics();
  else if(id==='fees') loadFeesPage();
  else if(id==='promote') loadPromotePage();
  else if(id==='settings') loadSettings();
}
function toggleSb(){ $('sidebar').classList.toggle('open'); $('sbOverlay').classList.toggle('open'); }
function closeSb(){ $('sidebar').classList.remove('open'); $('sbOverlay').classList.remove('open'); }

// ── Date ──────────────────────────────────────────────────────────────────────
$('dateTag').textContent = new Date().toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short',year:'numeric'});

// ── DASHBOARD ─────────────────────────────────────────────────────────────────
async function loadDashboard(){
  const st = await API.get('/api/admin/stats'); if(!st) return;
  const defs = [
    {ic:'👩‍🏫',val:st.teachers,lbl:'Active Teachers',bg:'#ede9fe',ic_bg:'var(--pri)'},
    {ic:'👨‍🎓',val:st.students,lbl:'Students',bg:'#d1fae5',ic_bg:'var(--grn)'},
    {ic:'🏛️',val:st.classes,lbl:'Classes',bg:'#fef3c7',ic_bg:'var(--amb)'},
    {ic:'📚',val:st.subjects,lbl:'Subjects',bg:'#e0f2fe',ic_bg:'var(--sky)'},
    {ic:'📈',val:st.grades,lbl:'Grades Entered',bg:'#ede9fe',ic_bg:'var(--pur)'},
    {ic:'📨',val:st.reports_sent,lbl:'Reports Sent',bg:'#fce7f3',ic_bg:'var(--pnk)'},
  ];
  $('statsRow').innerHTML = defs.map(d=>`
    <div class="stat-card">
      <div class="stat-ic" style="background:${d.bg};color:${d.ic_bg}">${d.ic}</div>
      <div class="stat-inf">
        <div class="val">${d.val}</div>
        <div class="lbl">${d.lbl}</div>
      </div>
    </div>`).join('');
  if(st.pending>0){
    const t = await API.get('/api/admin/teachers');
    const pend = (t||[]).filter(x=>!x.approved);
    $('pendingList').innerHTML = pend.length ? pend.map(p=>`
      <div class="rep-row">
        <div class="avatar" style="width:38px;height:38px;background:var(--amb)">${p.full_name[0]}</div>
        <div style="flex:1;min-width:0">
          <div style="font-weight:700;font-size:14px">${p.full_name}</div>
          <div style="font-size:12px;color:var(--g500)">${p.username}</div>
          ${p.subjects_note?`<div style="font-size:11px;color:var(--g400)">📚 ${p.subjects_note}</div>`:''}
        </div>
        <button class="btn btn-sm btn-grn" onclick="approveTeacher(${p.id})">✅ Approve</button>
        <button class="btn btn-sm btn-red" onclick="delTeacher(${p.id},true)">❌</button>
      </div>`).join('')
    : '<div class="empty"><div class="ei">✅</div><h4>All Caught Up!</h4><p>No pending approvals</p></div>';
  } else {
    $('pendingList').innerHTML = '<div class="empty"><div class="ei">✅</div><h4>No Pending Approvals</h4></div>';
  }
  const del = await API.get('/api/admin/reports/deliveries');
  const rec = (del||[]).slice(0,8);
  $('recentDeliveries').innerHTML = rec.length ? `<table><tbody>${rec.map(d=>`<tr>
    <td><strong>${d.student_name}</strong></td>
    <td><span class="badge ${d.channel==='email'?'badge-sky':'badge-grn'}">${d.channel==='email'?'📧 Email':'💬 WhatsApp'}</span></td>
    <td>${d.status==='sent'?'<span class="badge badge-grn">Sent</span>':'<span class="badge badge-red">Failed</span>'}</td>
    <td style="font-size:11px;color:var(--g400)">${fmtDate(d.sent_at)}</td>
  </tr>`).join('')}</tbody></table>`
  : '<div class="empty"><div class="ei">📭</div><p>No deliveries yet</p></div>';
}

// ── TEACHERS ──────────────────────────────────────────────────────────────────
async function loadTeachers(){
  allTeachers = await API.get('/api/admin/teachers') || [];
  $('teacherTbody').innerHTML = allTeachers.length ? allTeachers.map(t=>`<tr>
    <td><div style="display:flex;align-items:center;gap:10px">
      <div class="avatar" style="width:34px;height:34px;font-size:13px;background:${t.avatar_color||'var(--pri)'}">${t.full_name[0]}</div>
      <strong>${t.full_name}</strong></div></td>
    <td>${t.username}</td>
    <td>${t.phone||'—'}</td>
    <td>${t.whatsapp||'—'}</td>
    <td style="font-size:12px;max-width:160px;overflow:hidden;text-overflow:ellipsis">${t.subjects_note||'—'}</td>
    <td>${t.approved?'<span class="badge badge-grn">✅ Active</span>':'<span class="badge badge-amb">⏳ Pending</span>'}</td>
    <td style="font-size:12px;color:var(--g400)">${fmtDate(t.created_at)}</td>
    <td><div style="display:flex;gap:6px">
      ${!t.approved?`<button class="btn btn-sm btn-grn" onclick="approveTeacher(${t.id})">Approve</button>`:''}
      <button class="btn btn-sm btn-red btn-icon" onclick="delTeacher(${t.id})" title="Delete">🗑</button>
    </div></td>
  </tr>`).join('')
  : '<tr><td colspan="8"><div class="empty"><div class="ei">👩‍🏫</div><h4>No teachers yet</h4></div></td></tr>';
}
async function addTeacher(){
  const r = await API.post('/api/admin/teachers/add',{
    full_name:$('t-name').value, email:$('t-email').value,
    password:$('t-pwd').value||'Teacher@123',
    phone:$('t-phone').value, whatsapp:$('t-wa').value, subjects_note:$('t-subj').value});
  if(r?.ok){ toast('Teacher added!'); closeModal('m-addTeacher'); loadTeachers(); }
  else toast(r?.msg||'Error','error');
}
async function approveTeacher(id){
  await API.post(`/api/admin/teachers/${id}/approve`);
  toast('Teacher approved! 🎉'); loadTeachers(); loadDashboard();
}
async function delTeacher(id, isRej=false){
  if(!confirm_del(isRej?'Reject this registration?':'Delete teacher and all their data?')) return;
  await API.del(`/api/admin/teachers/${id}`);
  toast(isRej?'Registration rejected':'Teacher deleted','warn');
  loadTeachers(); if(isRej) loadDashboard();
}

// ── STUDENTS ──────────────────────────────────────────────────────────────────
async function loadStudents(){
  const cid = $('flt-class').value;
  const url = '/api/admin/students'+(cid?`?class_id=${cid}`:'');
  allStudents = await API.get(url) || [];
  allClasses  = await API.get('/api/admin/classes') || [];
  // Populate class filter
  const cOpts = '<option value="">All Classes</option>'+allClasses.map(c=>`<option value="${c.id}" ${$('flt-class').value==c.id?'selected':''}>${c.name}</option>`).join('');
  $('flt-class').innerHTML = cOpts;
  $('s-class').innerHTML   = allClasses.map(c=>`<option value="${c.id}">${c.name}</option>`).join('');
  renderStudents();
}
function renderStudents(){
  const q = $('flt-stu-search').value.toLowerCase();
  const list = allStudents.filter(s=>s.full_name.toLowerCase().includes(q)||s.admission_number.toLowerCase().includes(q));
  $('studentTbody').innerHTML = list.length ? list.map(s=>`<tr>
    <td><span class="badge badge-sky">${s.admission_number}</span></td>
    <td><strong>${s.full_name}</strong></td>
    <td>${s.gender||'—'}</td>
    <td>${s.class_name||'—'}</td>
    <td>${s.parent_name||'—'}</td>
    <td style="font-size:12px">${s.parent_email||'—'}</td>
    <td>${s.parent_phone||'—'}</td>
    <td style="display:flex;gap:6px">
      <button class="btn btn-sm btn-ghost" onclick="openStudentProfile(${s.id})">👤 Profile</button>
      <button class="btn btn-sm btn-red btn-icon" onclick="delStudent(${s.id})" title="Remove">🗑</button>
    </td>
  </tr>`).join('')
  : '<tr><td colspan="8"><div class="empty"><div class="ei">👨‍🎓</div><h4>No students found</h4></div></td></tr>';
}
async function addStudent(){
  const r = await API.post('/api/admin/students',{
    full_name:$('s-name').value, admission_number:$('s-adm').value,
    class_id:$('s-class').value, gender:$('s-gender').value, date_of_birth:$('s-dob').value,
    parent_name:$('p-name').value, parent_email:$('p-email').value,
    parent_phone:$('p-phone').value, parent_whatsapp:$('p-wa').value, address:$('s-addr').value});
  if(r?.ok){ toast('Student added! 🎉'); closeModal('m-addStudent'); loadStudents(); }
  else toast(r?.msg||'Error','error');
}
async function delStudent(id){
  if(!confirm_del('Remove this student from the system?')) return;
  await API.del(`/api/admin/students/${id}`);
  toast('Student removed','warn'); loadStudents();
}

// ── CLASSES ───────────────────────────────────────────────────────────────────
async function loadClasses(){
  allClasses   = await API.get('/api/admin/classes')  || [];
  allTeachers  = await API.get('/api/admin/teachers') || [];
  $('c-teacher').innerHTML = '<option value="">None</option>'+
    allTeachers.filter(t=>t.approved).map(t=>`<option value="${t.id}">${t.full_name}</option>`).join('');
  $('classTbody').innerHTML = allClasses.length ? allClasses.map(c=>`<tr>
    <td><strong>${c.name}</strong></td>
    <td><span class="badge badge-pri">Std ${c.grade_level}</span></td>
    <td>${c.stream||'—'}</td><td>${c.academic_year}</td>
    <td>${c.teacher_name||'—'}</td>
    <td><span class="badge badge-grn">👨‍🎓 ${c.student_count||0}</span></td>
    <td><button class="btn btn-sm btn-red btn-icon" onclick="delClass(${c.id})">🗑</button></td>
  </tr>`).join('')
  : '<tr><td colspan="7"><div class="empty"><div class="ei">🏛️</div><h4>No classes yet</h4></div></td></tr>';
}
async function addClass(){
  const r = await API.post('/api/admin/classes',{
    name:$('c-name').value, grade_level:$('c-grade').value,
    stream:$('c-stream').value, academic_year:$('c-year').value,
    class_teacher_id:$('c-teacher').value||null});
  if(r?.ok){ toast('Class added!'); closeModal('m-addClass'); loadClasses(); }
  else toast('Error','error');
}
async function delClass(id){
  if(!confirm_del('Delete this class?')) return;
  await API.del(`/api/admin/classes/${id}`); toast('Class deleted','warn'); loadClasses();
}

// ── SUBJECTS ──────────────────────────────────────────────────────────────────
async function loadSubjects(){
  allSubjects = await API.get('/api/admin/subjects') || [];
  $('subjectTbody').innerHTML = allSubjects.length ? allSubjects.map(s=>`<tr>
    <td><strong>${s.name}</strong></td>
    <td><span class="badge badge-pur">${s.code||'—'}</span></td>
    <td>${s.max_marks}</td><td>${s.pass_mark}</td>
    <td><button class="btn btn-sm btn-red btn-icon" onclick="delSubject(${s.id})">🗑</button></td>
  </tr>`).join('')
  : '<tr><td colspan="5"><div class="empty"><div class="ei">📚</div><h4>No subjects yet</h4></div></td></tr>';
}
async function addSubject(){
  const r = await API.post('/api/admin/subjects',{
    name:$('sub-name').value, code:$('sub-code').value,
    max_marks:parseInt($('sub-max').value)||100, pass_mark:parseInt($('sub-pass').value)||50});
  if(r?.ok){ toast('Subject added!'); closeModal('m-addSubject'); loadSubjects(); }
  else toast(r?.msg||'Error','error');
}
async function delSubject(id){
  if(!confirm_del()) return;
  await API.del(`/api/admin/subjects/${id}`); toast('Subject deleted','warn'); loadSubjects();
}

// ── ASSIGNMENTS ───────────────────────────────────────────────────────────────
async function loadAssignments(){
  [allTeachers, allSubjects, allClasses] = await Promise.all([
    API.get('/api/admin/teachers'), API.get('/api/admin/subjects'), API.get('/api/admin/classes')]);
  $('a-teacher').innerHTML = (allTeachers||[]).filter(t=>t.approved)
    .map(t=>`<option value="${t.id}">${t.full_name}</option>`).join('');
  $('a-subject').innerHTML = (allSubjects||[]).map(s=>`<option value="${s.id}">${s.name}</option>`).join('');
  $('a-class').innerHTML   = (allClasses||[]).map(c=>`<option value="${c.id}">${c.name}</option>`).join('');
  const rows = await API.get('/api/admin/assignments') || [];
  $('assignTbody').innerHTML = rows.length ? rows.map(r=>`<tr>
    <td><strong>${r.teacher_name}</strong></td>
    <td>${r.subject_name}</td>
    <td>${r.class_name}</td>
    <td><button class="btn btn-sm btn-red btn-icon" onclick="delAssign(${r.id})">🗑</button></td>
  </tr>`).join('')
  : '<tr><td colspan="4"><div class="empty"><div class="ei">🔗</div><h4>No assignments yet</h4></div></td></tr>';
}
async function doAssign(){
  const r = await API.post('/api/admin/assignments',{
    teacher_id:$('a-teacher').value, subject_id:$('a-subject').value, class_id:$('a-class').value});
  if(r?.ok){ toast('Assigned! ✅'); closeModal('m-assign'); loadAssignments(); }
  else toast(r?.msg||'Error (possibly duplicate)','error');
}
async function delAssign(id){
  await API.del(`/api/admin/assignments/${id}`); toast('Assignment removed','warn'); loadAssignments();
}

// ── GRADES VIEW ───────────────────────────────────────────────────────────────
let _gradeData = [];
async function loadGradesView(){
  const cid  = $('gv-class').value;
  const term = $('gv-term').value;
  const container = $('gradeViewContainer');
  container.innerHTML = '<div class="empty"><div class="ei" style="animation:spin 1s linear infinite">⏳</div><p>Loading grades…</p></div>';
  _gradeData = await API.get(`/api/admin/grades?class_id=${cid}&term=${encodeURIComponent(term)}`) || [];
  if(!_gradeData.length){
    container.innerHTML = '<div class="card"><div class="card-bod"><div class="empty"><div class="ei">📈</div><h4>No grades entered yet for this selection</h4><p>Teachers need to enter grades first</p></div></div></div>';
    return;
  }
  renderGradesTables(_gradeData);
}
function filterGradesTable(){
  if(!_gradeData.length) return;
  const q = ($('gv-search').value||'').toLowerCase();
  if(!q){ renderGradesTables(_gradeData); return; }
  const filtered = _gradeData.map(cls=>({
    ...cls,
    students: cls.students.filter(s=>s.student_name.toLowerCase().includes(q))
  })).filter(cls=>cls.students.length);
  renderGradesTables(filtered);
}
function renderGradesTables(data){
  const container = $('gradeViewContainer');
  container.innerHTML = data.map(cls=>{
    const subs = cls.subjects;
    const thead = `<tr><th>Student</th>${subs.map(s=>`<th style="min-width:90px;text-align:center">${s}</th>`).join('')}<th style="text-align:center">Average</th><th style="text-align:center">Grade</th></tr>`;
    const tbody = cls.students.map(stu=>{
      const cells = subs.map(sub=>{
        const sg = stu.subjects[sub];
        if(!sg) return `<td style="text-align:center;color:var(--g300)">—</td>`;
        const score = sg.score ?? null;
        const maxS  = sg.max || 100;
        if(score===null) return `<td style="text-align:center;color:var(--g300)">—</td>`;
        const pctVal = Math.round(score/maxS*100);
        return `<td style="text-align:center">
          <div style="font-weight:800;font-size:14px">${score}</div>
          <div style="font-size:11px;color:var(--g400)">${pctVal}%</div>
          <div style="margin-top:2px">${gradeChip(score,maxS)}</div>
        </td>`;
      }).join('');
      const avg = stu.average;
      const avgCell = avg!=null
        ? `<td style="text-align:center;font-weight:800;color:var(--pri)">${avg}%</td><td style="text-align:center">${gradeChip(avg)}</td>`
        : `<td style="text-align:center;color:var(--g300)">—</td><td>—</td>`;
      return `<tr><td><strong>${stu.student_name}</strong></td>${cells}${avgCell}</tr>`;
    }).join('');
    return `<div class="card" style="margin-bottom:20px">
      <div class="card-hdr">
        <h3>🏛️ ${cls.class_name}</h3>
        <span class="badge badge-pri">👨‍🎓 ${cls.students.length} students · 📚 ${subs.length} subjects</span>
      </div>
      <div class="tbl-wrap"><table><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>
    </div>`;
  }).join('');
}

// ── REPORTS ───────────────────────────────────────────────────────────────────
async function initReports(){
  allClasses = await API.get('/api/admin/classes') || [];
  $('rp-class').innerHTML = '<option value="">All Classes</option>'+
    allClasses.map(c=>`<option value="${c.id}">${c.name}</option>`).join('');
  $('gv-class').innerHTML = '<option value="">All Classes</option>'+
    allClasses.map(c=>`<option value="${c.id}">${c.name}</option>`).join('');
}
async function generateReports(){
  const btn = $('genBtn');
  const term = $('rp-term').value;
  const yr   = $('rp-year').value;
  const doEmail = $('rp-email').checked;
  const doWa    = $('rp-wa').checked;

  // Reset UI
  btn.disabled = true; btn.innerHTML = '⏳ Generating…';
  $('rp-progress').style.display = 'block';
  $('rp-prog-bar').style.width = '10%';
  $('rp-prog-pct').textContent = '…';
  $('rp-prog-label').textContent = 'Generating reports, please wait…';
  $('rp-prog-current').textContent = 'This may take a moment for large classes';
  $('rp-results').innerHTML = '';

  let r;
  try {
    r = await API.post('/api/admin/reports/generate',{
      class_id: $('rp-class').value||null,
      term, academic_year: yr,
      send_email: doEmail,
      send_whatsapp: doWa
    });
  } catch(e) {
    r = {ok:false, error: e.message};
  }

  // Always re-enable button and complete bar regardless of outcome
  btn.disabled = false; btn.innerHTML = '🚀 Generate Reports';
  $('rp-prog-bar').style.width = '100%';
  $('rp-prog-pct').textContent = '100%';

  if(!r || !r.ok){
    $('rp-progress').style.display='none';
    toast((r?.error)||'Error generating reports — check server logs','error'); return;
  }

  $('rp-prog-label').textContent = `✅ Done — ${r.generated} generated, ${r.skipped} skipped`;
  $('rp-prog-current').textContent = '';

  // Summary badges
  const emailSent  = r.results.filter(x=>x.email_status?.startsWith('✅')).length;
  const waSent     = r.results.filter(x=>x.wa_status?.startsWith('✅')).length;

  $('rp-results').innerHTML = `
    <div class="stat-grid" style="margin-bottom:20px">
      <div class="stat-card"><div class="stat-ic" style="background:#ede9fe;color:var(--pri)">📋</div>
        <div class="stat-inf"><div class="val">${r.generated}</div><div class="lbl">Reports Generated</div></div></div>
      <div class="stat-card"><div class="stat-ic" style="background:#d1fae5;color:var(--grn)">✅</div>
        <div class="stat-inf"><div class="val">${r.total}</div><div class="lbl">Students Processed</div></div></div>
      <div class="stat-card"><div class="stat-ic" style="background:#e0f2fe;color:var(--sky)">📧</div>
        <div class="stat-inf"><div class="val">${emailSent}</div><div class="lbl">Emails Sent</div></div></div>
      <div class="stat-card"><div class="stat-ic" style="background:#f0fdf4;color:var(--grn)">💬</div>
        <div class="stat-inf"><div class="val">${waSent}</div><div class="lbl">WhatsApp Sent</div></div></div>
    </div>
    <div class="card">
      <div class="card-hdr">
        <h3>📋 ${term} — ${yr} Results</h3>
        <div style="display:flex;gap:8px">
          <span class="badge badge-grn">${r.generated} generated</span>
          ${r.skipped?'<span class="badge badge-amb">'+r.skipped+' skipped</span>':''}
        </div>
      </div>
      <div class="tbl-wrap">
        <table><thead><tr>
          <th>Student</th><th>Class</th><th>Subjects</th><th>Average</th><th>Grade</th>
          <th>📧 Email</th><th>💬 WhatsApp</th><th>Download</th>
        </tr></thead>
        <tbody>${r.results.map(row=>row.status==='skipped'?`
          <tr style="background:#fffbeb">
            <td><strong>${row.name}</strong></td>
            <td>${row.class||'—'}</td>
            <td colspan="6"><span class="badge badge-amb">⚠️ Skipped: ${row.reason}</span></td>
          </tr>`:`
          <tr>
            <td><strong>${row.name}</strong></td>
            <td><span class="badge badge-sky">${row.class||'—'}</span></td>
            <td style="text-align:center">${row.subjects||'—'}</td>
            <td><strong>${row.avg}%</strong></td>
            <td>${gradeChip(row.avg)}</td>
            <td style="font-size:12px">${row.email_status||'—'}</td>
            <td style="font-size:12px">${row.wa_status||'—'}</td>
            <td style="display:flex;gap:6px;flex-wrap:wrap">
              <a href="/api/admin/reports/download/${row.id}?term=${encodeURIComponent(term)}&year=${yr}"
                class="btn btn-sm btn-ghost" target="_blank">⬇ PDF</a>
              <button class="btn btn-sm btn-pri-out"
                onclick="resendReport(${row.id},'${term.replace(/'/g,"\\'")}','${yr}',this)">📤 Resend</button>
            </td>
          </tr>`).join('')}
        </tbody></table>
      </div>
    </div>`;
  toast(`${r.generated} reports generated! 🎉`);
}

async function resendReport(sid, term, yr, btn){
  const doEmail = $('rp-email').checked;
  const doWa    = $('rp-wa').checked;
  if(!doEmail && !doWa){ toast('Check at least one delivery option above','warn'); return; }
  btn.disabled=true; btn.textContent='⏳';
  const r = await API.post('/api/admin/reports/resend',{
    student_id:sid, term, academic_year:yr, send_email:doEmail, send_whatsapp:doWa
  });
  btn.disabled=false; btn.textContent='📤 Resend';
  if(r?.ok){
    toast(`Resent to ${r.result.name} — Email: ${r.result.email_status} | WA: ${r.result.wa_status}`);
  } else {
    toast(r?.error||'Resend failed','error');
  }
}

// ── DELIVERIES LOG ────────────────────────────────────────────────────────────
async function loadDeliveries(){
  const rows = await API.get('/api/admin/reports/deliveries') || [];
  $('delivTbody').innerHTML = rows.length ? rows.map(r=>`<tr>
    <td><strong>${r.student_name}</strong></td>
    <td>${r.term}</td><td>${r.academic_year}</td>
    <td><span class="badge ${r.channel==='email'?'badge-sky':'badge-grn'}">${r.channel==='email'?'📧 Email':'💬 WhatsApp'}</span></td>
    <td style="font-size:12px;max-width:180px;overflow:hidden;text-overflow:ellipsis">${r.recipient||'—'}</td>
    <td>${r.status==='sent'?'<span class="badge badge-grn">✅ Sent</span>':'<span class="badge badge-red">❌ Failed</span>'}</td>
    <td style="font-size:12px;color:var(--g400)">${fmtDate(r.sent_at)}</td>
  </tr>`).join('')
  : '<tr><td colspan="7"><div class="empty"><div class="ei">📭</div><h4>No deliveries logged yet</h4></div></td></tr>';
}

// ── STUDENT PROFILE MODAL ─────────────────────────────────────────────────────
async function openStudentProfile(sid){
  openModal('m-studentProfile');
  $('profileModalBody').innerHTML = '<div class="empty"><div class="ei" style="animation:spin 1s linear infinite">⏳</div><p>Loading…</p></div>';
  const p = await API.get(`/api/admin/student/${sid}/profile`);
  if(!p){ $('profileModalBody').innerHTML='<div class="empty"><p>Failed to load profile</p></div>'; return; }
  $('profileModalTitle').textContent = `👤 ${p.student.full_name}`;
  const gl = l => `<span class="chip chip-${l}">${l}</span>`;
  $('profileModalBody').innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px">
      <div style="background:var(--pri-xl);border-radius:var(--r12);padding:18px;display:flex;gap:14px;align-items:center">
        <div class="avatar" style="width:56px;height:56px;background:var(--pri);font-size:20px;flex-shrink:0">${p.student.full_name[0]}</div>
        <div>
          <div style="font-size:16px;font-weight:800">${p.student.full_name}</div>
          <div style="font-size:12px;color:var(--g500)">${p.student.admission_number}</div>
          <span class="badge badge-sky" style="margin-top:4px">${p.student.class_name||'No Class'}</span>
        </div>
      </div>
      <div style="background:var(--g50);border-radius:var(--r12);padding:16px;font-size:13px;display:grid;gap:6px">
        <div style="display:flex;justify-content:space-between"><span style="color:var(--g500)">Parent</span><span style="font-weight:600">${p.student.parent_name||'—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span style="color:var(--g500)">Phone</span><span>${p.student.parent_phone||'—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span style="color:var(--g500)">Email</span><span>${p.student.parent_email||'—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span style="color:var(--g500)">Gender</span><span>${p.student.gender||'—'}</span></div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px">
      ${[{ic:'📈',v:p.summary.avg_score!=null?p.summary.avg_score+'%':'—',l:'Overall Avg',bg:'#ede9fe',c:'var(--pri)'},
         {ic:'📚',v:p.summary.subjects_count,l:'Subjects',bg:'#e0f2fe',c:'var(--sky)'},
         {ic:'📋',v:p.summary.attendance_rate!=null?p.summary.attendance_rate+'%':'—',l:'Attendance',bg:'#d1fae5',c:'var(--grn)'},
         {ic:'🏅',v:p.summary.overall_grade||'—',l:'Grade',bg:'#fef3c7',c:'var(--amb)'}
        ].map(s=>`<div style="background:${s.bg};border-radius:var(--r12);padding:14px;text-align:center">
          <div style="font-size:22px">${s.ic}</div>
          <div style="font-size:18px;font-weight:800;color:${s.c};margin:4px 0">${s.v}</div>
          <div style="font-size:11px;color:var(--g500)">${s.l}</div>
        </div>`).join('')}
    </div>
    ${p.grades_by_term.length ? `
    <h4 style="margin-bottom:10px;font-size:14px">📊 Grades History</h4>
    ${p.grades_by_term.map(t=>`
      <div style="margin-bottom:14px">
        <div style="font-size:12px;font-weight:700;color:var(--pri);margin-bottom:6px;text-transform:uppercase">${t.term}</div>
        <table style="width:100%;border-collapse:collapse">
          <thead><tr style="background:var(--g50)"><th style="padding:7px 10px;text-align:left;font-size:12px">Subject</th><th style="padding:7px 10px;text-align:center;font-size:12px">Score</th><th style="padding:7px 10px;text-align:center;font-size:12px">%</th><th style="padding:7px 10px;text-align:center;font-size:12px">Grade</th></tr></thead>
          <tbody>${t.grades.map(g=>`<tr style="border-bottom:1px solid var(--g100)">
            <td style="padding:7px 10px;font-weight:600">${g.subject_name}</td>
            <td style="padding:7px 10px;text-align:center;font-weight:800">${g.score}</td>
            <td style="padding:7px 10px;text-align:center">${Math.round(g.score/g.max_score*100)}%</td>
            <td style="padding:7px 10px;text-align:center">${gradeChip(g.score,g.max_score)}</td>
          </tr>`).join('')}</tbody>
        </table>
      </div>`).join('')}` : '<div class="empty" style="padding:20px"><div class="ei">📚</div><p>No grades recorded yet</p></div>'}
    ${p.attendance.length ? `
    <h4 style="margin:14px 0 8px;font-size:14px">📋 Recent Attendance (last 20 days)</h4>
    <div style="display:flex;flex-wrap:wrap;gap:6px">
      ${p.attendance.slice(0,20).map(a=>`
        <div title="${a.date}: ${a.status}" style="width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;
          background:${a.status==='present'?'var(--grn-l)':a.status==='absent'?'var(--red-l)':a.status==='late'?'var(--amb-l)':'var(--g100)'};
          color:${a.status==='present'?'var(--grn)':a.status==='absent'?'var(--red)':a.status==='late'?'var(--amb)':'var(--g500)'}">
          ${a.status==='present'?'✓':a.status==='absent'?'✗':a.status==='late'?'L':'E'}
        </div>`).join('')}
    </div>` : ''}`;
}

// ── ANALYTICS ─────────────────────────────────────────────────────────────────
async function loadAnalytics(){
  const term = $('an-term').value;
  const [perf, att] = await Promise.all([
    API.get(`/api/admin/analytics/class-performance?term=${encodeURIComponent(term)}`),
    API.get('/api/admin/analytics/attendance')
  ]);
  if(!perf||!att) return;
  renderBarChart($('perfChart'), perf.map(c=>c.class_name), perf.map(c=>c.avg_score), perf.map(c=>c.avg_score>=70?'var(--grn)':c.avg_score>=50?'var(--amb)':'var(--red)'), '%');
  renderBarChart($('attChart'), att.map(c=>c.class_name), att.map(c=>c.rate), att.map(c=>c.rate>=90?'var(--grn)':c.rate>=75?'var(--amb)':'var(--red)'), '%');
  $('leaderTbody').innerHTML = perf.length ? perf.map((c,i)=>`<tr>
    <td><strong>#${i+1}</strong></td>
    <td><strong>${c.class_name}</strong></td>
    <td style="text-align:center">${c.student_count}</td>
    <td><strong style="color:var(--pri)">${c.avg_score!=null?c.avg_score+'%':'—'}</strong></td>
    <td>${c.avg_score!=null?gradeChip(c.avg_score):'—'}</td>
    <td>${(att.find(a=>a.class_name===c.class_name)||{rate:'—'}).rate}%</td>
    <td style="font-size:12px">${c.top_student||'—'}</td>
  </tr>`).join('') : '<tr><td colspan="7"><div class="empty"><div class="ei">📊</div><p>No grade data for this term</p></div></td></tr>';
}

function renderBarChart(container, labels, values, colors, unit=''){
  if(!labels.length){ container.innerHTML='<div class="empty"><div class="ei">📊</div><p>No data yet</p></div>'; return; }
  const max = Math.max(...values.filter(v=>v!=null), 1);
  container.innerHTML = `<div style="display:flex;align-items:flex-end;gap:8px;height:220px;padding:10px 0;overflow-x:auto">
    ${labels.map((l,i)=>{
      const v = values[i] ?? 0;
      const h = Math.round((v/max)*180);
      const col = Array.isArray(colors)?colors[i]:(colors||'var(--pri)');
      return `<div style="display:flex;flex-direction:column;align-items:center;min-width:48px;flex:1">
        <div style="font-size:11px;font-weight:700;margin-bottom:4px;color:var(--g700)">${v}${unit}</div>
        <div style="background:${col};width:100%;height:${h}px;border-radius:6px 6px 0 0;transition:height .4s;min-height:4px"></div>
        <div style="font-size:10px;color:var(--g500);margin-top:5px;text-align:center;line-height:1.2;max-width:52px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${l}">${l}</div>
      </div>`;
    }).join('')}
  </div>`;
}

// ── FEES ───────────────────────────────────────────────────────────────────────
async function loadFeesPage(){
  const [cls] = await Promise.all([API.get('/api/admin/classes')||[]]);
  if(cls){
    const opts = cls.map(c=>`<option value="${c.id}">${c.name}</option>`).join('');
    ['fee-class','bf-class'].forEach(id=>{ const el=$(id); if(el) el.innerHTML='<option value="">All Classes</option>'+opts; });
  }
  loadFees(); loadFeeSummary();
}
async function loadFeeSummary(){
  const s = await API.get('/api/admin/fees/summary');
  if(!s) return;
  $('feeSummaryRow').innerHTML = [
    {ic:'💰',v:'MK '+Number(s.total_due||0).toLocaleString(),l:'Total Due',bg:'#ede9fe',c:'var(--pri)'},
    {ic:'✅',v:'MK '+Number(s.total_paid||0).toLocaleString(),l:'Total Paid',bg:'#d1fae5',c:'var(--grn)'},
    {ic:'⚠️',v:'MK '+Number(s.total_balance||0).toLocaleString(),l:'Outstanding',bg:'#fee2e2',c:'var(--red)'},
    {ic:'👥',v:s.defaulters||0,l:'Defaulters',bg:'#fef3c7',c:'var(--amb)'},
  ].map(s=>`<div class="stat-card"><div class="stat-ic" style="background:${s.bg};color:${s.c}">${s.ic}</div>
    <div class="stat-inf"><div class="val" style="font-size:15px">${s.v}</div><div class="lbl">${s.l}</div></div></div>`).join('');
}
async function loadFees(){
  const cid=$('fee-class').value, term=$('fee-term').value, status=$('fee-status').value;
  let url=`/api/admin/fees?term=${encodeURIComponent(term)}`;
  if(cid) url+=`&class_id=${cid}`;
  if(status) url+=`&status=${status}`;
  const rows = await API.get(url)||[];
  $('feeTbody').innerHTML = rows.length ? rows.map(r=>{
    const bal = (r.amount_due||0)-(r.amount_paid||0);
    const sc = r.status==='paid'?'badge-grn':r.status==='partial'?'badge-amb':'badge-red';
    return `<tr>
      <td><strong>${r.student_name}</strong></td>
      <td><span class="badge badge-sky">${r.class_name||'—'}</span></td>
      <td>${r.term}</td>
      <td>MK ${Number(r.amount_due||0).toLocaleString()}</td>
      <td style="color:var(--grn);font-weight:700">MK ${Number(r.amount_paid||0).toLocaleString()}</td>
      <td style="color:${bal>0?'var(--red)':'var(--grn)'};font-weight:700">MK ${Number(bal).toLocaleString()}</td>
      <td><span class="badge ${sc}">${r.status}</span></td>
      <td style="display:flex;gap:6px">
        <button class="btn btn-sm btn-grn" onclick="recordPayment(${r.id},${r.amount_due-r.amount_paid},this)">💳 Pay</button>
        <button class="btn btn-sm btn-red" onclick="deleteFee(${r.id},this)">🗑</button>
      </td>
    </tr>`;
  }).join('') : '<tr><td colspan="8"><div class="empty"><div class="ei">💰</div><h4>No fee records</h4><p>Set fees for a class using the button above</p></div></td></tr>';
}
async function setBulkFees(){
  const r = await API.post('/api/admin/fees/bulk',{
    class_id:$('bf-class').value||null, term:$('bf-term').value,
    amount_due:parseFloat($('bf-amount').value)||0,
    due_date:$('bf-due').value, note:$('bf-note').value
  });
  if(r?.ok){ toast(`Fees set for ${r.count} students ✅`); closeModal('m-bulkFees'); loadFees(); loadFeeSummary(); }
  else toast(r?.error||'Error','error');
}
async function recordPayment(fid, balance, btn){
  const amt = prompt(`Record payment (max MK ${Number(balance).toLocaleString()}):`);
  if(!amt||isNaN(amt)) return;
  btn.disabled=true;
  const r = await API.post(`/api/admin/fees/${fid}/pay`,{amount:parseFloat(amt)});
  btn.disabled=false;
  if(r?.ok){ toast('Payment recorded ✅'); loadFees(); loadFeeSummary(); }
  else toast(r?.error||'Error','error');
}
async function deleteFee(fid, btn){
  if(!confirm('Delete this fee record?')) return;
  btn.disabled=true;
  const r = await API.del(`/api/admin/fees/${fid}`);
  if(r?.ok){ toast('Deleted'); loadFees(); loadFeeSummary(); }
  else toast('Error','error');
}

// ── PROMOTE ────────────────────────────────────────────────────────────────────
async function loadPromotePage(){
  const cls = await API.get('/api/admin/classes')||[];
  const opts = cls.map(c=>`<option value="${c.id}">${c.name}</option>`).join('');
  $('promo-from').innerHTML='<option value="">Select class…</option>'+opts;
  $('promo-to').innerHTML='<option value="">Select class…</option>'+opts;
}
async function previewPromotion(){
  const from=$('promo-from').value, to=$('promo-to').value, min=$('promo-min').value;
  if(!from||!to){ toast('Select both classes','warn'); return; }
  const r = await API.post('/api/admin/students/promote',{from_class:from,to_class:to,min_avg:parseFloat(min)||40,preview:true});
  if(!r) return;
  $('promoPreview').innerHTML=`<div class="card">
    <div class="card-hdr"><h3>👁 Preview</h3>
      <div style="display:flex;gap:8px">
        <span class="badge badge-grn">✅ ${r.promote?.length||0} will be promoted</span>
        <span class="badge badge-amb">⚠️ ${r.retain?.length||0} will be retained</span>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px">
      <div><div style="font-weight:700;color:var(--grn);margin-bottom:8px">✅ Promote</div>
        ${(r.promote||[]).map(s=>`<div style="padding:6px 0;border-bottom:1px solid var(--g100);font-size:13px"><strong>${s.name}</strong> — ${s.avg}%</div>`).join('')||'<p style="color:var(--g400);font-size:13px">None</p>'}
      </div>
      <div><div style="font-weight:700;color:var(--amb);margin-bottom:8px">⚠️ Retain (below ${min}%)</div>
        ${(r.retain||[]).map(s=>`<div style="padding:6px 0;border-bottom:1px solid var(--g100);font-size:13px"><strong>${s.name}</strong> — ${s.avg!=null?s.avg+'%':'no grades'}</div>`).join('')||'<p style="color:var(--g400);font-size:13px">None</p>'}
      </div>
    </div>
  </div>`;
}
async function runPromotion(){
  const from=$('promo-from').value, to=$('promo-to').value, min=$('promo-min').value;
  if(!from||!to){ toast('Select both classes','warn'); return; }
  if(!confirm(`Promote qualifying students from the selected class? This cannot be undone.`)) return;
  const r = await API.post('/api/admin/students/promote',{from_class:from,to_class:to,min_avg:parseFloat(min)||40,preview:false});
  if(r?.ok){ toast(`${r.promoted} students promoted! 🎓`); loadStudents(); }
  else toast(r?.error||'Error','error');
}

// ── SETTINGS ───────────────────────────────────────────────────────────────────
async function loadSettings(){
  const s = await API.get('/api/admin/settings'); if(!s) return;
  const fields = {'school_name':'s-name','school_motto':'s-motto','school_address':'s-address',
    'school_phone':'s-phone','academic_year':'s-year','email_user':'s-email-user',
    'email_pass':'s-email-pass','smtp_host':'s-smtp-host','smtp_port':'s-smtp-port',
    'twilio_sid':'s-twilio-sid','twilio_token':'s-twilio-token','twilio_from':'s-twilio-from'};
  Object.entries(fields).forEach(([k,id])=>{ const el=$(id); if(el&&s[k]) el.value=s[k]; });
  const th = localStorage.getItem('theme')||'light';
  const sel=$('s-theme'); if(sel) sel.value=th;
}
async function saveSettings(){
  const fields = {'school_name':'s-name','school_motto':'s-motto','school_address':'s-address',
    'school_phone':'s-phone','academic_year':'s-year','email_user':'s-email-user',
    'email_pass':'s-email-pass','smtp_host':'s-smtp-host','smtp_port':'s-smtp-port',
    'twilio_sid':'s-twilio-sid','twilio_token':'s-twilio-token','twilio_from':'s-twilio-from'};
  const data={};
  Object.entries(fields).forEach(([k,id])=>{ const el=$(id); if(el) data[k]=el.value; });
  const r = await API.post('/api/admin/settings',data);
  if(r?.ok){ toast('Settings saved ✅'); applyTheme(localStorage.getItem('theme')||'light'); }
  else toast('Error saving','error');
  const th=$('s-theme')?.value||'light';
  localStorage.setItem('theme',th); applyTheme(th);
}
async function testEmail(){
  const r=await API.post('/api/admin/settings/test-email',{email:$('s-email-user')?.value});
  toast(r?.ok?'Test email sent! 📧':(r?.error||'Failed'),'info');
}
async function testWhatsApp(){
  const r=await API.post('/api/admin/settings/test-whatsapp',{});
  toast(r?.ok?'Test WhatsApp sent! 💬':(r?.error||'Failed'),'info');
}

// ── TIMETABLE ─────────────────────────────────────────────────────────────────
const TT_DAYS  = ['','Monday','Tuesday','Wednesday','Thursday','Friday'];
const TT_COLORS= ['','#ede9fe','#e0f2fe','#d1fae5','#fef3c7','#fce7f3','#fee2e2','#f0fdf4','#fff7ed'];
const TT_CBORD = ['','#7c3aed','#0284c7','#059669','#d97706','#db2777','#dc2626','#15803d','#ea580c'];
let _ttData = [], _ttSubjects = [], _ttTeachers = [];

async function loadTimetablePage(){
  const [cls, subs, teachers] = await Promise.all([
    API.get('/api/admin/classes') || [],
    API.get('/api/admin/subjects') || [],
    API.get('/api/admin/teachers') || []
  ]);
  _ttSubjects = subs || [];
  _ttTeachers = teachers || [];
  if(cls){
    $('tt-class').innerHTML = '<option value="">Select Class…</option>' +
      cls.map(c=>`<option value="${c.id}">${c.name}</option>`).join('');
  }
  $('sl-subject').innerHTML = (_ttSubjects||[]).map(s=>`<option value="${s.id}">${s.name}</option>`).join('');
  $('sl-teacher').innerHTML = '<option value="">Not assigned</option>' +
    (_ttTeachers||[]).map(t=>`<option value="${t.id}">${t.full_name}</option>`).join('');
  loadTimetable();
}

async function loadTimetable(){
  const cid = $('tt-class').value;
  const yr  = $('tt-year').value || '2025';
  const grid = $('ttGrid');
  if(!cid){
    grid.innerHTML = '<div class="card"><div class="card-bod"><div class="empty"><div class="ei">🗓️</div><h4>Select a class to view or build its timetable</h4></div></div></div>';
    return;
  }
  grid.innerHTML = '<div class="empty"><div class="ei" style="animation:spin 1s linear infinite">⏳</div><p>Loading…</p></div>';
  _ttData = await API.get(`/api/admin/timetable?class_id=${cid}&academic_year=${yr}`) || [];
  renderTimetableGrid(_ttData, cid, yr);
}

function renderTimetableGrid(slots, cid, yr){
  const grid = $('ttGrid');
  // Find all unique periods
  const periods = [...new Set(slots.map(s=>s.period))].sort((a,b)=>a-b);
  // Also find time labels from first occurrence of each period
  const periodTimes = {};
  slots.forEach(s=>{ if(!periodTimes[s.period]) periodTimes[s.period] = `${s.start_time}–${s.end_time}`; });
  // If no slots yet, show empty grid with periods 1-8
  const allPeriods = periods.length ? periods : [1,2,3,4,5,6,7,8];

  // Build lookup: day+period → slot
  const lookup = {};
  slots.forEach(s=>{ lookup[`${s.day_of_week}_${s.period}`] = s; });

  // Subject color map
  const subColorMap = {};
  (_ttSubjects||[]).forEach((s,i)=>{ subColorMap[s.id] = i % (TT_COLORS.length-1) + 1; });

  const thead = `<tr>
    <th style="background:var(--g50);width:80px;font-size:12px">Period</th>
    ${[1,2,3,4,5].map(d=>`<th style="background:var(--g50);text-align:center;min-width:130px">${TT_DAYS[d]}</th>`).join('')}
  </tr>`;

  const tbody = allPeriods.map(p=>`<tr>
    <td style="background:var(--g50);font-size:12px;font-weight:700;text-align:center;padding:8px 4px">
      <div>P${p}</div>
      <div style="font-size:10px;color:var(--g400);font-weight:400">${periodTimes[p]||''}</div>
    </td>
    ${[1,2,3,4,5].map(d=>{
      const slot = lookup[`${d}_${p}`];
      if(slot){
        const ci = subColorMap[slot.subject_id] || 1;
        return `<td style="padding:4px">
          <div style="background:${TT_COLORS[ci]};border-left:3px solid ${TT_CBORD[ci]};
            border-radius:6px;padding:7px 9px;position:relative;min-height:58px">
            <div style="font-weight:700;font-size:12px;color:${TT_CBORD[ci]}">${slot.subject_name}</div>
            <div style="font-size:11px;color:var(--g500);margin-top:2px">${slot.teacher_name||'Unassigned'}</div>
            ${slot.room?`<div style="font-size:10px;color:var(--g400);margin-top:1px">📍 ${slot.room}</div>`:''}
            <button onclick="deleteSlot(${slot.id})" title="Remove"
              style="position:absolute;top:3px;right:3px;background:none;border:none;cursor:pointer;
                font-size:12px;color:var(--g300);line-height:1" onmouseover="this.style.color='var(--red)'"
              onmouseout="this.style.color='var(--g300)'">✕</button>
          </div>
        </td>`;
      }
      return `<td style="padding:4px">
        <div onclick="quickAddSlot(${d},${p})" style="border:2px dashed var(--g200);border-radius:6px;
          min-height:58px;display:flex;align-items:center;justify-content:center;cursor:pointer;
          color:var(--g300);font-size:18px;transition:all .15s"
          onmouseover="this.style.borderColor='var(--pri)';this.style.color='var(--pri)'"
          onmouseout="this.style.borderColor='var(--g200)';this.style.color='var(--g300)'">+</div>
      </td>`;
    }).join('')}
  </tr>`).join('');

  // Period time summary
  const timeGuide = `
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
      ${allPeriods.map(p=>`<span style="font-size:11px;background:var(--g100);padding:3px 8px;border-radius:6px;color:var(--g600)">
        P${p} ${periodTimes[p]||'—'}
      </span>`).join('')}
    </div>`;

  // Subject legend
  const legend = `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
    ${(_ttSubjects||[]).filter(s=>slots.some(sl=>sl.subject_id===s.id)).map(s=>{
      const ci = subColorMap[s.id] || 1;
      return `<span style="font-size:11px;background:${TT_COLORS[ci]};border-left:3px solid ${TT_CBORD[ci]};
        padding:3px 8px;border-radius:4px;color:${TT_CBORD[ci]};font-weight:600">${s.name}</span>`;
    }).join('')}
  </div>`;

  grid.innerHTML = `
    <div class="card">
      <div class="card-hdr">
        <h3>🗓️ Weekly Timetable — ${$('tt-class').options[$('tt-class').selectedIndex]?.text||''} (${yr})</h3>
        <span class="badge badge-pri">${slots.length} slots</span>
      </div>
      <div class="card-bod" style="padding-bottom:8px">
        ${timeGuide}
        <div style="overflow-x:auto">
          <table style="width:100%;border-collapse:collapse;min-width:700px">
            <thead>${thead}</thead>
            <tbody>${tbody}</tbody>
          </table>
        </div>
        ${slots.length ? legend : ''}
      </div>
    </div>`;
}

function quickAddSlot(day, period){
  $('sl-day').value = day;
  $('sl-period').value = period;
  // Auto-fill time based on period
  const times = {1:['07:30','08:10'],2:['08:10','08:50'],3:['08:50','09:30'],
                 4:['09:50','10:30'],5:['10:30','11:10'],6:['11:10','11:50'],
                 7:['12:30','13:10'],8:['13:10','13:50']};
  if(times[period]){ $('sl-start').value=times[period][0]; $('sl-end').value=times[period][1]; }
  openModal('m-addSlot');
}

async function saveSlot(){
  const cid = $('tt-class').value;
  const yr  = $('tt-year').value || '2025';
  if(!cid){ toast('Select a class first','warn'); return; }
  const r = await API.post('/api/admin/timetable',{
    class_id: cid, academic_year: yr,
    subject_id: $('sl-subject').value,
    teacher_id: $('sl-teacher').value || null,
    day_of_week: $('sl-day').value,
    period: $('sl-period').value,
    start_time: $('sl-start').value,
    end_time: $('sl-end').value,
    room: $('sl-room').value
  });
  if(r?.ok){ toast('Slot saved ✅'); closeModal('m-addSlot'); $('sl-room').value=''; loadTimetable(); }
  else toast(r?.error||'Could not save — slot may already exist','error');
}

async function deleteSlot(id){
  const r = await API.del(`/api/admin/timetable/${id}`);
  if(r?.ok){ toast('Slot removed'); loadTimetable(); }
  else toast('Error removing slot','error');
}

async function clearTimetable(){
  const cid = $('tt-class').value; const yr = $('tt-year').value||'2025';
  if(!cid){ toast('Select a class first','warn'); return; }
  const cls = $('tt-class').options[$('tt-class').selectedIndex]?.text||'';
  if(!confirm(`Clear ALL timetable slots for ${cls}? This cannot be undone.`)) return;
  const r = await API.post('/api/admin/timetable/clear',{class_id:cid,academic_year:yr});
  if(r?.ok){ toast('Timetable cleared'); loadTimetable(); }
  else toast('Error','error');
}

function printTimetable(){
  const grid = $('ttGrid');
  if(!grid?.innerHTML){ toast('Load a timetable first','warn'); return; }
  const w = window.open('','_blank');
  w.document.write(`<!DOCTYPE html><html><head><title>Timetable</title>
    <style>body{font-family:Arial,sans-serif;padding:20px}
    table{width:100%;border-collapse:collapse}
    th,td{border:1px solid #ddd;padding:8px;font-size:12px}
    th{background:#f5f3ff;font-weight:700}
    @media print{button{display:none}}</style></head>
    <body>${grid.innerHTML}<br><button onclick="window.print()">🖨️ Print</button></body></html>`);
  w.document.close();
}

// ── INIT ──────────────────────────────────────────────────────────────────────
loadDashboard();
loadStudents();   // preload class selects
loadClasses();
loadSubjects();
</script>
</body></html>"""

ADMIN_HTML = ADMIN_HTML.replace('{{ GLOBAL }}', GLOBAL)

# ─────────────────────────────────────────────────────────────────────────────
# TEACHER PAGE (full SPA)
# ─────────────────────────────────────────────────────────────────────────────
TEACHER_HTML = """<!DOCTYPE html><html lang="en"><head>
<title>Teacher Portal – {{ school }}</title>
{{ GLOBAL }}
<style>
.att-row{display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid var(--g100)}
.att-name{flex:1;font-weight:600}
</style>
</head><body>
<div class="sb-overlay" id="sbOverlay" onclick="closeSb()"></div>
<div class="layout">

<!-- ══ SIDEBAR ══════════════════════════════════════════════════════════════ -->
<div class="sidebar" id="sidebar">
  <div class="sb-logo">
    <div style="font-size:28px;margin-bottom:8px">🏫</div>
    <h1>Teacher Portal</h1>
    <p id="sbTeacherName">{{ name }}</p>
  </div>
  <div class="sb-label">Main Menu</div>
  <button class="nav-btn active" data-sec="dashboard" onclick="sec(this)">
    <span class="ni">📊</span>Dashboard</button>
  <button class="nav-btn" data-sec="classes" onclick="sec(this)">
    <span class="ni">🏛️</span>My Classes</button>
  <button class="nav-btn" data-sec="students" onclick="sec(this)">
    <span class="ni">👨‍🎓</span>My Students</button>
  <button class="nav-btn" data-sec="attendance" onclick="sec(this)">
    <span class="ni">📋</span>Attendance</button>
  <button class="nav-btn" data-sec="grades" onclick="sec(this)">
    <span class="ni">✏️</span>Enter Grades</button>
  <button class="nav-btn" data-sec="gradebook" onclick="sec(this)">
    <span class="ni">📊</span>Grade Book</button>
  <button class="nav-btn" data-sec="mytimetable" onclick="sec(this)">
    <span class="ni">🗓️</span>My Timetable</button>
  <div class="sb-divider"></div>
  <div class="sb-label">Other</div>
  <button class="nav-btn" data-sec="homework" onclick="sec(this)">
    <span class="ni">📝</span>Homework</button>
  <button class="nav-btn" data-sec="alerts" onclick="sec(this)">
    <span class="ni">🔔</span>Attendance Alerts</button>
  <div class="sb-divider"></div>
  <button class="nav-btn" data-sec="announcements" onclick="sec(this)">
    <span class="ni">📢</span>Announcements</button>
  <button class="nav-btn" data-sec="profile" onclick="sec(this)">
    <span class="ni">👤</span>My Profile</button>
  <div class="sb-divider"></div>
  <a href="/api/logout" class="nav-btn"><span class="ni">🚪</span>Sign Out</a>
</div>

<!-- ══ MAIN ═════════════════════════════════════════════════════════════════ -->
<div class="main">
<div id="offlineBar" style="display:none;background:#dc2626;color:#fff;padding:8px 20px;font-size:13px;font-weight:600;align-items:center;gap:8px;justify-content:center">
  📡 You are offline — changes may not be saved
</div>
<div class="topbar">
  <div style="display:flex;align-items:center;gap:12px">
    <button onclick="toggleSb()" style="background:none;border:none;font-size:22px;cursor:pointer;color:var(--g500)">☰</button>
    <div style="font-size:15px;font-weight:800;color:var(--g900)" id="pageTitle">Dashboard</div>
  </div>
  <div style="display:flex;align-items:center;gap:10px">
    <button id="themeBtn" onclick="toggleTheme()" style="background:none;border:none;font-size:20px;cursor:pointer" title="Toggle dark mode">🌙</button>
    <div class="avatar" style="width:36px;height:36px;background:var(--grn)">{{ name[0] }}</div>
    <span style="font-size:13px;font-weight:600" id="topTeacher">{{ name }}</span>
  </div>
</div>

<div class="main-body">

<!-- ─── DASHBOARD ─────────────────────────────────────────────────────────── -->
<div class="sec active" id="sec-dashboard">
  <div class="pg-hdr">
    <div class="pg-hdr-left">
      <h2>📊 Dashboard</h2>
      <p>Welcome back, <strong>{{ name }}</strong>. Here's your overview for today.</p>
    </div>
  </div>
  <div class="stat-grid" id="tStatsRow"></div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px">
    <div class="card">
      <div class="card-hdr"><h3>📝 Recent Grades Entered</h3>
        <button class="btn btn-sm btn-pri-out" onclick="sec(document.querySelector('[data-sec=grades]'))">Enter Grades →</button>
      </div>
      <div id="tRecentGrades" style="padding:0"></div>
    </div>
    <div class="card">
      <div class="card-hdr"><h3>📢 Latest Announcements</h3></div>
      <div id="tAnnouncements" style="padding:0"></div>
    </div>
  </div>
  <div class="card">
    <div class="card-hdr"><h3>🏛️ My Assigned Classes &amp; Subjects</h3>
      <button class="btn btn-sm btn-pri-out" onclick="sec(document.querySelector('[data-sec=classes]'))">View All →</button>
    </div>
    <div id="dashClassList" style="padding:0"></div>
  </div>
</div>

<!-- ─── MY CLASSES ────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-classes">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>🏛️ My Classes</h2><p>Subjects and classes assigned to you by admin</p></div>
  </div>
  <div id="myClassGrid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px"></div>
</div>

<!-- ─── ATTENDANCE ────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-attendance">
  <div class="pg-hdr"><div class="pg-hdr-left"><h2>📋 Attendance Register</h2></div></div>
  <div class="card" style="margin-bottom:20px">
    <div class="card-bod">
      <div class="filter-bar">
        <select id="att-class" onchange="loadAttendance()" style="min-width:200px"></select>
        <input type="date" id="att-date" style="width:160px" onchange="loadAttendance()">
        <button class="voice-btn idle" id="voiceAttBtn" onclick="toggleVoiceAtt()" title="Voice attendance">🎙️</button>
        <button class="btn btn-grn" onclick="saveAttendance()">💾 Save Register</button>
        <button class="btn btn-ghost" onclick="markAll('present')">✅ All Present</button>
        <button class="btn btn-ghost" onclick="markAll('absent')">❌ All Absent</button>
      </div>
      <div id="voiceAttStatus" style="font-size:13px;color:var(--red);margin-top:6px;font-weight:600;display:none"></div>
    </div>
  </div>
  <div class="card" style="margin-bottom:20px">
    <div class="card-hdr"><h3 id="attRegTitle">📝 Register</h3></div>
    <div id="attList"></div>
  </div>
  <div class="card">
    <div class="card-hdr"><h3>📊 Attendance Summary</h3></div>
    <div class="tbl-wrap">
      <table><thead><tr><th>Student</th><th>Present</th><th>Absent</th>
        <th>Late</th><th>Total Days</th><th>Attendance %</th></tr></thead>
        <tbody id="attSumTbody"></tbody></table>
    </div>
  </div>
</div>

<!-- ─── GRADES ────────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-grades">
  <div class="pg-hdr"><div class="pg-hdr-left"><h2>✏️ Enter Grades</h2></div></div>
  <div class="card" style="margin-bottom:20px">
    <div class="card-bod">
      <div class="filter-bar">
        <select id="g-class" onchange="onGradeClassChange()" style="min-width:200px"></select>
        <select id="g-subject" onchange="loadGradeStudents()" style="min-width:220px"></select>
        <select id="g-term" onchange="loadGradeStudents()" style="min-width:200px">
          <option>Mid Term 1</option><option selected>End of Term 1</option>
          <option>Mid Term 2</option><option>End of Term 2</option>
          <option>Mid Term 3</option><option>End of Term 3</option>
        </select>
      </div>
    </div>
  </div>

  <!-- Grade entry method tabs -->
  <div class="tabs">
    <button class="tab-btn active" onclick="switchGradeTab('manual',this)">✏️ Manual</button>
    <button class="tab-btn" onclick="switchGradeTab('voice',this)">🎙️ Voice</button>
    <button class="tab-btn" onclick="switchGradeTab('scan',this)">📷 Scan OCR</button>
    <button class="tab-btn" onclick="switchGradeTab('canvas',this)">🖊️ Handwriting</button>
  </div>

  <!-- Manual -->
  <div id="gt-manual">
    <div class="card">
      <div class="card-hdr"><h3>✏️ Manual Entry</h3>
        <button class="btn btn-grn" onclick="saveGrades()">💾 Save Grades</button></div>
      <div class="tbl-wrap">
        <table><thead><tr><th>#</th><th>Student Name</th><th>Score (0–100)</th><th>Grade</th><th>Comment</th></tr></thead>
          <tbody id="gradeTbody"></tbody></table>
      </div>
    </div>
  </div>

  <!-- Voice -->
  <div id="gt-voice" style="display:none">
    <div class="card">
      <div class="card-hdr"><h3>🎙️ Voice Grade Entry</h3></div>
      <div class="card-bod" style="text-align:center;padding:36px">
        <p style="color:var(--g500);margin-bottom:24px;max-width:420px;margin-left:auto;margin-right:auto">
          Say <strong>"[student name] [score]"</strong> e.g. <em>"Amara eighty-five"</em> or <em>"Chisomo 92"</em></p>
        <button class="voice-btn idle" id="voiceGradeBtn" onclick="toggleVoiceGrades()"
          style="width:72px;height:72px;font-size:28px;margin:0 auto 20px">🎙️</button>
        <div id="voiceGradeStatus" style="font-size:13px;color:var(--g500);margin-bottom:16px">Click mic to start</div>
        <div id="voiceGradeLog" style="max-height:180px;overflow-y:auto;text-align:left;max-width:500px;margin:0 auto"></div>
      </div>
    </div>
    <div class="card" style="margin-top:16px">
      <div class="card-hdr"><h3>Captured Grades</h3>
        <button class="btn btn-grn" onclick="saveGrades()">💾 Save All</button></div>
      <div class="tbl-wrap">
        <table><thead><tr><th>Student</th><th>Score</th><th>Grade</th></tr></thead>
          <tbody id="voiceGradeTbody"></tbody></table>
      </div>
    </div>
  </div>

  <!-- Scan -->
  <div id="gt-scan" style="display:none">
    <div class="card">
      <div class="card-hdr"><h3>📷 Scan Mark Sheet (OCR)</h3></div>
      <div class="card-bod">
        <p style="color:var(--g500);margin-bottom:18px">
          Take a photo of the mark sheet or upload an image. The system will extract names and scores using OCR.</p>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px">
          <button class="btn btn-pri" onclick="startCamera()">📷 Open Camera</button>
          <label class="btn btn-ghost" style="cursor:pointer">
            📁 Upload Image<input type="file" accept="image/*" style="display:none" onchange="handleUpload(event)"></label>
          <button class="btn btn-grn" id="captureBtn" style="display:none" onclick="captureAndScan()">✅ Capture &amp; Scan</button>
          <button class="btn btn-ghost" id="stopCamBtn" style="display:none" onclick="stopCamera()">⏹ Stop</button>
        </div>
        <div id="camBox" style="display:none;margin-bottom:16px;border-radius:var(--r12);overflow:hidden;background:#000">
          <video id="camFeed" autoplay playsinline style="width:100%;max-height:320px;display:block"></video>
          <canvas id="snapCanvas" style="display:none"></canvas>
        </div>
        <div id="uploadPreview" style="margin-bottom:16px"></div>
        <div id="scanResults" style="display:none">
          <h4 style="font-size:13px;font-weight:800;margin-bottom:12px">📝 Detected Grades — review and apply:</h4>
          <div class="tbl-wrap"><table><thead><tr><th>Student</th><th>Score</th><th>Apply?</th></tr></thead>
            <tbody id="scanTbody"></tbody></table></div>
          <button class="btn btn-pri" style="margin-top:14px" onclick="applyScan()">✅ Apply to Grade Sheet</button>
        </div>
        <pre id="ocrText" style="display:none;background:var(--g50);padding:12px;border-radius:var(--r8);
          font-size:11px;max-height:120px;overflow-y:auto;margin-top:12px;white-space:pre-wrap"></pre>
      </div>
    </div>
  </div>

  <!-- Canvas / Handwriting -->
  <div id="gt-canvas" style="display:none">
    <div class="card">
      <div class="card-hdr"><h3>🖊️ Handwriting Canvas</h3>
        <div style="display:flex;gap:8px">
          <button class="btn btn-ghost btn-sm" onclick="clearCanvas()">🗑 Clear</button>
        </div>
      </div>
      <div class="canv-tools">
        <label style="font-size:12px;font-weight:700">Pen size:</label>
        <input type="range" id="penSize" min="1" max="20" value="3" style="width:90px">
        <label style="font-size:12px;font-weight:700">Colour:</label>
        <input type="color" id="penColor" value="#1e1b4b" style="width:34px;height:28px;padding:2px;border-radius:6px">
        <button class="btn btn-sm btn-ghost" onclick="pm='pen'">✏️ Pen</button>
        <button class="btn btn-sm btn-ghost" onclick="pm='eraser'">🧹 Eraser</button>
      </div>
      <div style="background:#fff7ed;padding:10px 16px;font-size:12px;color:var(--amb);font-weight:600;border-bottom:1px solid var(--g100)">
        ✍️ Write grades here for visual reference, then transfer them to the Manual tab to save.
      </div>
      <canvas id="handCanvas" style="display:block;width:100%;cursor:crosshair;touch-action:none;background:#fff"></canvas>
    </div>
  </div>
</div>

<!-- ─── GRADE BOOK ─────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-gradebook">
  <div class="pg-hdr"><div class="pg-hdr-left"><h2>📊 Grade Book</h2><p>Complete grade overview for your class</p></div></div>
  <div class="filter-bar">
    <select id="gb-class" onchange="loadGradeBook()" style="min-width:200px"></select>
    <select id="gb-term" onchange="loadGradeBook()" style="min-width:200px">
      <option>Mid Term 1</option><option selected>End of Term 1</option>
      <option>Mid Term 2</option><option>End of Term 2</option>
      <option>Mid Term 3</option><option>End of Term 3</option>
    </select>
  </div>
  <div class="card">
    <div class="tbl-wrap" id="gbTableWrap">
      <table><thead id="gbHead"></thead><tbody id="gbBody"></tbody></table>
    </div>
  </div>
</div>

<!-- ─── MY STUDENTS ─────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-students">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>👨‍🎓 My Students</h2><p>Students in your assigned classes</p></div>
  </div>
  <div class="filter-bar" style="margin-bottom:18px">
    <select id="my-stu-class" onchange="loadMyStudents()" style="min-width:200px"></select>
    <input id="my-stu-search" placeholder="🔍 Search by name or admission number…"
      oninput="renderMyStudents()" style="max-width:300px">
  </div>
  <div class="card">
    <div class="tbl-wrap">
      <table><thead><tr><th>Adm #</th><th>Name</th><th>Gender</th><th>Class</th>
        <th>Parent</th><th>Parent Phone</th></tr></thead>
        <tbody id="myStuTbody"></tbody></table>
    </div>
  </div>
</div>

<!-- ─── ANNOUNCEMENTS ──────────────────────────────────────────────────────── -->
<div class="sec" id="sec-announcements">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>📢 Announcements</h2><p>Messages from admin and school management</p></div>
    <button class="btn btn-ghost" onclick="loadAnnouncements()">🔄 Refresh</button>
  </div>
  <div id="announcementsList">
    <div class="empty"><div class="ei">📢</div><h4>Loading…</h4></div>
  </div>
</div>

<!-- ─── MY TIMETABLE ─────────────────────────────────────────────────────── -->
<div class="sec" id="sec-mytimetable">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>🗓️ My Timetable</h2><p>Your weekly teaching schedule</p></div>
    <button class="btn btn-ghost" onclick="loadMyTimetable()">🔄 Refresh</button>
  </div>
  <div id="myTtGrid"></div>
</div>

<!-- ─── HOMEWORK ──────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-homework">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>📝 Homework</h2><p>Assign homework and track submissions</p></div>
    <button class="btn btn-pri" onclick="openModal('m-addHomework')">➕ New Assignment</button>
  </div>
  <div id="homeworkList"></div>
</div>

<!-- ─── ATTENDANCE ALERTS ─────────────────────────────────────────────────── -->
<div class="sec" id="sec-alerts">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>🔔 Attendance Alerts</h2><p>Students below threshold — notify parents instantly</p></div>
  </div>
  <div class="filter-bar">
    <select id="alert-class" style="min-width:200px"></select>
    <input id="alert-thresh" type="number" value="80" min="1" max="100" style="max-width:120px" placeholder="Min %">
    <button class="btn btn-pri" onclick="loadAlerts()">🔍 Check Alerts</button>
  </div>
  <div id="alertsList"></div>
</div>

<!-- ─── MY PROFILE ─────────────────────────────────────────────────────────── -->
<div class="sec" id="sec-profile">
  <div class="pg-hdr">
    <div class="pg-hdr-left"><h2>👤 My Profile</h2><p>Your account details and assignments</p></div>
  </div>
  <div class="card">
    <div class="card-bod" id="profileCard">
      <div class="empty"><div class="ei">👤</div><h4>Loading…</h4></div>
    </div>
  </div>
</div>

</div><!-- main-body -->
</div><!-- main -->
</div><!-- layout -->

<script>
let myAssignments=[], currentStudents=[], gradeMap={}, attMap={};
let voiceRec=null, voiceAttActive=false, voiceGradeActive=false;
let camStream=null; let pm='pen'; let isDrawing=false, lx=0, ly=0;
let _initDone=false;

// ── Sidebar ───────────────────────────────────────────────────────────────────
function sec(btn){
  const id=btn.dataset.sec;
  $$('.sec').forEach(s=>s.classList.remove('active'));
  $$('.nav-btn').forEach(b=>b.classList.remove('active'));
  const secEl=$('sec-'+id);
  if(!secEl){ toast('Section not found: '+id,'error'); return; }
  secEl.classList.add('active'); btn.classList.add('active');
  $('pageTitle').textContent=btn.querySelector('.ni')?btn.textContent.trim().replace(btn.querySelector('.ni').textContent,'').trim():btn.textContent.trim();
  closeSb();
  // Only fire data loads after init() has populated selects
  if(!_initDone) return;
  if(id==='dashboard') loadDashboard();
  else if(id==='classes') renderMyClasses();
  else if(id==='attendance'){ const d=$('att-date'); if(d) d.valueAsDate=new Date(); loadAttendance(); }
  else if(id==='grades'){ onGradeClassChange(); }
  else if(id==='gradebook') loadGradeBook();
  else if(id==='students') loadMyStudents();
  else if(id==='profile') loadProfile();
  else if(id==='announcements') loadAnnouncements();
  else if(id==='mytimetable') loadMyTimetable();
  else if(id==='homework') loadHomework();
  else if(id==='alerts') initAlerts();
}
function toggleSb(){$('sidebar').classList.toggle('open');$('sbOverlay').classList.toggle('open');}
function closeSb(){$('sidebar').classList.remove('open');$('sbOverlay').classList.remove('open');}

// ── Grade tab switcher ────────────────────────────────────────────────────────
function switchGradeTab(name,btn){
  ['manual','voice','scan','canvas'].forEach(t=>$('gt-'+t).style.display=t===name?'block':'none');
  $$('.tab-btn').forEach(b=>b.classList.remove('active')); btn.classList.add('active');
  if(name==='canvas') initCanvas();
}

// ── MY TIMETABLE ─────────────────────────────────────────────────────────────
const T_DAYS   = ['','Monday','Tuesday','Wednesday','Thursday','Friday'];
const T_COLORS = ['','#ede9fe','#e0f2fe','#d1fae5','#fef3c7','#fce7f3','#fee2e2','#f0fdf4','#fff7ed'];
const T_CBORD  = ['','#7c3aed','#0284c7','#059669','#d97706','#db2777','#dc2626','#15803d','#ea580c'];

async function loadMyTimetable(){
  const el = $('myTtGrid');
  el.innerHTML = '<div class="empty"><div class="ei" style="animation:spin 1s linear infinite">⏳</div><p>Loading…</p></div>';
  const slots = await API.get('/api/teacher/timetable') || [];
  if(!slots.length){
    el.innerHTML = '<div class="card"><div class="card-bod"><div class="empty"><div class="ei">🗓️</div><h4>No timetable assigned yet</h4><p>Ask admin to build your timetable</p></div></div></div>';
    return;
  }
  const today = new Date().getDay(); // 0=Sun,1=Mon…5=Fri

  // Build lookup
  const lookup = {};
  const periods = [...new Set(slots.map(s=>s.period))].sort((a,b)=>a-b);
  const periodTimes = {};
  const subColorMap = {};
  let colorIdx = 1;
  slots.forEach(s=>{
    lookup[`${s.day_of_week}_${s.period}`] = s;
    if(!periodTimes[s.period]) periodTimes[s.period] = `${s.start_time}–${s.end_time}`;
    if(!subColorMap[s.subject_id]){ subColorMap[s.subject_id] = colorIdx % (T_COLORS.length-1) + 1; colorIdx++; }
  });
  const allPeriods = periods.length ? periods : [1,2,3,4,5,6,7,8];

  // Today's schedule highlight
  const todaySlots = slots.filter(s=>s.day_of_week===today).sort((a,b)=>a.period-b.period);
  const todayHtml = todaySlots.length ? `
    <div class="card" style="margin-bottom:16px;border-left:4px solid var(--pri)">
      <div class="card-hdr"><h3>📅 Today — ${T_DAYS[today]}</h3>
        <span class="badge badge-pri">${todaySlots.length} periods</span></div>
      <div style="display:flex;flex-wrap:wrap;gap:10px;padding:12px 16px">
        ${todaySlots.map(s=>{
          const ci = subColorMap[s.subject_id]||1;
          return `<div style="background:${T_COLORS[ci]};border-left:3px solid ${T_CBORD[ci]};border-radius:8px;padding:10px 14px;min-width:140px">
            <div style="font-size:11px;color:${T_CBORD[ci]};font-weight:700">P${s.period} · ${s.start_time}–${s.end_time}</div>
            <div style="font-weight:800;font-size:14px;margin-top:3px">${s.subject_name}</div>
            <div style="font-size:12px;color:var(--g500);margin-top:2px">${s.class_name}</div>
            ${s.room?`<div style="font-size:11px;color:var(--g400);margin-top:2px">📍 ${s.room}</div>`:''}
          </div>`;
        }).join('')}
      </div>
    </div>` : (today>=1&&today<=5 ? '<div class="card" style="margin-bottom:16px"><div class="card-bod"><div class="empty" style="padding:16px"><div class="ei">☀️</div><p>No classes scheduled for today</p></div></div></div>' : '');

  const thead = `<tr>
    <th style="background:var(--g50);width:72px;font-size:12px">Period</th>
    ${[1,2,3,4,5].map(d=>`<th style="text-align:center;min-width:120px;background:${d===today?'var(--pri-xl)':'var(--g50)'}">
      ${T_DAYS[d]}${d===today?' <span style="font-size:10px;color:var(--pri)">(Today)</span>':''}
    </th>`).join('')}
  </tr>`;

  const tbody = allPeriods.map(p=>`<tr>
    <td style="background:var(--g50);font-size:11px;font-weight:700;text-align:center;padding:6px 4px">
      <div>P${p}</div>
      <div style="font-size:10px;color:var(--g400);font-weight:400">${periodTimes[p]||''}</div>
    </td>
    ${[1,2,3,4,5].map(d=>{
      const slot = lookup[`${d}_${p}`];
      const isTodayCol = d===today;
      if(slot){
        const ci = subColorMap[slot.subject_id]||1;
        return `<td style="padding:3px;background:${isTodayCol?'rgba(79,70,229,.04)':''}">
          <div style="background:${T_COLORS[ci]};border-left:3px solid ${T_CBORD[ci]};border-radius:6px;padding:7px 9px;min-height:54px">
            <div style="font-weight:700;font-size:12px;color:${T_CBORD[ci]}">${slot.subject_name}</div>
            <div style="font-size:11px;color:var(--g500);margin-top:2px">${slot.class_name}</div>
            ${slot.room?`<div style="font-size:10px;color:var(--g400);margin-top:1px">📍 ${slot.room}</div>`:''}
          </div>
        </td>`;
      }
      return `<td style="background:${isTodayCol?'rgba(79,70,229,.03)':''}"><div style="min-height:54px"></div></td>`;
    }).join('')}
  </tr>`).join('');

  el.innerHTML = todayHtml + `
    <div class="card">
      <div class="card-hdr"><h3>📅 Full Week Schedule</h3>
        <span class="badge badge-pri">${slots.length} total periods</span></div>
      <div class="card-bod" style="padding:0">
        <div style="overflow-x:auto">
          <table style="width:100%;border-collapse:collapse;min-width:640px">
            <thead>${thead}</thead>
            <tbody>${tbody}</tbody>
          </table>
        </div>
      </div>
    </div>`;
}

// ── HOMEWORK ─────────────────────────────────────────────────────────────────
async function loadHomework(){
  const hw = await API.get('/api/teacher/homework') || [];
  const hwEl = $('homeworkList');
  if(!hwEl) return;
  // Populate hw-class select
  const cls = [...new Map(myAssignments.map(a=>[a.class_id,a])).values()];
  const hwCls = $('hw-class');
  if(hwCls) hwCls.innerHTML = cls.map(a=>`<option value="${a.class_id}">${a.class_name}</option>`).join('');
  onHwClassChange();
  if(!hw.length){
    hwEl.innerHTML='<div class="card"><div class="card-bod"><div class="empty"><div class="ei">📝</div><h4>No assignments yet</h4><p>Click "+ New Assignment" to create one</p></div></div></div>';
    return;
  }
  hwEl.innerHTML = hw.map(h=>`
    <div class="card" style="margin-bottom:14px">
      <div class="card-hdr">
        <div>
          <div style="font-weight:800;font-size:15px">${h.title}</div>
          <div style="font-size:12px;color:var(--g500);margin-top:3px">
            <span class="badge badge-sky">${h.class_name}</span>
            <span class="badge badge-pri" style="margin-left:6px">📚 ${h.subject_name}</span>
            ${h.due_date?`<span style="margin-left:8px">📅 Due: ${h.due_date}</span>`:''}
            ${h.max_marks?`<span style="margin-left:8px">🏅 ${h.max_marks} marks</span>`:''}
          </div>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn btn-sm btn-ghost" onclick="viewSubmissions(${h.id},'${h.title.replace(/'/g,"\\'")}')">📋 Submissions (${h.submitted_count||0}/${h.total_students||0})</button>
          <button class="btn btn-sm btn-red" onclick="deleteHomework(${h.id},this)">🗑</button>
        </div>
      </div>
      ${h.description?`<div class="card-bod" style="padding-top:0;font-size:13px;color:var(--g600)">${h.description}</div>`:''}
    </div>`).join('');
}
function onHwClassChange(){
  const cid = $('hw-class')?.value;
  const subs = myAssignments.filter(a=>String(a.class_id)===String(cid));
  const hwSub = $('hw-subject');
  if(hwSub) hwSub.innerHTML = subs.map(a=>`<option value="${a.subject_id}">${a.subject_name}</option>`).join('');
}
async function addHomework(){
  const r = await API.post('/api/teacher/homework',{
    class_id:$('hw-class').value, subject_id:$('hw-subject').value,
    title:$('hw-title').value, description:$('hw-desc').value,
    due_date:$('hw-due').value, max_marks:parseInt($('hw-marks').value)||0
  });
  if(r?.ok){ toast('Assignment added! 📝'); closeModal('m-addHomework');
    $('hw-title').value=''; $('hw-desc').value=''; loadHomework(); }
  else toast(r?.error||'Error','error');
}
async function deleteHomework(id,btn){
  if(!confirm('Delete this assignment?')) return;
  btn.disabled=true;
  const r = await API.del(`/api/teacher/homework/${id}`);
  if(r?.ok){ toast('Deleted'); loadHomework(); }
  else { toast('Error','error'); btn.disabled=false; }
}
async function viewSubmissions(hwId, title){
  openModal('m-hwSubmissions');
  $('hwSubTitle').textContent = `📋 ${title} — Submissions`;
  $('hwSubBody').innerHTML = '<div class="empty"><div class="ei" style="animation:spin 1s linear infinite">⏳</div><p>Loading…</p></div>';
  const subs = await API.get(`/api/teacher/homework/${hwId}/submissions`) || [];
  if(!subs.length){ $('hwSubBody').innerHTML='<div class="empty"><div class="ei">📋</div><p>No submissions yet</p></div>'; return; }
  $('hwSubBody').innerHTML = `<table style="width:100%;border-collapse:collapse">
    <thead><tr style="background:var(--g50)"><th style="padding:9px 12px;text-align:left">Student</th><th style="padding:9px 12px;text-align:center">Status</th><th style="padding:9px 12px;text-align:center">Marks</th><th style="padding:9px 12px">Note</th><th style="padding:9px 12px">Action</th></tr></thead>
    <tbody>${subs.map(s=>`<tr style="border-bottom:1px solid var(--g100)">
      <td style="padding:9px 12px;font-weight:600">${s.student_name}</td>
      <td style="padding:9px 12px;text-align:center">
        <select onchange="updateSubmission(${s.id},this.value,null)" style="font-size:12px;padding:4px 8px;width:auto">
          ${['pending','submitted','graded','missing'].map(st=>`<option value="${st}" ${s.status===st?'selected':''}>${st}</option>`).join('')}
        </select>
      </td>
      <td style="padding:9px 12px;text-align:center">
        <input type="number" value="${s.marks||''}" placeholder="—" style="width:60px;padding:4px;text-align:center;font-size:12px"
          onchange="updateSubmission(${s.id},null,this.value)">
      </td>
      <td style="padding:9px 12px;font-size:12px;color:var(--g500)">${s.note||'—'}</td>
      <td style="padding:9px 12px"><button class="btn btn-sm btn-ghost" onclick="updateSubmission(${s.id},null,null,this)">💾</button></td>
    </tr>`).join('')}</tbody>
  </table>`;
}
async function updateSubmission(id, status, marks, btn){
  const body={};
  if(status) body.status=status;
  if(marks!=null&&marks!=='') body.marks=parseInt(marks);
  await API.put(`/api/teacher/homework/submission/${id}`,body);
  if(btn){ btn.textContent='✅'; setTimeout(()=>btn.textContent='💾',1200); }
}

// ── ATTENDANCE ALERTS ─────────────────────────────────────────────────────────
function initAlerts(){
  const cls = [...new Map(myAssignments.map(a=>[a.class_id,a])).values()];
  const sel = $('alert-class');
  if(sel) sel.innerHTML = cls.map(a=>`<option value="${a.class_id}">${a.class_name}</option>`).join('');
}
async function loadAlerts(){
  const cid = $('alert-class').value;
  const thresh = parseFloat($('alert-thresh').value)||80;
  if(!cid){ toast('Select a class first','warn'); return; }
  const data = await API.get(`/api/teacher/attendance/alerts/${cid}?threshold=${thresh}`) || [];
  const el = $('alertsList');
  if(!data.length){
    el.innerHTML='<div class="card"><div class="card-bod"><div class="empty"><div class="ei">✅</div><h4>No alerts — all students above '+thresh+'%</h4></div></div></div>';
    return;
  }
  el.innerHTML = `<div class="card">
    <div class="card-hdr"><h3>⚠️ ${data.length} students below ${thresh}% attendance</h3></div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Student</th><th>Attendance</th><th>Absences</th><th>Parent</th><th>Contact</th><th>Notify</th></tr></thead>
      <tbody>${data.map(s=>`<tr>
        <td><strong>${s.student_name}</strong></td>
        <td><span style="font-weight:800;color:${s.rate<60?'var(--red)':'var(--amb)'}">${s.rate}%</span></td>
        <td style="text-align:center">${s.absences} / ${s.total} days</td>
        <td>${s.parent_name||'—'}</td>
        <td style="font-size:12px">${s.parent_whatsapp||s.parent_phone||'—'}</td>
        <td><button class="btn btn-sm btn-grn" onclick="notifyParent(${s.student_id},this)"
          ${!(s.parent_whatsapp||s.parent_phone)?'disabled title="No number on record"':''}>
          💬 WhatsApp</button></td>
      </tr>`).join('')}
      </tbody>
    </table></div>
  </div>`;
}
async function notifyParent(sid, btn){
  btn.disabled=true; btn.textContent='⏳';
  const r = await API.post('/api/teacher/attendance/notify',{student_id:sid});
  btn.textContent = r?.ok ? '✅ Sent' : '❌ Failed';
  if(!r?.ok) toast(r?.error||'Could not send notification','error');
  else toast('Parent notified via WhatsApp ✅');
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function init(){
  myAssignments = await API.get('/api/teacher/assignments') || [];
  _initDone = true;
  populateSelects();
  loadDashboard();
}

// ── DASHBOARD ─────────────────────────────────────────────────────────────────
async function loadDashboard(){
  const d = await API.get('/api/teacher/dashboard'); if(!d) return;
  const defs = [
    {ic:'🏛️',val:d.classes,lbl:'My Classes',bg:'#ede9fe',ic_bg:'var(--pri)'},
    {ic:'📚',val:d.subjects,lbl:'My Subjects',bg:'#e0f2fe',ic_bg:'var(--sky)'},
    {ic:'👨‍🎓',val:d.students,lbl:'My Students',bg:'#d1fae5',ic_bg:'var(--grn)'},
    {ic:'📈',val:d.grades_entered,lbl:'Grades Entered',bg:'#fef3c7',ic_bg:'var(--amb)'},
    {ic:'📋',val:d.att_today,lbl:"Today's Attendance",bg:'#fce7f3',ic_bg:'var(--pnk)'},
  ];
  const statsEl=$('tStatsRow'); if(!statsEl) return;
  statsEl.innerHTML = defs.map(def=>`
    <div class="stat-card">
      <div class="stat-ic" style="background:${def.bg};color:${def.ic_bg}">${def.ic}</div>
      <div class="stat-inf"><div class="val">${def.val}</div><div class="lbl">${def.lbl}</div></div>
    </div>`).join('');

  const rg=$('tRecentGrades'); if(rg) rg.innerHTML = d.recent_grades.length
    ? `<table><tbody>${d.recent_grades.map(g=>`<tr>
        <td><strong>${g.student_name}</strong></td>
        <td style="font-size:12px;color:var(--g500)">${g.subject_name}</td>
        <td>${gradeChip(g.score)}</td>
        <td style="font-size:11px;color:var(--g400)">${fmtDate(g.entered_at)}</td>
      </tr>`).join('')}</tbody></table>`
    : '<div class="empty" style="padding:32px"><div class="ei">📝</div><p>No grades entered yet</p></div>';

  const ta=$('tAnnouncements'); if(ta) ta.innerHTML = d.announcements.length
    ? d.announcements.map(a=>`
        <div style="padding:14px 18px;border-bottom:1px solid var(--g100)">
          <div style="font-weight:700;font-size:14px;margin-bottom:3px">${a.title}</div>
          <div style="font-size:13px;color:var(--g700);margin-bottom:5px">${a.body}</div>
          <div style="font-size:11px;color:var(--g400)">${a.author||'Admin'} · ${fmtDate(a.created_at)}</div>
        </div>`).join('')
    : '<div class="empty" style="padding:32px"><div class="ei">📢</div><p>No announcements yet</p></div>';

  const dc=$('dashClassList'); if(dc) dc.innerHTML = myAssignments.length
    ? `<table><tbody>${myAssignments.map((a,i)=>`<tr>
        <td><strong>${a.class_name}</strong></td>
        <td><span class="badge badge-pri">📚 ${a.subject_name}</span></td>
        <td><span class="badge badge-grn">👨‍🎓 ${a.student_count} students</span></td>
        <td><button class="btn btn-sm btn-pri-out" onclick="quickNav(${i})">Enter Grades →</button></td>
      </tr>`).join('')}</tbody></table>`
    : '<div class="empty" style="padding:32px"><div class="ei">📭</div><h4>No classes assigned yet</h4></div>';
}

function renderMyClasses(){
  const grid = $('myClassGrid');
  if(!grid) return;
  if(!myAssignments.length){
    grid.innerHTML='<div class="empty" style="grid-column:1/-1"><div class="ei">📭</div><h4>No Classes Assigned</h4><p>Ask admin to assign subjects to you</p></div>';
    return;
  }
  grid.innerHTML = myAssignments.map((a,i)=>`
    <div onclick="quickNav(${i})" style="background:#fff;border-radius:16px;padding:22px;border:1.5px solid var(--g200);
      cursor:pointer;transition:all .2s;box-shadow:var(--sh)"
      onmouseover="this.style.borderColor='var(--pri)';this.style.transform='translateY(-3px)';this.style.boxShadow='var(--sh-md)'"
      onmouseout="this.style.borderColor='var(--g200)';this.style.transform='';this.style.boxShadow='var(--sh)'">
      <div style="font-size:32px;margin-bottom:10px">🏛️</div>
      <div style="font-size:16px;font-weight:800;color:var(--g900);margin-bottom:4px">${a.class_name}</div>
      <div style="font-size:13px;font-weight:700;color:var(--pri);margin-bottom:12px">📚 ${a.subject_name}</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <span class="badge badge-grn">👨‍🎓 ${a.student_count} students</span>
        <span class="badge badge-pri">Std ${a.grade_level}</span>
      </div>
      <div style="margin-top:14px;font-size:12px;color:var(--g400);font-weight:500">Click to enter grades →</div>
    </div>`).join('');
}

function quickNav(i){
  const a=myAssignments[i];
  $('g-class').value=a.class_id;
  onGradeClassChange();
  setTimeout(()=>{ $('g-subject').value=a.subject_id; loadGradeStudents(); },80);
  const btn=document.querySelector('[data-sec="grades"]');
  if(btn) sec(btn);
}

function populateSelects(){
  const cls = [...new Map(myAssignments.map(a=>[a.class_id,a])).values()];
  ['att-class','g-class','gb-class','my-stu-class'].forEach(id=>{
    const el=$(id); if(!el) return;
    el.innerHTML=(id==='my-stu-class'?'<option value="">All My Classes</option>':'')+
      cls.map(a=>`<option value="${a.class_id}">${a.class_name}</option>`).join('');
  });
  // Set today's date on attendance
  const attDate=$('att-date');
  if(attDate) attDate.valueAsDate = new Date();
  if(cls.length){
    onGradeClassChange(); // populate subject dropdown only
  }
}

// ── MY STUDENTS (new section) ────────────────────────────────────────────────
let _allMyStudents=[];
async function loadMyStudents(){
  const cid=$('my-stu-class')?$('my-stu-class').value:'';
  let students=[];
  if(cid){
    students=await API.get(`/api/teacher/students/${cid}`)||[];
  } else {
    // Load all students across all assigned classes (deduplicated)
    const cls=[...new Map(myAssignments.map(a=>[a.class_id,a])).values()];
    const classMap={}; myAssignments.forEach(a=>classMap[a.class_id]=a.class_name);
    for(const c of cls){
      const res=await API.get(`/api/teacher/students/${c.class_id}`)||[];
      res.forEach(s=>{ students.push({...s,_className:classMap[c.class_id]}); });
    }
  }
  _allMyStudents=students;
  renderMyStudents();
}
function renderMyStudents(){
  const q=($('my-stu-search')||{}).value||'';
  const filtered=_allMyStudents.filter(s=>!q||s.full_name.toLowerCase().includes(q.toLowerCase())||
    (s.admission_number||'').toLowerCase().includes(q.toLowerCase()));
  const tbody=$('myStuTbody');
  if(!tbody) return;
  tbody.innerHTML=filtered.length?filtered.map(s=>`<tr>
    <td><span class="badge badge-sky">${s.admission_number}</span></td>
    <td><strong>${s.full_name}</strong></td>
    <td>${s.gender||'—'}</td>
    <td>${s._className||'—'}</td>
    <td style="font-size:12px">${s.parent_name||'—'}</td>
    <td style="font-size:12px">${s.parent_phone||s.parent_whatsapp||'—'}</td>
  </tr>`).join('')
  :'<tr><td colspan="6"><div class="empty"><div class="ei">👨‍🎓</div><h4>No students found</h4></div></td></tr>';
}

// ── PROFILE (new section) ─────────────────────────────────────────────────────
async function loadProfile(){
  const p=await API.get('/api/teacher/profile'); if(!p) return;
  const el=$('profileCard'); if(!el) return;
  el.innerHTML=`
    <div style="display:flex;align-items:center;gap:20px;margin-bottom:28px;flex-wrap:wrap">
      <div class="avatar" style="width:72px;height:72px;font-size:28px;background:var(--pri)">${p.full_name?p.full_name[0]:''}</div>
      <div>
        <div style="font-size:22px;font-weight:900">${p.full_name}</div>
        <div style="color:var(--g500);font-size:13px;margin-top:3px">${p.username}</div>
        <span class="badge ${p.approved?'badge-grn':'badge-amb'}" style="margin-top:6px">${p.approved?'✅ Approved':'⏳ Pending Approval'}</span>
      </div>
    </div>
    <div class="frow2" style="gap:16px">
      <div style="background:var(--g50);border-radius:var(--r12);padding:16px;border:1px solid var(--g200)">
        <div style="font-size:11px;font-weight:700;color:var(--g400);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">📧 Email</div>
        <div style="font-weight:600">${p.email||'—'}</div>
      </div>
      <div style="background:var(--g50);border-radius:var(--r12);padding:16px;border:1px solid var(--g200)">
        <div style="font-size:11px;font-weight:700;color:var(--g400);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">📱 Phone</div>
        <div style="font-weight:600">${p.phone||'—'}</div>
      </div>
      <div style="background:var(--g50);border-radius:var(--r12);padding:16px;border:1px solid var(--g200)">
        <div style="font-size:11px;font-weight:700;color:var(--g400);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">💬 WhatsApp</div>
        <div style="font-weight:600">${p.whatsapp||'—'}</div>
      </div>
      <div style="background:var(--g50);border-radius:var(--r12);padding:16px;border:1px solid var(--g200)">
        <div style="font-size:11px;font-weight:700;color:var(--g400);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">🏛️ Classes Assigned</div>
        <div style="font-weight:600">${myAssignments.length} subject${myAssignments.length!==1?'s':''}</div>
      </div>
    </div>
    <div style="margin-top:24px">
      <h4 style="font-size:13px;font-weight:800;color:var(--g500);text-transform:uppercase;letter-spacing:.4px;margin-bottom:14px">My Subject Assignments</h4>
      ${myAssignments.length?myAssignments.map(a=>`
        <div style="display:flex;align-items:center;gap:12px;padding:12px 16px;background:var(--g50);
          border-radius:var(--r12);border:1px solid var(--g200);margin-bottom:8px">
          <div style="font-size:20px">📚</div>
          <div style="flex:1">
            <div style="font-weight:700">${a.subject_name}</div>
            <div style="font-size:12px;color:var(--g500)">${a.class_name} · ${a.student_count} students</div>
          </div>
          <button class="btn btn-sm btn-pri-out" onclick="quickNav(${myAssignments.indexOf(a)})">Enter Grades →</button>
        </div>`).join('')
      :'<div class="empty"><p>No assignments yet</p></div>'}
    </div>`;
}

// ── ANNOUNCEMENTS (new section) ───────────────────────────────────────────────
async function loadAnnouncements(){
  const el=$('announcementsList'); if(!el) return;
  const rows=await API.get('/api/announcements')||[];
  el.innerHTML=rows.length?rows.map(a=>`
    <div style="background:#fff;border-radius:var(--r12);padding:18px 20px;border:1px solid var(--g200);margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:8px">
        <div style="font-size:15px;font-weight:800">${a.title}</div>
        <div style="font-size:11px;color:var(--g400);white-space:nowrap">${fmtDate(a.created_at)}</div>
      </div>
      <div style="color:var(--g700);font-size:13px;line-height:1.6">${a.body}</div>
    </div>`).join('')
  :'<div class="empty"><div class="ei">📢</div><h4>No announcements yet</h4><p>Admin announcements will appear here</p></div>';
}

function onGradeClassChange(){
  const cid = $('g-class').value;
  const subs = myAssignments.filter(a=>String(a.class_id)===String(cid));
  $('g-subject').innerHTML = subs.map(a=>`<option value="${a.subject_id}">${a.subject_name}</option>`).join('');
  loadGradeStudents();
}

// ── ATTENDANCE ────────────────────────────────────────────────────────────────
async function loadAttendance(){
  const cid=String($('att-class').value);
  const date=$('att-date').value;
  $('attRegTitle').textContent=`📝 Register — ${date}`;

  const assign=myAssignments.find(a=>String(a.class_id)===cid);
  const stuRes = await API.get(`/api/teacher/students/${cid}`);
  currentStudents = stuRes||[];
  attMap = {};

  const existing = await API.get(`/api/teacher/attendance/${cid}?date=${date}`)||[];
  existing.forEach(r=>attMap[r.student_id]=r.status);

  $('attList').innerHTML = currentStudents.length ? currentStudents.map(s=>{
    const st=attMap[s.id]||'';
    return `<div class="att-row" id="ar-${s.id}">
      <div class="att-name">${s.full_name}</div>
      <div class="att-grp" style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="att-P${st==='present'?' on':''}" onclick="setAtt(${s.id},'present')">✅ Present</button>
        <button class="att-A${st==='absent'?' on':''}" onclick="setAtt(${s.id},'absent')">❌ Absent</button>
        <button class="att-L${st==='late'?' on':''}" onclick="setAtt(${s.id},'late')">🕐 Late</button>
        <button class="att-E${st==='excused'?' on':''}" onclick="setAtt(${s.id},'excused')">📄 Excused</button>
      </div>
    </div>`;
  }).join('')
  : '<div class="empty"><div class="ei">👨‍🎓</div><p>No students in this class</p></div>';

  // Load summary
  const sum = await API.get(`/api/teacher/attendance/summary/${cid}`) || [];
  $('attSumTbody').innerHTML = sum.map(r=>{
    const pp = r.total_days>0?Math.round(r.present/r.total_days*100):0;
    return `<tr>
      <td><strong>${r.full_name}</strong></td>
      <td style="color:var(--grn);font-weight:700">${r.present}</td>
      <td style="color:var(--red);font-weight:700">${r.absent}</td>
      <td style="color:var(--amb);font-weight:700">${r.late}</td>
      <td>${r.total_days}</td>
      <td><span class="badge ${pp>=80?'badge-grn':pp>=60?'badge-amb':'badge-red'}">${pp}%</span></td>
    </tr>`;
  }).join('') || '<tr><td colspan="6"><div class="empty"><p>No records yet</p></div></td></tr>';
}

function setAtt(id,status){
  attMap[id]=status;
  const row=$('ar-'+id);
  row.querySelectorAll('.att-grp button').forEach(b=>b.classList.remove('on'));
  const map={present:'att-P',absent:'att-A',late:'att-L',excused:'att-E'};
  const btn=row.querySelector('.'+map[status]);
  if(btn) btn.classList.add('on');
}
function markAll(status){ currentStudents.forEach(s=>setAtt(s.id,status)); }

async function saveAttendance(){
  const cid=$('att-class').value;
  const date=$('att-date').value;
  const records=Object.entries(attMap).map(([id,status])=>({student_id:parseInt(id),status}));
  const r=await API.post('/api/teacher/attendance',{class_id:parseInt(cid),date,records});
  if(r?.ok) toast(`Attendance saved for ${date}! ✅`);
  else toast('Error saving attendance','error');
}

// ── VOICE ATTENDANCE ──────────────────────────────────────────────────────────
function toggleVoiceAtt(){
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){ toast('Browser does not support voice recognition','error'); return; }
  const btn=$('voiceAttBtn'), sta=$('voiceAttStatus');
  if(voiceAttActive){
    voiceRec&&voiceRec.stop(); voiceAttActive=false;
    btn.className='voice-btn idle'; btn.textContent='🎙️'; sta.style.display='none'; return;
  }
  voiceRec=new SR(); voiceRec.continuous=true; voiceRec.lang='en-GB';
  voiceRec.onresult=e=>{
    const txt=e.results[e.results.length-1][0].transcript.trim().toLowerCase();
    sta.textContent=`🎙 Heard: "${txt}"`;
    const statusMap={present:'present',absent:'absent',late:'late',excused:'excused',here:'present','not here':'absent'};
    let matched=false;
    currentStudents.forEach(s=>{
      const parts=s.full_name.toLowerCase().split(' ');
      if(parts.some(p=>p.length>2&&txt.includes(p))){
        const statusWord=Object.keys(statusMap).find(k=>txt.includes(k))||'present';
        setAtt(s.id,statusMap[statusWord]);
        toast(`${s.full_name} → ${statusMap[statusWord]}`,'info',1800);
        matched=true;
      }
    });
    if(!matched) sta.textContent=`🔍 No match for: "${txt}" — try again`;
  };
  voiceRec.onerror=e=>toast(`Voice error: ${e.error}`,'error');
  voiceRec.start(); voiceAttActive=true;
  btn.className='voice-btn rec'; btn.textContent='⏹';
  sta.style.display='block'; sta.textContent='🎙 Listening… say "[Name] present / absent / late"';
}

// ── GRADE ENTRY ───────────────────────────────────────────────────────────────
async function loadGradeStudents(){
  const cid=$('g-class').value; const sid=$('g-subject').value; const term=$('g-term').value;
  if(!cid||!sid) return;
  const stuRes=await API.get(`/api/teacher/students/${cid}`); currentStudents=stuRes||[];
  const gRes=await API.get(`/api/teacher/grades/${cid}/${sid}?term=${encodeURIComponent(term)}`)||[];
  gradeMap={}; gRes.forEach(g=>gradeMap[g.student_id]={score:g.score,comment:g.comment||''});
  renderGradeTable();
}

function renderGradeTable(){
  $('gradeTbody').innerHTML = currentStudents.map((s,i)=>{
    const g=gradeMap[s.id]||{}; const sc=g.score??''; const mx=100;
    const ltr=sc!==''?(sc>=80?'A':sc>=65?'B':sc>=50?'C':sc>=40?'D':'F'):'—';
    const chip=sc!==''?`<span class="chip chip-${ltr}">${ltr}</span>`:'—';
    return `<tr>
      <td style="color:var(--g400)">${i+1}</td>
      <td><strong>${s.full_name}</strong></td>
      <td><input class="gi" type="number" min="0" max="${mx}" id="sc-${s.id}"
        value="${sc}" oninput="liveGrade(${s.id},this.value)"></td>
      <td id="ltr-${s.id}">${chip}</td>
      <td><input style="width:160px;padding:6px 10px;font-size:12px;border:1.5px solid var(--g200);
        border-radius:var(--r8)" id="cm-${s.id}" placeholder="Optional comment" value="${g.comment||''}"></td>
    </tr>`;
  }).join('');
}

function liveGrade(id,val){
  const v=parseFloat(val);
  const ltr=isNaN(v)?'—':v>=80?'A':v>=65?'B':v>=50?'C':v>=40?'D':'F';
  $('ltr-'+id).innerHTML=isNaN(v)?'—':`<span class="chip chip-${ltr}">${ltr}</span>`;
  if(!isNaN(v)) gradeMap[id]={...(gradeMap[id]||{}),score:v};
}

async function saveGrades(){
  const cid=parseInt($('g-class').value), sid=parseInt($('g-subject').value);
  const term=$('g-term').value;
  const grades=currentStudents.filter(s=>{const el=$('sc-'+s.id);return el&&el.value!=='';})
    .map(s=>({student_id:s.id,subject_id:sid,class_id:cid,score:parseFloat($('sc-'+s.id).value),
      max_score:100, method:'manual', term, academic_year:'2025',
      comment:($('cm-'+s.id)||{}).value||''}));
  if(!grades.length){ toast('No grades to save','warn'); return; }
  const r=await API.post('/api/teacher/grades',{grades});
  if(r?.ok) toast(`${r.saved} grades saved! ✅`);
  else toast('Error saving grades','error');
}

// ── VOICE GRADES ──────────────────────────────────────────────────────────────
function toggleVoiceGrades(){
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){ toast('Browser does not support voice recognition','error'); return; }
  const btn=$('voiceGradeBtn'), sta=$('voiceGradeStatus');
  if(voiceGradeActive){
    voiceRec&&voiceRec.stop(); voiceGradeActive=false;
    btn.className='voice-btn idle'; btn.textContent='🎙️'; sta.textContent='Recording stopped'; return;
  }
  const words={zero:0,one:1,two:2,three:3,four:4,five:5,six:6,seven:7,eight:8,nine:9,
    ten:10,eleven:11,twelve:12,thirteen:13,fourteen:14,fifteen:15,sixteen:16,seventeen:17,
    eighteen:18,nineteen:19,twenty:20,thirty:30,forty:40,fifty:50,sixty:60,seventy:70,eighty:80,ninety:90,hundred:100};

  voiceRec=new SR(); voiceRec.continuous=true; voiceRec.lang='en-GB';
  voiceRec.onresult=e=>{
    const txt=e.results[e.results.length-1][0].transcript.trim().toLowerCase();
    sta.textContent=`🎙 "${txt}"`;
    const log=$('voiceGradeLog');
    log.innerHTML=`<div style="padding:5px 10px;background:var(--g50);border-radius:6px;font-size:12px;margin-bottom:5px">"${txt}"</div>`+log.innerHTML;
    let numVal=NaN;
    const nm=txt.match(/(\d+)/); if(nm) numVal=parseInt(nm[1]);
    else{let t=0,s=0;txt.split(/\s+/).forEach(w=>{const n=words[w];if(n!==undefined){if(n===100){s+=100;t+=s;s=0;}else if(n>=10)s+=n;else s+=n;}});if(s+t>0)numVal=s+t;}
    if(!isNaN(numVal)&&numVal>=0&&numVal<=100){
      currentStudents.forEach(s=>{
        if(s.full_name.toLowerCase().split(' ').some(p=>p.length>2&&txt.includes(p))){
          gradeMap[s.id]={...(gradeMap[s.id]||{}),score:numVal};
          const inp=$('sc-'+s.id); if(inp){inp.value=numVal; liveGrade(s.id,numVal);}
          toast(`${s.full_name}: ${numVal}`,'info',1800);
          renderVoiceTable();
        }
      });
    }
  };
  voiceRec.onerror=e=>toast(`Voice error: ${e.error}`,'error');
  voiceRec.start(); voiceGradeActive=true;
  btn.className='voice-btn rec'; btn.textContent='⏹';
  sta.textContent='🎙 Listening… say "Name Score" e.g. "Amara eighty-five"';
}

function renderVoiceTable(){
  $('voiceGradeTbody').innerHTML=currentStudents.filter(s=>gradeMap[s.id]?.score!=null).map(s=>{
    const v=gradeMap[s.id].score;
    const l=v>=80?'A':v>=65?'B':v>=50?'C':v>=40?'D':'F';
    return `<tr><td>${s.full_name}</td><td style="font-weight:800">${v}</td>
      <td><span class="chip chip-${l}">${l}</span></td></tr>`;
  }).join('');
}

// ── SCAN / OCR ────────────────────────────────────────────────────────────────
async function startCamera(){
  try{
    camStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'}});
    $('camFeed').srcObject=camStream; $('camBox').style.display='block';
    $('captureBtn').style.display='inline-flex'; $('stopCamBtn').style.display='inline-flex';
  }catch(e){ toast('Camera access denied: '+e.message,'error'); }
}
function stopCamera(){
  if(camStream){camStream.getTracks().forEach(t=>t.stop());camStream=null;}
  $('camBox').style.display='none'; $('captureBtn').style.display='none'; $('stopCamBtn').style.display='none';
}
function captureAndScan(){
  const v=$('camFeed'), c=$('snapCanvas');
  c.width=v.videoWidth; c.height=v.videoHeight;
  c.getContext('2d').drawImage(v,0,0);
  stopCamera();
  doScan(c.toDataURL('image/jpeg',0.85));
}
function handleUpload(e){
  const file=e.target.files[0]; if(!file) return;
  const rd=new FileReader();
  rd.onload=ev=>{
    $('uploadPreview').innerHTML=`<img src="${ev.target.result}" style="max-height:280px;border-radius:12px;border:1px solid var(--g200)">`;
    doScan(ev.target.result);
  };
  rd.readAsDataURL(file);
}
async function doScan(b64){
  toast('Scanning with OCR…','info');
  const cid=parseInt($('g-class').value);
  const r=await API.post('/api/teacher/scan',{image:b64,class_id:cid});
  if(!r?.ok){ toast(r?.error||'OCR failed — ensure pytesseract is installed','error'); return; }
  $('ocrText').style.display='block';
  $('ocrText').textContent='OCR Output: '+(r.raw_text||'(empty)');
  if(!r.matches?.length){ toast('No grades detected — try a clearer image','warn'); return; }
  $('scanResults').style.display='block';
  $('scanTbody').innerHTML=r.matches.map(m=>`<tr>
    <td>${m.student_name}</td>
    <td><input class="gi" type="number" id="scs-${m.student_id}" value="${m.score}" min="0" max="100"></td>
    <td><input type="checkbox" id="sca-${m.student_id}" checked style="width:auto;width:17px;height:17px;accent-color:var(--pri)"></td>
  </tr>`).join('');
  toast(`${r.matches.length} entries detected`);
}
function applyScan(){
  document.querySelectorAll('[id^="sca-"]').forEach(cb=>{
    if(!cb.checked) return;
    const id=cb.id.replace('sca-','');
    const v=parseFloat(($('scs-'+id)||{}).value);
    if(!isNaN(v)){ gradeMap[id]={...(gradeMap[id]||{}),score:v}; }
  });
  renderGradeTable();
  switchGradeTab('manual',document.querySelector('.tab-btn'));
  toast('Scan results applied to grade sheet!');
}

// ── CANVAS ────────────────────────────────────────────────────────────────────
function initCanvas(){
  const canvas=$('handCanvas');
  if(canvas._rdy) return;
  canvas._rdy=true;
  const W=canvas.parentElement.clientWidth||800;
  canvas.width=W; canvas.height=Math.max(currentStudents.length*44+60, 360);
  const ctx=canvas.getContext('2d');
  ctx.fillStyle='#fff'; ctx.fillRect(0,0,canvas.width,canvas.height);
  ctx.strokeStyle='#e5e7eb'; ctx.lineWidth=1;
  for(let y=50;y<canvas.height;y+=44){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(canvas.width,y);ctx.stroke();}
  ctx.fillStyle='#6b7280'; ctx.font='bold 11px Inter';
  ctx.fillText('STUDENT NAME',16,28); ctx.fillText('SCORE',300,28); ctx.fillText('GRADE',380,28);
  ctx.strokeStyle='#4f46e5'; ctx.lineWidth=1.5;
  ctx.beginPath();ctx.moveTo(0,36);ctx.lineTo(canvas.width,36);ctx.stroke();
  currentStudents.slice(0,30).forEach((s,i)=>{
    ctx.fillStyle='#374151'; ctx.font='13px Inter';
    ctx.fillText(s.full_name,16,(i+1)*44+22);
    ctx.strokeStyle='#d1d5db'; ctx.lineWidth=1;
    ctx.strokeRect(285,(i+1)*44+5,62,28); ctx.strokeRect(368,(i+1)*44+5,42,28);
  });
  const pos=ev=>{const r=canvas.getBoundingClientRect();const s=ev.touches?ev.touches[0]:ev;return[s.clientX-r.left,s.clientY-r.top];};
  canvas.addEventListener('mousedown',e=>{isDrawing=true;[lx,ly]=pos(e);e.preventDefault();});
  canvas.addEventListener('mousemove',e=>{if(!isDrawing)return;const[x,y]=pos(e);draw(ctx,x,y);[lx,ly]=[x,y];e.preventDefault();});
  canvas.addEventListener('mouseup',()=>isDrawing=false);
  canvas.addEventListener('mouseleave',()=>isDrawing=false);
  canvas.addEventListener('touchstart',e=>{isDrawing=true;[lx,ly]=pos(e);e.preventDefault();},{passive:false});
  canvas.addEventListener('touchmove',e=>{if(!isDrawing)return;const[x,y]=pos(e);draw(ctx,x,y);[lx,ly]=[x,y];e.preventDefault();},{passive:false});
  canvas.addEventListener('touchend',()=>isDrawing=false);
}
function draw(ctx,x,y){
  ctx.beginPath(); ctx.moveTo(lx,ly); ctx.lineTo(x,y);
  ctx.strokeStyle=pm==='eraser'?'#ffffff':$('penColor').value;
  ctx.lineWidth=pm==='eraser'?18:parseInt($('penSize').value);
  ctx.lineCap='round'; ctx.lineJoin='round'; ctx.stroke();
}
function clearCanvas(){ const c=$('handCanvas'); c._rdy=false; initCanvas(); }

// ── GRADE BOOK ────────────────────────────────────────────────────────────────
async function loadGradeBook(){
  const cid=$('gb-class').value, term=$('gb-term').value;
  if(!cid) return;
  const rows=await API.get(`/api/teacher/gradebook/${cid}?term=${encodeURIComponent(term)}`)||[];
  const stuMap={}, subSet=new Set();
  rows.forEach(r=>{
    if(!stuMap[r.student_name]) stuMap[r.student_name]={scores:{},tot:0,cnt:0};
    stuMap[r.student_name].scores[r.subject_name]=r;
    stuMap[r.student_name].tot+=(r.score||0); stuMap[r.student_name].cnt++;
    subSet.add(r.subject_name);
  });
  const subs=[...subSet].sort();
  const sorted=Object.entries(stuMap).sort(([,a],[,b])=>(b.cnt?b.tot/b.cnt:0)-(a.cnt?a.tot/a.cnt:0));
  $('gbHead').innerHTML=`<tr><th>#</th><th>Student</th>${subs.map(s=>`<th>${s}</th>`).join('')}<th>Avg</th><th>Grade</th></tr>`;
  $('gbBody').innerHTML=sorted.length?sorted.map(([name,d],i)=>{
    const avg=d.cnt?d.tot/d.cnt:0; const l=avg>=80?'A':avg>=65?'B':avg>=50?'C':avg>=40?'D':'F';
    return `<tr>
      <td style="color:var(--g400);font-weight:700">${i+1}</td>
      <td><strong>${name}</strong></td>
      ${subs.map(s=>{const v=d.scores[s];return v?`<td style="text-align:center;font-weight:700">${v.score??'—'}</td>`:'<td style="text-align:center;color:var(--g300)">—</td>';}).join('')}
      <td style="text-align:center;font-weight:800">${avg.toFixed(1)}%</td>
      <td><span class="chip chip-${l}">${l}</span></td>
    </tr>`;
  }).join('')
  :`<tr><td colspan="${subs.length+4}"><div class="empty"><div class="ei">📊</div><h4>No grades for this selection</h4></div></td></tr>`;
}

init();
</script>

<!-- Add Homework Modal -->
<div class="modal-bg" id="m-addHomework" onclick="if(event.target===this)closeModal(this.id)" style="display:none">
<div class="modal"><div class="modal-hdr"><h3>📝 New Homework Assignment</h3>
  <button class="close" onclick="closeModal('m-addHomework')">✕</button></div>
<div class="modal-bod">
  <div class="frow2">
    <div class="fg"><label class="flbl">Class</label>
      <select id="hw-class"></select></div>
    <div class="fg"><label class="flbl">Subject</label>
      <select id="hw-subject"></select></div>
  </div>
  <div class="fg"><label class="flbl">Title *</label><input id="hw-title" placeholder="e.g. Chapter 3 Exercise"></div>
  <div class="fg"><label class="flbl">Description</label><textarea id="hw-desc" rows="3" placeholder="Instructions…"></textarea></div>
  <div class="frow2">
    <div class="fg"><label class="flbl">Due Date</label><input id="hw-due" type="date"></div>
    <div class="fg"><label class="flbl">Max Marks (0 = no marks)</label><input id="hw-marks" type="number" value="0" min="0"></div>
  </div>
</div>
<div class="modal-ftr">
  <button class="btn btn-ghost" onclick="closeModal('m-addHomework')">Cancel</button>
  <button class="btn btn-pri" onclick="addHomework()">📝 Add Assignment</button>
</div></div></div>

<!-- Homework Submissions Modal -->
<div class="modal-bg" id="m-hwSubmissions" onclick="if(event.target===this)closeModal(this.id)" style="display:none">
<div class="modal" style="max-width:720px"><div class="modal-hdr"><h3 id="hwSubTitle">📋 Submissions</h3>
  <button class="close" onclick="closeModal('m-hwSubmissions')">✕</button></div>
<div class="modal-bod" id="hwSubBody" style="max-height:70vh;overflow-y:auto"></div>
</div></div>

</body></html>"""

TEACHER_HTML = TEACHER_HTML.replace('{{ GLOBAL }}', GLOBAL)

# ══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    os.makedirs('reports', exist_ok=True)
    print("╔══════════════════════════════════════════════════════╗")
    print(f"║  {SCHOOL_NAME} — School Management System")
    print("║  Admin:  admin@school.mw  /  Admin@2025             ║")
    print("║  URL:    http://localhost:5000                       ║")
    print("╚══════════════════════════════════════════════════════╝")
    app.run(debug=True, host='0.0.0.0', port=5000)