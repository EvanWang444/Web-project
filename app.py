from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import os
from datetime import datetime
from werkzeug.utils import secure_filename
from typing import List, Optional
from sqlite3 import Connection, Row
import json

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'

def init_db() -> None:
    """
    初始化資料庫，創建 announcements、images、form_submissions 和 forms 資料表。
    """
    try:
        conn = sqlite3.connect('database.db')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                image TEXT,
                timestamp TEXT NOT NULL
            );
        ''')
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

@app.route('/')
def index():
    """
    首頁，顯示最新三則公告。
    """
    try:
        conn = get_db_connection()
        announcements = conn.execute(
            'SELECT * FROM announcements ORDER BY id DESC LIMIT 3'
        ).fetchall()
    finally:
        conn.close()
    return render_template('index.html', announcements=announcements)

@app.route('/announcements')
def announcement_list():
    """
    公告列表頁面。
    """
    try:
        conn = get_db_connection()
        announcements = conn.execute(
            'SELECT * FROM announcements ORDER BY id DESC'
        ).fetchall()
    finally:
        conn.close()
    return render_template('announcements.html', announcements=announcements)

@app.route('/announcements/<int:announcement_id>')
def announcement_detail(announcement_id: int):
    """
    公告詳情頁。
    """
    try:
        conn = get_db_connection()
        announcement = conn.execute(
            'SELECT * FROM announcements WHERE id = ?',
            (announcement_id,)
        ).fetchone()
        images = conn.execute(
            'SELECT * FROM images WHERE announcement_id = ?',
            (announcement_id,)
        ).fetchall()
    finally:
        conn.close()
    return render_template('announcement_detail.html', announcement=announcement, images=images)

@app.route('/admin')
def admin():
    """
    管理頁面，顯示所有公告、表單提交記錄及自訂表單。
    """
    try:
        conn = get_db_connection()
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        table_names = [table['name'] for table in tables]
        required_tables = ['announcements', 'form_submissions', 'forms']
        
        for table in required_tables:
            if table not in table_names:
                print(f"警告：缺少表格 {table}")
                 

        announcements = conn.execute(
            'SELECT * FROM announcements ORDER BY id DESC'
        ).fetchall()
        form_submissions = conn.execute(
            'SELECT * FROM form_submissions ORDER BY id DESC'
        ).fetchall()
        forms = conn.execute(
            'SELECT * FROM forms ORDER BY id DESC'
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"資料庫查詢錯誤: {e}")
    except Exception as e:
        print(f"未知錯誤: {e}")
    finally:
        conn.close()
    return render_template('admin.html', announcements=announcements, form_submissions=form_submissions, forms=forms)

@app.route('/admin/create', methods=['GET', 'POST'])
def create():
    """
    新增公告。
    """
    if request.method == 'POST':
        title: str = request.form['title']
        content: str = request.form['content']
        image = request.files.get('image')
        images = request.files.getlist('images')
        timestamp: str = datetime.now().strftime('%Y-%m-%d')

        image_filename: Optional[str] = None
        if image and image.filename:
            filename = secure_filename(image.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image.save(image_path)
            image_filename = filename

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO announcements (title, content, image, timestamp) VALUES (?, ?, ?, ?)',
                (title, content, image_filename, timestamp)
            )
            announcement_id = cursor.lastrowid

            for img in images:
                if img and img.filename:
                    img_name = secure_filename(img.filename)
                    img_path = os.path.join(app.config['UPLOAD_FOLDER'], img_name)
                    img.save(img_path)
                    cursor.execute(
                        'INSERT INTO images (announcement_id, filename) VALUES (?, ?)',
                        (announcement_id, img_name)
                    )
            conn.commit()
        except sqlite3.Error as e:
            print(f"資料庫錯誤: {e}")
        finally:
            conn.close()

        return redirect(url_for('admin'))

    return render_template('create.html')

@app.route('/admin/delete/<int:announcement_id>')
def delete(announcement_id: int):
    """
    刪除公告。
    """
    try:
        conn = get_db_connection()
        conn.execute(
            'DELETE FROM announcements WHERE id = ?',
            (announcement_id,)
        )
        conn.commit()
    except sqlite3.Error as e:
        print(f"刪除失敗: {e}")
    finally:
        conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/edit/<int:announcement_id>', methods=['GET', 'POST'])
def edit(announcement_id: int):
    """
    編輯公告。
    """
    conn = get_db_connection()
    announcement = conn.execute(
        'SELECT * FROM announcements WHERE id = ?',
        (announcement_id,)
    ).fetchone()

    if request.method == 'POST':
        title: str = request.form['title']
        content: str = request.form['content']
        image = request.files.get('image')

        image_filename: str = announcement['image']
        if image and image.filename:
            filename = secure_filename(image.filename)
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_filename = filename

        try:
            conn.execute(
                'UPDATE announcements SET title = ?, content = ?, image = ? WHERE id = ?',
                (title, content, image_filename, announcement_id)
            )
            conn.commit()
        except sqlite3.Error as e:
            print(f"更新失敗: {e}")
        finally:
            conn.close()
        return redirect(url_for('admin'))

    conn.close()
    return render_template('edit.html', announcement=announcement)

@app.route('/admin/create_form', methods=['GET', 'POST'])
def create_form():
    """
    後台創建新表單，允許輸入標題、描述和自訂欄位名稱。
    """
    if request.method == 'POST':
        title: str = request.form['title']
        description: str = request.form['description']
        custom_fields: List[str] = request.form.get('custom_fields', '').split(',') if request.form.get('custom_fields') else []
        custom_fields = [field.strip() for field in custom_fields if field.strip()]
        created_at: str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        try:
            conn = get_db_connection()
            conn.execute(
                'INSERT INTO forms (title, description, custom_fields, created_at) VALUES (?, ?, ?, ?)',
                (title, description, json.dumps(custom_fields), created_at)
            )
            conn.commit()
        except sqlite3.Error as e:
            print(f"表單創建失敗: {e}")
        finally:
            conn.close()
        return redirect(url_for('admin'))

    return render_template('create_form.html')

@app.route('/admin/delete_form/<int:form_id>')
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
    except sqlite3.Error as e:
        print(f"表單刪除失敗: {e}")
    finally:
        conn.close()
    return redirect(url_for('admin'))

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
                
            finally:
                conn.close()
            return redirect(url_for('form_submitted'))

        conn.close()
        return render_template('dynamic_form.html', form=form, custom_fields=custom_fields)

    except sqlite3.Error as e:
        print(f"資料庫錯誤: {e}")
         
@app.route('/form_submitted')
def form_submitted():
    """
    表單提交成功後的確認頁面。
    """
    return render_template('form_submitted.html')

@app.route('/admin/form_submissions')
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
    finally:
        conn.close()
    
    return render_template('form_all.html', submissions=submissions, forms=forms, selected_form_id=form_id)

 