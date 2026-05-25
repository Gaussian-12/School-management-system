import sqlite3

conn = sqlite3.connect('school.db')
c = conn.cursor()

# Users table
c.execute('''CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    full_name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    role TEXT NOT NULL CHECK(role IN ('admin', 'teacher', 'parent')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')

# Classes table
c.execute('''CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    grade_level INTEGER,
    academic_year TEXT
)''')

# Subjects table
c.execute('''CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    code TEXT UNIQUE
)''')

# Students table
c.execute('''CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    class_id INTEGER,
    parent_id INTEGER,
    admission_number TEXT UNIQUE,
    FOREIGN KEY (class_id) REFERENCES classes(id),
    FOREIGN KEY (parent_id) REFERENCES users(id)
)''')

# Teacher Subjects mapping (which teacher teaches which subject to which class)
c.execute('''CREATE TABLE IF NOT EXISTS teacher_subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    class_id INTEGER NOT NULL,
    FOREIGN KEY (teacher_id) REFERENCES users(id),
    FOREIGN KEY (subject_id) REFERENCES subjects(id),
    FOREIGN KEY (class_id) REFERENCES classes(id),
    UNIQUE(teacher_id, subject_id, class_id)
)''')

# Grades table
c.execute('''CREATE TABLE IF NOT EXISTS grades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    teacher_id INTEGER NOT NULL,
    class_id INTEGER NOT NULL,
    grade_value INTEGER CHECK(grade_value >= 0 AND grade_value <= 100),
    method TEXT CHECK(method IN ('voice', 'scan', 'manual')),
    term TEXT,
    academic_year TEXT,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    status TEXT DEFAULT 'submitted',
    FOREIGN KEY (student_id) REFERENCES students(id),
    FOREIGN KEY (subject_id) REFERENCES subjects(id),
    FOREIGN KEY (teacher_id) REFERENCES users(id),
    FOREIGN KEY (class_id) REFERENCES classes(id)
)''')

# Reports table
c.execute('''CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    class_id INTEGER,
    report_type TEXT,
    file_path TEXT,
    generated_by INTEGER,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_to_parents BOOLEAN DEFAULT 0,
    FOREIGN KEY (student_id) REFERENCES students(id),
    FOREIGN KEY (class_id) REFERENCES classes(id),
    FOREIGN KEY (generated_by) REFERENCES users(id)
)''')

# Terms table
c.execute('''CREATE TABLE IF NOT EXISTS terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_date DATE,
    end_date DATE,
    is_active BOOLEAN DEFAULT 0
)''')

# Insert default admin
import bcrypt
hashed = bcrypt.hashpw('admin123'.encode('utf-8'), bcrypt.gensalt())
c.execute("INSERT OR IGNORE INTO users (username, password, full_name, role) VALUES (?, ?, ?, ?)",
          ('admin@school.com', hashed, 'System Administrator', 'admin'))

# Insert default subjects
default_subjects = [
    ('Mathematics', 'MATH101'),
    ('English', 'ENG101'),
    ('Science', 'SCI101'),
    ('History', 'HIST101'),
    ('Geography', 'GEO101'),
    ('Art', 'ART101'),
    ('Physical Education', 'PE101')
]
c.executemany("INSERT OR IGNORE INTO subjects (name, code) VALUES (?, ?)", default_subjects)

# Insert default classes
default_classes = [
    ('Grade 5A', 5, '2025'),
    ('Grade 5B', 5, '2025'),
    ('Grade 6A', 6, '2025'),
    ('Grade 6B', 6, '2025')
]
c.executemany("INSERT OR IGNORE INTO classes (name, grade_level, academic_year) VALUES (?, ?, ?)", default_classes)

# Insert default term
c.execute("INSERT OR IGNORE INTO terms (name, is_active) VALUES ('Term 1', 1)")

conn.commit()
conn.close()

print("Database setup complete!")
print("Admin login: admin@school.com / admin123")
