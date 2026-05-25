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

# Email configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', 'your-email@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', 'your-app-password')
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

# ============ ADMIN PORTAL ============
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    return render_template('admin_dashboard.html')

# API: Get all teachers
@app.route('/api/admin/teachers')
@login_required
@admin_required
def get_teachers():
    conn = get_db()
    teachers = conn.execute("SELECT id, username, full_name, email, phone FROM users WHERE role = 'teacher'").fetchall()
    conn.close()
    return jsonify([dict(t) for t in teachers])

# API: Add teacher
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

# API: Delete teacher
@app.route('/api/admin/teachers/<int:teacher_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_teacher(teacher_id):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ? AND role = 'teacher'", (teacher_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# API: Get all classes
@app.route('/api/admin/classes')
@login_required
@admin_required
def get_classes():
    conn = get_db()
    classes = conn.execute("SELECT * FROM classes ORDER BY grade_level, name").fetchall()
    conn.close()
    return jsonify([dict(c) for c in classes])

# API: Add class
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

# API: Get all subjects
@app.route('/api/admin/subjects')
@login_required
@admin_required
def get_subjects():
    conn = get_db()
    subjects = conn.execute("SELECT * FROM subjects ORDER BY name").fetchall()
    conn.close()
    return jsonify([dict(s) for s in subjects])

# API: Add subject
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

# API: Get all students
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

# API: Add student
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

# API: Assign teacher to subject and class
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

# API: Get teacher assignments
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

# API: Generate school report
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

# API: Send reports via email/WhatsApp
@app.route('/api/admin/send-reports', methods=['POST'])
@login_required
@admin_required
def send_reports():
    data = request.json
    reports = data.get('reports', [])
    send_via = data.get('method', 'email')  # 'email' or 'whatsapp'
    
    results = []
    for report in reports:
        student_id = report['student_id']
        pdf_path = report['pdf_path']
        
        conn = get_db()
        student = conn.execute("SELECT s.*, u.email as parent_email FROM students s LEFT JOIN users u ON s.parent_id = u.id WHERE s.id = ?", (student_id,)).fetchone()
        conn.close()
        
        if student and student['parent_email']:
            if send_via == 'email':
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
    
    return jsonify({'results': results})

# ============ TEACHER PORTAL ============
@app.route('/teacher')
@login_required
@teacher_required
def teacher_dashboard():
    return render_template('teacher_dashboard.html')

# API: Get teacher's assigned classes and students
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

# API: Save grade (voice/scan/manual)
@app.route('/api/teacher/save-grade', methods=['POST'])
@login_required
@teacher_required
def save_grade():
    data = request.json
    teacher_id = session['user_id']
    
    conn = get_db()
    
    # Get current term
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
            grade['method'],
            term_name,
            datetime.now().strftime('%Y')
        ))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': f"Saved {len(data['grades'])} grades"})

# API: Get teacher's submitted grades
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

# API: Get all subjects for teacher's class
@app.route('/api/teacher/subjects/<int:class_id>')
@login_required
@teacher_required
def get_teacher_subjects(class_id):
    teacher_id = session['user_id']
    
    conn = get_db()
    subjects = conn.execute("""
        SELECT s.id, s.name, s.code
        FROM teacher_subjects ts
        JOIN subjects s ON ts.subject_id = s.id
        WHERE ts.teacher_id = ? AND ts.class_id = ?
    """, (teacher_id, class_id)).fetchall()
    
    conn.close()
    return jsonify([dict(s) for s in subjects])

# Helper function for HTML report
def generate_report_html(student, grades, average, term):
    letter_grade = 'A' if average >= 90 else 'B' if average >= 80 else 'C' if average >= 70 else 'D' if average >= 60 else 'F'
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Report Card - {student['name']}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 50px; }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            .school {{ font-size: 28px; font-weight: bold; color: #2c3e50; }}
            .title {{ font-size: 20px; color: #666; }}
            .info {{ background: #f5f5f5; padding: 15px; border-radius: 10px; margin: 20px 0; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
            th {{ background: #4CAF50; color: white; }}
            .summary {{ background: #e8f5e9; padding: 15px; border-radius: 10px; margin-top: 20px; }}
            .footer {{ text-align: center; font-size: 12px; color: #999; margin-top: 50px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="school">School Management System</div>
            <div class="title">Student Report Card - {term}</div>
        </div>
        <div class="info">
            <strong>Student:</strong> {student['name']}<br>
            <strong>Admission No:</strong> {student['admission_number']}<br>
            <strong>Date:</strong> {datetime.now().strftime('%B %d, %Y')}
        </div>
        <table>
            <thead><tr><th>Subject</th><th>Grade</th></tr></thead>
            <tbody>
                {''.join(f'<tr><td>{g["subject_name"]}</td><td>{g["grade_value"]}</td></tr>' for g in grades)}
            </tbody>
        </table>
        <div class="summary">
            <strong>Average:</strong> {average:.1f}%<br>
            <strong>Letter Grade:</strong> {letter_grade}
        </div>
        <div class="footer">Generated by School Management System</div>
    </body>
    </html>
    """

if __name__ == '__main__':
    os.makedirs('reports', exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)