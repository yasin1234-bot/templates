import os
import io
import uuid
import base64
import zlib
import marshal
import sqlite3
import urllib.request
import json
from datetime import datetime
from flask import Flask, render_template, request, send_file, flash, redirect, url_for, jsonify

app = Flask(__name__)
app.secret_key = "yasin_sec_key_123"

# SQLite Database Setup
def init_db():
    conn = sqlite3.connect('history.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS encoded_files (
            file_id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            expiry_time TEXT NOT NULL,
            is_expired INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

BANNER_TEMPLATE = r"""
#   __   __          _       ____      ___      _   _ 
#   \ \ / /         / \     / ___|    |_ _|    | \ | |
#    \ V /         / _ \    \___ \     | |     |  \| |
#     | |         / ___ \    ___) |    | |     | |\  |
#     |_|        /_/   \_\  |____/    |___|    |_| \_|
#
#
#    ENCODED BY YASIN
#    YASIN ENCODED V1.0 (SECURE LOCK)
#    NO PASSWORD REQUIRED
#    EXPIRY: {expiry_display}
#    AUTO-EXPIRE ENABLED
#
"""

def generate_obfuscated_code(raw_code, expiry_dt_str, file_id, server_url):
    wrapper = f"""
import sys
import threading
import time
import os
import json
import urllib.request
from datetime import datetime

EXPIRY_TIME_STR = "{expiry_dt_str}"
FILE_ID = "{file_id}"
SERVER_URL = "{server_url}"

def check_remote_status():
    try:
        url = f"{{SERVER_URL}}/check_status/{{FILE_ID}}"
        req = urllib.request.urlopen(url, timeout=3)
        res = json.loads(req.read().decode())
        if res.get('expired'):
            print("\\n[!] CRITICAL ERROR: File status updated! License force-expired by admin.")
            os._exit(1)
    except Exception:
        pass

def check_expiry_loop():
    while True:
        try:
            exp_dt = datetime.strptime(EXPIRY_TIME_STR, "%Y-%m-%d %H:%M:%S")
            if datetime.now() > exp_dt:
                print("\\n[!] CRITICAL ERROR: License Expired while running!")
                print(f"[!] File was valid till: {{EXPIRY_TIME_STR}}")
                print("[!] Contact YASIN for renewal.")
                os._exit(1)
            check_remote_status()
        except Exception:
            pass
        time.sleep(5)

expiry_thread = threading.Thread(target=check_expiry_loop, daemon=True)
expiry_thread.start()

# Initial Checks
try:
    exp_dt = datetime.strptime(EXPIRY_TIME_STR, "%Y-%m-%d %H:%M:%S")
    if datetime.now() > exp_dt:
        print("\\n[!] CRITICAL ERROR: License Expired!")
        print(f"[!] File was valid till: {{EXPIRY_TIME_STR}}")
        print("[!] Contact YASIN for renewal.")
        sys.exit(1)
    check_remote_status()
except Exception:
    sys.exit(1)

{raw_code}
"""

    compiled = compile(wrapper, '<yasin_core>', 'exec')
    marshalled = marshal.dumps(compiled)
    compressed = zlib.compress(marshalled)
    encoded = base64.b64encode(compressed).decode('utf-8')

    chunk_size = 60
    chunks = [encoded[i:i+chunk_size] for i in range(0, len(encoded), chunk_size)]
    tokens_code_lines = ",\n".join([f"    'YASIN_{c}'" for c in chunks])
    tokens_code = f"TOKENS = [\n{tokens_code_lines}\n]"

    loader = BANNER_TEMPLATE.format(expiry_display=expiry_dt_str) + f"""
import marshal, zlib, base64, sys

{tokens_code}

try:
    raw_b64 = "".join([t.replace("YASIN_", "") for t in TOKENS])
    decoded = base64.b64decode(raw_b64)
    decompressed = zlib.decompress(decoded)
    code_obj = marshal.loads(decompressed)
    exec(code_obj)
except Exception as e:
    print(f"[!] ERROR: Script execution failed. Details: {{e}}")
    sys.exit(1)
"""
    return loader

@app.route('/', methods=['GET', 'POST'])
def index():
    conn = sqlite3.connect('history.db')
    cursor = conn.cursor()

    if request.method == 'POST':
        file = request.files.get('file')
        year = request.form.get('year')
        month = request.form.get('month')
        day = request.form.get('day')
        hour = request.form.get('hour')
        minute = request.form.get('minute')
        second = request.form.get('second')

        if not file or file.filename == '':
            flash('দয়া করে একটি পাইথন (.py) ফাইল সিলেক্ট করুন!', 'error')
            return redirect(url_for('index'))

        try:
            expiry_str = f"{year}-{int(month):02d}-{int(day):02d} {int(hour):02d}:{int(minute):02d}:{int(second):02d}"
            datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")

            file_id = str(uuid.uuid4())[:8]
            server_url = request.host_url.rstrip('/')

            raw_code = file.read().decode('utf-8')
            protected_code = generate_obfuscated_code(raw_code, expiry_str, file_id, server_url)

            cursor.execute("INSERT INTO encoded_files (file_id, filename, expiry_time) VALUES (?, ?, ?)", 
                           (file_id, file.filename, expiry_str))
            conn.commit()

            # Memory buffer output (For 100% Render & Railway Cloud compatibility)
            mem_file = io.BytesIO()
            mem_file.write(protected_code.encode('utf-8'))
            mem_file.seek(0)

            return send_file(mem_file, as_attachment=True, download_name=f"yasin_enc_{file.filename}", mimetype='text/x-python')

        except ValueError:
            flash('তারিখ ও সময় ঠিকমতো পূরণ করুন!', 'error')
            return redirect(url_for('index'))

    cursor.execute("SELECT file_id, filename, expiry_time, is_expired FROM encoded_files ORDER BY rowid DESC")
    files_list = cursor.fetchall()
    conn.close()

    return render_template('index.html', files=files_list)

# API Endpoint for Remote Status Check
@app.route('/check_status/<file_id>')
def check_status(file_id):
    conn = sqlite3.connect('history.db')
    cursor = conn.cursor()
    cursor.execute("SELECT expiry_time, is_expired FROM encoded_files WHERE file_id = ?", (file_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({'expired': True})
    
    exp_time_str, is_expired = row
    if is_expired == 1:
        return jsonify({'expired': True})
        
    try:
        exp_dt = datetime.strptime(exp_time_str, "%Y-%m-%d %H:%M:%S")
        if datetime.now() > exp_dt:
            return jsonify({'expired': True})
    except Exception:
        pass

    return jsonify({'expired': False})

@app.route('/expire/<file_id>')
def force_expire(file_id):
    conn = sqlite3.connect('history.db')
    cursor = conn.cursor()
    past_time = "2000-01-01 00:00:00"
    cursor.execute("UPDATE encoded_files SET expiry_time = ?, is_expired = 1 WHERE file_id = ?", (past_time, file_id))
    conn.commit()
    conn.close()
    flash('ফাইলটি সাথে সাথে এক্সপায়ার করে দেওয়া হলো!', 'success')
    return redirect(url_for('index'))

@app.route('/delete/<file_id>')
def delete_file_record(file_id):
    conn = sqlite3.connect('history.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM encoded_files WHERE file_id = ?", (file_id,))
    conn.commit()
    conn.close()
    flash('তালিকা থেকে ফাইলটি ডিলিট করা হয়েছে!', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
