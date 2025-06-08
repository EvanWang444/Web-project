from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
import os
from datetime import datetime
from werkzeug.utils import secure_filename
from typing import List, Optional
from sqlite3 import Connection, Row
import json
import re

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.secret_key = 'your_secret_key_here'  # 必要，用於 flash 訊息

def init_db() -> None:
    """
    初始化資料庫，創建 announcements、images、form_submissions 和 forms 資料表。
    """
    try:
        conn = sqlite3.connect('database.db')
         
        conn.execute('''
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                announcement_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                is_cover INTEGER DEFAULT 0,
                FOREIGN KEY (announcement_id) REFERENCES announcements (id)
            );
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS form_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                form_id INTEGER,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                custom_fields JSON NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (form_id) REFERENCES forms (id)
            );
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS forms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                custom_fields JSON NOT NULL,
                created_at TEXT NOT NULL
            );
        ''')
        conn.commit()
    except sqlite3.Error as e:
        print(f"資料庫錯誤: {e}")
    finally:
        conn.close()

def get_db_connection() -> Connection:
    """
    建立並回傳資料庫連線。
    """
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/form_admin')
def form_admin():
    """
    表單管理頁面，顯示所有表單提交記錄及自訂表單。
    """
    try:
        conn = get_db_connection()
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        table_names = [table['name'] for table in tables]
        required_tables = ['form_submissions', 'forms']
        
        for table in required_tables:
            if table not in table_names:
                print(f"警告：缺少表格 {table}")

        form_submissions = conn.execute(
            'SELECT * FROM form_submissions ORDER BY id DESC'
        ).fetchall()
        forms = conn.execute(
            'SELECT * FROM forms ORDER BY id DESC'
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"資料庫查詢錯誤: {e}")
        form_submissions = []
        forms = []
    except Exception as e:
        print(f"未知錯誤: {e}")
        form_submissions = []
        forms = []
    finally:
        conn.close()
    return render_template('form_admin.html', form_submissions=form_submissions, forms=forms)

@app.route('/form_admin/create_form', methods=['GET', 'POST'])
def create_form():
    """
    後台創建新表單，允許輸入標題、描述和自訂欄位名稱。
    自訂欄位支持英文逗號、中文逗號、空格等多種分隔符，並進行防呆驗證。
    """
    if request.method == 'POST':
        title: str = request.form['title'].strip()
        description: str = request.form['description'].strip()
        custom_fields_input: str = request.form.get('custom_fields', '').strip()

        # 使用正則表達式分割多種分隔符（英文逗號、中文逗號、空白字符）
        if custom_fields_input:
            custom_fields = re.split(r'[,\s]+|，', custom_fields_input)
            # 過濾空欄位、去除空白、重複欄位，並確保有效
            custom_fields = [field.strip() for field in custom_fields if field.strip()]
            custom_fields = list(dict.fromkeys(custom_fields))  # 移除重複
        else:
            custom_fields = []

        # 驗證輸入
        if not title:
            flash('表單標題不能為空！', 'danger')
            return render_template('create_form.html', title=title, description=description, custom_fields=custom_fields_input)
        
        if len(custom_fields) > 10:  # 限制自訂欄位數量，防呆
            flash('自訂欄位數量不得超過10個！', 'danger')
            return render_template('create_form.html', title=title, description=description, custom_fields=custom_fields_input)

        for field in custom_fields:
            if len(field) > 50:  # 限制單個欄位名稱長度
                flash(f'自訂欄位 "{field}" 過長，長度不得超過50個字符！', 'danger')
                return render_template('create_form.html', title=title, description=description, custom_fields=custom_fields_input)

        created_at: str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        try:
            conn = get_db_connection()
            conn.execute(
                'INSERT INTO forms (title, description, custom_fields, created_at) VALUES (?, ?, ?, ?)',
                (title, description, json.dumps(custom_fields), created_at)
            )
            conn.commit()
            flash('表單創建成功！', 'success')
        except sqlite3.Error as e:
            print(f"表單創建失敗: {e}")
            flash('表單創建失敗，請稍後再試！', 'danger')
        finally:
            conn.close()
        return redirect(url_for('form_admin'))

    return render_template('create_form.html')

