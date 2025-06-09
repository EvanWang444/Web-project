import sqlite3
import os
import json
import re
from datetime import datetime
from typing import List, Dict, Tuple, Any, Optional
from contextlib import contextmanager
from flask import Flask, render_template, request, redirect, url_for
from werkzeug.utils import secure_filename

 
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
class DatabaseManager:
    """封裝所有資料庫操作。"""

    def __init__(self, db_path='database.db'):
        self.db_path = db_path

    @contextmanager
    def get_db_connection(self):
        """提供一個自動管理開關的資料庫連線。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except sqlite3.Error as e:
            print(f"資料庫操作錯誤: {e}")
            conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def init_db(self):
        """初始化資料庫和所有需要的資料表。"""
        with self.get_db_connection() as conn:
            # 表單主表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS forms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    custom_fields JSON NOT NULL,
                    table_name TEXT,
                    created_at TEXT NOT NULL
                );
            ''')
            conn.commit()

    def get_all_forms(self) -> List[sqlite3.Row]:
        """取得所有表單的列表。"""
        with self.get_db_connection() as conn:
            return conn.execute('SELECT * FROM forms ORDER BY id DESC').fetchall()

    def get_form_by_id(self, form_id: int) -> Optional[sqlite3.Row]:
        """根據 ID 取得單一表單。"""
        with self.get_db_connection() as conn:
            return conn.execute('SELECT * FROM forms WHERE id = ?', (form_id,)).fetchone()

    def create_form_and_table(self, title: str, description: str, custom_fields_data: List[Dict[str, str]]) -> None:
        """
        以交易方式創建新表單及其對應的提交資料表。
        確保所有操作要麼全部成功，要麼全部失敗。
        """
        with self.get_db_connection() as conn:
            custom_fields_json = json.dumps(custom_fields_data)
            created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # 步驟 1: 插入表單元數據
            cursor = conn.execute(
                'INSERT INTO forms (title, description, custom_fields, created_at) VALUES (?, ?, ?, ?)',
                (title, description, custom_fields_json, created_at)
            )
            form_id = cursor.lastrowid
            table_name = f"form_submissions_{form_id}"

            # 步驟 2: 更新 table_name
            conn.execute('UPDATE forms SET table_name = ? WHERE id = ?', (table_name, form_id))

            # 步驟 3: 動態建立提交記錄資料表
            columns = [
                "id INTEGER PRIMARY KEY AUTOINCREMENT",
                "name TEXT NOT NULL", "email TEXT NOT NULL", "phone TEXT NOT NULL",
                "timestamp TEXT NOT NULL"
            ]
            # 由於 sanitize_column_name 函式已被移除，這裡直接使用原始名稱，這可能導致問題
            columns.extend(f'"{field["original_name"]}" TEXT' for field in custom_fields_data)
            conn.execute(f"CREATE TABLE {table_name} ({', '.join(columns)});")
            
            conn.commit()

    def delete_form_and_table(self, form_id: int) -> bool:
        """刪除表單及其對應的提交資料表。"""
        form = self.get_form_by_id(form_id)
        if not form or not form['table_name']:
            return False
            
        with self.get_db_connection() as conn:
            conn.execute(f"DROP TABLE IF EXISTS {form['table_name']}")
            conn.execute('DELETE FROM forms WHERE id = ?', (form_id,))
            conn.commit()
        return True

    def save_submission(self, form: sqlite3.Row, form_data: Dict[str, Any]) -> None:
        """儲存一筆表單提交記錄。"""
        custom_fields = json.loads(form['custom_fields'])
        
        columns = ['name', 'email', 'phone', 'timestamp']
        values = [
            form_data['name'], form_data['email'], form_data['phone'],
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ]
        
        for field in custom_fields:
            # 由於 sanitize_column_name 函式已被移除，這裡直接使用原始名稱，這可能導致問題
            columns.append(f'"{field["original_name"]}"')
            values.append(form_data.get(field['original_name'], ''))
            
        placeholders = ', '.join(['?'] * len(values))
        sql = f"INSERT INTO {form['table_name']} ({', '.join(columns)}) VALUES ({placeholders})"
        
        with self.get_db_connection() as conn:
            conn.execute(sql, tuple(values))
            conn.commit()

    def get_submissions_with_ordered_headers(self, form_id: int) -> Tuple[List[str], List[List[Any]]]:
        """取得特定表單的提交記錄，並回傳排序好的表頭和資料。"""
        form = self.get_form_by_id(form_id)
        if not form or not form['table_name']:
            return [], []

        with self.get_db_connection() as conn:
            # 1. 取得資料庫中實際存在的欄位
            cursor = conn.execute(f"PRAGMA table_info({form['table_name']})")
            db_columns = {row['name'] for row in cursor}

            # 2. 定義欄位順序和顯示名稱
            header_map = {'name': '姓名', 'email': '電子郵件', 'phone': '手機號碼', 'timestamp': '提交時間'}
            # 由於 sanitize_column_name 函式已被移除，這裡直接使用原始名稱，這可能導致問題
            custom_fields_map = {f['original_name']: f['original_name'] for f in json.loads(form['custom_fields'])}
            
            # 依序建立最終要查詢的欄位和顯示的表頭
            query_cols, display_headers = [], []

            # 標準欄位
            for col in ['name', 'email', 'phone']:
                if col in db_columns:
                    query_cols.append(f'"{col}"')
                    display_headers.append(header_map[col])
            
            # 自訂欄位 (依照創建順序)
            for san_name, org_name in custom_fields_map.items(): # san_name 現在其實是 original_name
                    if san_name in db_columns:
                        query_cols.append(f'"{san_name}"')
                        display_headers.append(org_name)

            # 時間戳欄位
            if 'timestamp' in db_columns:
                query_cols.append('"timestamp"')
                display_headers.append(header_map['timestamp'])
            
            # 3. 查詢資料
            if not query_cols:
                return [], []

            sql = f'SELECT {", ".join(query_cols)} FROM {form["table_name"]} ORDER BY id DESC'
            rows = conn.execute(sql).fetchall()
            submissions_data = [list(row) for row in rows]
            
            return display_headers, submissions_data

# 實例化資料庫管理器
db_manager = DatabaseManager()

# ====================================================================
# 路由函式 (Flask Routes)
# ====================================================================

def _validate_and_prepare_fields(fields_input: str) -> Tuple[Optional[str], Optional[List[Dict[str, str]]]]:
    """驗證自訂欄位輸入並準備儲存結構。回傳 (錯誤訊息, 欄位資料)。"""
    if not fields_input:
        return None, []

    fields_raw = list(dict.fromkeys([f.strip() for f in re.split(r'[,\s]+|，', fields_input) if f.strip()]))
    
    if len(fields_raw) > 10:
        return '自訂欄位數量不得超過10個！', None
    
    for field in fields_raw:
        if len(field) > 50:
            return f'自訂欄位 "{field}" 過長，長度不得超過50個字符！', None
    
    # 建立包含原始名稱和唯一淨化名稱的 JSON 結構
    # 由於 sanitize_column_name 函式已被移除，sanitized_name 將直接使用 original_name，這可能導致問題
    custom_fields_data = [
        {
            "original_name": name,
            "sanitized_name": name # 直接使用原始名稱，不再淨化
        }
        for i, name in enumerate(fields_raw)
    ]
    return None, custom_fields_data

@app.route('/form_admin')
def form_admin():
    """表單管理主頁。"""
    try:
        forms = db_manager.get_all_forms()
    except sqlite3.Error:
        forms = []
    return render_template('form_admin.html', forms=forms)

@app.route('/form_admin/create_form', methods=['GET', 'POST'])
def create_form():
    """創建新表單。"""
    if request.method == 'POST':
        title = request.form['title'].strip()
        description = request.form['description'].strip()
        custom_fields_input = request.form.get('custom_fields', '').strip()

        if not title:
            return render_template('create_form.html', **request.form)

        error_msg, fields_data = _validate_and_prepare_fields(custom_fields_input)
        if error_msg:
            return render_template('create_form.html', **request.form)

        try:
            db_manager.create_form_and_table(title, description, fields_data)
        except sqlite3.Error:
            pass
        
        return redirect(url_for('form_admin'))

    return render_template('create_form.html')

@app.route('/form_admin/delete_form/<int:form_id>')
def delete_form(form_id: int):
    """刪除表單及其提交記錄。"""
    try:
        if db_manager.delete_form_and_table(form_id):
            pass
        else:
            pass
    except sqlite3.Error:
        pass
    return redirect(url_for('form_admin'))

@app.route('/form/<int:form_id>', methods=['GET', 'POST'])
def dynamic_form(form_id: int):
    """顯示和處理動態表單。"""
    try:
        form = db_manager.get_form_by_id(form_id)
        if not form:
            return render_template('404.html'), 404

        if request.method == 'POST':
            if not form['table_name']:
                return redirect(url_for('dynamic_form', form_id=form_id))
            
            db_manager.save_submission(form, request.form)
            return redirect(url_for('form_submitted'))

        custom_fields = json.loads(form['custom_fields'])
        original_field_names = [field['original_name'] for field in custom_fields]
        return render_template('dynamic_form.html', form=form, custom_fields=original_field_names)
        
    except sqlite3.Error:
        return render_template('500.html'), 500

@app.route('/form_submitted')
def form_submitted():
    """表單提交成功頁面。"""
    return render_template('form_submitted.html')

@app.route('/form_admin/form_submissions')
def admin_form_submissions():
    """後台顯示所有表單的提交記錄。"""
    selected_form_id = request.args.get('form_id', type=int)
    headers, submissions_data, forms = [], [], []

    try:
        forms = db_manager.get_all_forms()
        if selected_form_id:
            headers, submissions_data = db_manager.get_submissions_with_ordered_headers(selected_form_id)
    except sqlite3.Error:
        pass

    return render_template(
        'form_all.html', 
        submissions=submissions_data, 
        forms=forms, 
        selected_form_id=selected_form_id,
        headers=headers
    )

 