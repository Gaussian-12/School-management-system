from flask import Flask, session, redirect, url_for, request, jsonify
from functools import wraps
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'test-key')

# ✅ DECORATORS DEFINED FIRST
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Login required'}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def index():
    return 'School Management System is running!'

@app.route('/admin')
@login_required
@admin_required
def admin_page():
    return 'Admin Dashboard'

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if data.get('username') == 'admin@school.mw' and data.get('password') == 'Admin@2025':
        session['user_id'] = 1
        session['role'] = 'admin'
        return jsonify({'ok': True, 'role': 'admin'})
    return jsonify({'ok': False, 'msg': 'Invalid credentials'}), 401

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
