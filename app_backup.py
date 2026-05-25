from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
from flask_cors import CORS
from flask_mail import Mail, Message
import sqlite3
from datetime import datetime
from weasyprint import HTML
import bcrypt
import json
import os
import re
from functools import wraps
import requests

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'
CORS(app)

# Email configuration (optional, configure later)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
mail = Mail(app)

# Database helper
def get_db():
    conn = sqlite3.connect('school.db')
    conn.row_factory = sqlite3.Row
    return conn

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Please login first'}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

def teacher_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') not in ['admin', 'teacher']:
            return jsonify({'error': 'Teacher access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def index():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif session.get('role') == 'teacher':
            return redirect(url_for('teacher_dashboard'))
    return render_template('login.html')

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    return render_template('admin_dashboard.html')

@app.route('/teacher')
@login_required
@teacher_required
def teacher_dashboard():
    return render_template('teacher_dashboard.html')

# ============ AUTHENTICATION ============
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    
    if user and bcrypt.checkpw(password.encode('utf-8'), user['password']):
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['full_name'] = user['full_name']
        session['role'] = user['role']
        return jsonify({'success': True, 'role': user['role']})
    
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ============ ADMIN API ============
@app.route('/api/admin/teachers')
@login_required
@admin_required
def get_teachers():
    conn = get_db()
    teachers = conn.execute("SELECT id, username, full_name, email, phone, created_at FROM users WHERE role = 'teacher'").fetchall()
    conn.close()
    return jsonify([dict(t) for t in teachers])

@app.route('/api/admin/teachers/add', methods=['POST'])
@login_required
@admin_required
def add_teacher():
    data = request.json
    hashed = bcrypt.hashpw(data['password'].encode('utf-8'), bcrypt.gensalt())
    
    conn = get_db()
    try:
        conn.execute("INSERT INTO users (username, password, full_name, email, phone, role) VALUES (?, ?, ?, ?, ?, 'teacher')",
                     (data['email'], hashed, data['full_name'], data['email'], data.get('phone', '')))
        conn.commit()
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'Email already exists'}), 400
    finally:
        conn.close()

@app.route('/api/admin/teachers/<int:teacher_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_teacher(teacher_id):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ? AND role = 'teacher'", (teacher_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/classes')
@login_required
@admin_required
def get_classes():
    conn = get_db()
    classes = conn.execute("SELECT * FROM classes ORDER BY grade_level, name").fetchall()
    conn.close()
    return jsonify([dict(c) for c in classes])