@app.route('/form_admin/delete_form/<int:form_id>')
def delete_form(form_id: int):
    """
    刪除表單。
    """
    try:
        conn = get_db_connection()
        conn.execute(
            'DELETE FROM forms WHERE id = ?',
            (form_id,)
        )
        conn.commit()
        flash('表單刪除成功！', 'success')
    except sqlite3.Error as e:
        print(f"表單刪除失敗: {e}")
        flash('表單刪除失敗，請稍後再試！', 'danger')
    finally:
        conn.close()
    return redirect(url_for('form_admin'))

@app.route('/form/<int:form_id>', methods=['GET', 'POST'])
def dynamic_form(form_id: int):
    """
    動態表單頁面，包含固定欄位（姓名、電子郵件、手機號碼）和自訂欄位（textarea）。
    """
    try:
        conn = get_db_connection()
        form = conn.execute(
            'SELECT * FROM forms WHERE id = ?',
            (form_id,)
        ).fetchone()

        if not form:
            conn.close()
            return render_template('404.html'), 404

        custom_fields = json.loads(form['custom_fields'])

        if request.method == 'POST':
            name: str = request.form['name']
            email: str = request.form['email']
            phone: str = request.form['phone']
            custom_field_values = {field: request.form.get(field, '') for field in custom_fields}
            timestamp: str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            try:
                conn.execute(
                    'INSERT INTO form_submissions (form_id, name, email, phone, custom_fields, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
                    (form_id, name, email, phone, json.dumps(custom_field_values), timestamp)
                )
                conn.commit()
            except sqlite3.Error as e:
                print(f"表單提交失敗: {e}")
                flash('表單提交失敗，請稍後再試！', 'danger')
            finally:
                conn.close()
            return redirect(url_for('form_submitted'))

        conn.close()
        return render_template('dynamic_form.html', form=form, custom_fields=custom_fields)

    except sqlite3.Error as e:
        print(f"資料庫錯誤: {e}")
        return render_template('500.html'), 500

@app.route('/form_submitted')
def form_submitted():
    """
    表單提交成功後的確認頁面。
    """
    return render_template('form_submitted.html')

@app.route('/form_admin/form_submissions')
def admin_form_submissions():
    """
    後台頁面，顯示所有表單提交記錄或特定表單的提交記錄，僅限管理員查看。
    """
    try:
        conn = get_db_connection()
        forms = conn.execute('SELECT id, title FROM forms ORDER BY id DESC').fetchall()
        form_id = request.args.get('form_id', type=int)
        
        if form_id:
            submissions = conn.execute(
                '''
                SELECT fs.*, f.title as form_title 
                FROM form_submissions fs 
                LEFT JOIN forms f ON fs.form_id = f.id 
                WHERE fs.form_id = ? 
                ORDER BY fs.id DESC
                ''',
                (form_id,)
            ).fetchall()
        else:
            submissions = conn.execute(
                '''
                SELECT fs.*, f.title as form_title 
                FROM form_submissions fs 
                LEFT JOIN forms f ON fs.form_id = f.id 
                ORDER BY fs.id DESC
                '''
            ).fetchall()
        
        submissions = [dict(submission) for submission in submissions]
        for submission in submissions:
            if submission['custom_fields']:
                try:
                    submission['custom_fields'] = json.loads(submission['custom_fields'])
                except json.JSONDecodeError as e:
                    print(f"JSON 解析錯誤 (submission ID {submission['id']}): {e}")
                    submission['custom_fields'] = {}
            else:
                submission['custom_fields'] = {}
                
    except sqlite3.Error as e:
        print(f"資料庫錯誤: {e}")
        submissions = []
        forms = []
    finally:
        conn.close()
    
    return render_template('form_all.html', submissions=submissions, forms=forms, selected_form_id=form_id)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)