@app.route('/api/admin/classes/add', methods=['POST'])
@login_required
@admin_required
def add_class():
    data = request.json
    conn = get_db()
    conn.execute("INSERT INTO classes (name, grade_level, academic_year) VALUES (?, ?, ?)",
                 (data['name'], data['grade_level'], data['academic_year']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/subjects')
@login_required
@admin_required
def get_subjects():
    conn = get_db()
    subjects = conn.execute("SELECT * FROM subjects ORDER BY name").fetchall()
    conn.close()
    return jsonify([dict(s) for s in subjects])

@app.route('/api/admin/subjects/add', methods=['POST'])
@login_required
@admin_required
def add_subject():
    data = request.json
    conn = get_db()
    conn.execute("INSERT INTO subjects (name, code) VALUES (?, ?)",
                 (data['name'], data['code']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/students')
@login_required
@admin_required
def get_students():
    conn = get_db()
    students = conn.execute("""
        SELECT s.*, c.name as class_name 
        FROM students s
        LEFT JOIN classes c ON s.class_id = c.id
        ORDER BY s.name
    """).fetchall()
    conn.close()
    return jsonify([dict(s) for s in students])

@app.route('/api/admin/students/add', methods=['POST'])
@login_required
@admin_required
def add_student():
    data = request.json
    conn = get_db()
    conn.execute("INSERT INTO students (name, class_id, admission_number) VALUES (?, ?, ?)",
                 (data['name'], data['class_id'], data['admission_number']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/assign', methods=['POST'])
@login_required
@admin_required
def assign_teacher():
    data = request.json
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO teacher_subjects (teacher_id, subject_id, class_id) VALUES (?, ?, ?)",
                 (data['teacher_id'], data['subject_id'], data['class_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/assignments')
@login_required
@admin_required
def get_assignments():
    conn = get_db()
    assignments = conn.execute("""
        SELECT ts.*, u.full_name as teacher_name, s.name as subject_name, c.name as class_name
        FROM teacher_subjects ts
        JOIN users u ON ts.teacher_id = u.id
        JOIN subjects s ON ts.subject_id = s.id
        JOIN classes c ON ts.class_id = c.id
    """).fetchall()
    conn.close()
    return jsonify([dict(a) for a in assignments])

@app.route('/api/admin/assignments/<int:assignment_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_assignment(assignment_id):
    conn = get_db()
    conn.execute("DELETE FROM teacher_subjects WHERE id = ?", (assignment_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/generate-report', methods=['POST'])
@login_required
@admin_required
def generate_school_report():
    data = request.json
    class_id = data.get('class_id')
    term = data.get('term')
    
    conn = get_db()
    
    if class_id:
        students = conn.execute("SELECT * FROM students WHERE class_id = ?", (class_id,)).fetchall()
    else:
        students = conn.execute("SELECT * FROM students").fetchall()
    
    reports = []
    for student in students:
        grades = conn.execute("""
            SELECT g.*, s.name as subject_name 
            FROM grades g
            JOIN subjects s ON g.subject_id = s.id
            WHERE g.student_id = ? AND g.term = ?
        """, (student['id'], term)).fetchall()
        
        if grades:
            avg_grade = sum(g['grade_value'] for g in grades) / len(grades)
            
            # Generate PDF
            html = generate_report_html(student, grades, avg_grade, term)
            pdf_path = f"reports/report_{student['id']}_{term}.pdf"
            os.makedirs('reports', exist_ok=True)
            HTML(string=html).write_pdf(pdf_path)
            
            reports.append({
                'student_id': student['id'],
                'student_name': student['name'],
                'pdf_path': pdf_path,
                'average': avg_grade
            })
    
    conn.close()
    return jsonify({'reports': reports})

@app.route('/api/admin/send-reports', methods=['POST'])
@login_required
@admin_required
def send_reports():
    data = request.json
    reports = data.get('reports', [])
    send_via = data.get('method', 'email')
    
    results = []
    for report in reports:
        student_id = report['student_id']
        pdf_path = report['pdf_path']
        
        conn = get_db()
        student = conn.execute("SELECT s.*, u.email as parent_email FROM students s LEFT JOIN users u ON s.parent_id = u.id WHERE s.id = ?", (student_id,)).fetchone()
        conn.close()
        
        if student and student['parent_email'] and send_via == 'email':
            try:
                msg = Message(f"Report Card for {student['name']}",
                              sender=app.config['MAIL_USERNAME'],
                              recipients=[student['parent_email']])
                msg.body = f"Dear Parent,\n\nPlease find attached the report card for {student['name']}.\n\nRegards,\nSchool Management"
                with app.open_resource(pdf_path) as fp:
                    msg.attach(f"{student['name']}_report.pdf", "application/pdf", fp.read())
                mail.send(msg)
                results.append({'student': student['name'], 'status': 'sent'})
            except Exception as e:
                results.append({'student': student['name'], 'status': f'failed: {str(e)}'})
        else:
            results.append({'student': student['name'], 'status': 'no email'})
    
    return jsonify({'results': results})

# ============ TEACHER API ============
@app.route('/api/teacher/classes')
@login_required
@teacher_required
def get_teacher_classes():
    teacher_id = session['user_id']
    conn = get_db()
    
    assignments = conn.execute("""
        SELECT DISTINCT c.*, s.name as subject_name, s.id as subject_id
        FROM teacher_subjects ts
        JOIN classes c ON ts.class_id = c.id
        JOIN subjects s ON ts.subject_id = s.id
        WHERE ts.teacher_id = ?
    """, (teacher_id,)).fetchall()
    
    result = []
    for assignment in assignments:
        students = conn.execute("""
            SELECT id, name, admission_number FROM students WHERE class_id = ?
        """, (assignment['id'],)).fetchall()
        
        result.append({
            'class': dict(assignment),
            'students': [dict(s) for s in students]
        })
    
    conn.close()
    return jsonify(result)

@app.route('/api/teacher/save-grade', methods=['POST'])
@login_required
@teacher_required
def save_grade():
    data = request.json
    teacher_id = session['user_id']
    
    conn = get_db()
    term = conn.execute("SELECT name FROM terms WHERE is_active = 1").fetchone()
    term_name = term['name'] if term else 'Term 1'
    
    for grade in data['grades']:
        conn.execute("""
            INSERT OR REPLACE INTO grades 
            (student_id, subject_id, teacher_id, class_id, grade_value, method, term, academic_year, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            grade['student_id'],
            grade['subject_id'],
            teacher_id,
            grade['class_id'],
            grade['grade_value'],
            grade.get('method', 'manual'),
            term_name,
            datetime.now().strftime('%Y')
        ))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': f"Saved {len(data['grades'])} grades"})

@app.route('/api/teacher/grades/<int:class_id>/<int:subject_id>')
@login_required
@teacher_required
def get_teacher_grades(class_id, subject_id):
    teacher_id = session['user_id']
    
    conn = get_db()
    term = conn.execute("SELECT name FROM terms WHERE is_active = 1").fetchone()
    term_name = term['name'] if term else 'Term 1'
    
    grades = conn.execute("""
        SELECT g.*, s.name as student_name
        FROM grades g
        JOIN students s ON g.student_id = s.id
        WHERE g.class_id = ? AND g.subject_id = ? AND g.teacher_id = ? AND g.term = ?
    """, (class_id, subject_id, teacher_id, term_name)).fetchall()
    
    conn.close()
    return jsonify([dict(g) for g in grades])

# Helper function
def generate_report_html(student, grades, average, term):
    letter_grade = 'A' if average >= 90 else 'B' if average >= 80 else 'C' if average >= 70 else 'D' if average >= 60 else 'F'
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><title>Report Card</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 50px; }}
        .header {{ text-align: center; margin-bottom: 30px; }}
        .school {{ font-size: 24px; font-weight: bold; color: #2c3e50; }}
        .info {{ background: #f5f5f5; padding: 15px; border-radius: 10px; margin: 20px 0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background: #4CAF50; color: white; }}
        .summary {{ background: #e8f5e9; padding: 15px; border-radius: 10px; }}
    </style>
    </head>
    <body>
        <div class="header"><div class="school">School Management System</div><div>Report Card - {term}</div></div>
        <div class="info"><strong>Student:</strong> {student['name']}<br><strong>Admission:</strong> {student['admission_number']}</div>
        </table><thead><tr><th>Subject</th><th>Grade</th></tr></thead>
        <tbody>{''.join(f'53赖<td>{g["subject_name"]}</td><td>{g["grade_value"]}</td>53赖' for g in grades)}</tbody>
    ?</table>
        <div class="summary"><strong>Average:</strong> {average:.1f}%<br><strong>Grade:</strong> {letter_grade}</div>
    </body>
    </html>
    """

if __name__ == '__main__':
    os.makedirs('reports', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)
#@app.route('/register-teacher', methods=['POST'])
def register_teacher():
    try:
        data = request.json
        print(f"📝 Registration attempt: {data.get('email')}")
        
        conn = sqlite3.connect('school.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Check if email already exists in users
        c.execute("SELECT id FROM users WHERE username = ?", (data['email'],))
        if c.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Email already registered'}), 400
        
        # Check if already pending
        c.execute("SELECT id FROM pending_teachers WHERE email = ?", (data['email'],))
        if c.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Registration already pending approval'}), 400
        
        # Hash password
        hashed = bcrypt.hashpw(data['password'].encode('utf-8'), bcrypt.gensalt())
        
        # Insert into pending_teachers
        c.execute("""
            INSERT INTO pending_teachers (full_name, email, phone, school_name, qualification, experience_years, password, reason, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (
            data['full_name'],
            data['email'],
            data.get('phone', ''),
            data.get('school_name', ''),
            data.get('qualification', ''),
            int(data.get('experience_years', 0)) if data.get('experience_years') else 0,
            hashed,
            data.get('reason', '')
        ))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Registration successful for {data['email']}")
        return jsonify({'success': True, 'message': 'Registration submitted for admin approval'})
        
    except Exception as e:
        print(f"❌ Registration error: {str(e)}")
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/api/admin/pending-teachers')
@login_required
@admin_required
def get_pending_teachers():
    conn = get_db()
    pending = conn.execute("SELECT * FROM pending_teachers WHERE status = 'pending' ORDER BY registration_date DESC").fetchall()
    conn.close()
    return jsonify([dict(p) for p in pending])

@app.route('/api/admin/approve-teacher/<int:pending_id>', methods=['POST'])
@login_required
@admin_required
def approve_teacher(pending_id):
    conn = get_db()
    pending = conn.execute("SELECT * FROM pending_teachers WHERE id = ?", (pending_id,)).fetchone()
    if not pending:
        conn.close()
        return jsonify({'success': False}), 404
    
    conn.execute("""INSERT INTO users (username, password, full_name, email, phone, role, approved)
                   VALUES (?, ?, ?, ?, ?, 'teacher', 1)""",
                 (pending['email'], pending['password'], pending['full_name'], pending['email'], pending['phone']))
    conn.execute("UPDATE pending_teachers SET status = 'approved' WHERE id = ?", (pending_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/reject-teacher/<int:pending_id>', methods=['POST'])
@login_required
@admin_required
def reject_teacher(pending_id):
    conn = get_db()
    conn.execute("UPDATE pending_teachers SET status = 'rejected' WHERE id = ?", (pending_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})
