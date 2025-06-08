import sqlite3
import os
import json
import re
from datetime import datetime
from typing import List, Optional
from sqlite3 import Connection

from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename

# ====================================================================
#  Flask 應用程式設定
# ====================================================================
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.secret_key = 'a_very_secret_key_that_you_should_change'  # 請務必更換為您自己的密鑰

# ====================================================================
#  工具函式 (Utility Function)
# ====================================================================
def sanitize_column_name(name: str) -> str:
    """
    將使用者提供的欄位名稱淨化為合法的 SQLite 欄位名稱。
    - 將空白和無效字元替換為底線。
    - 轉換為小寫。
    - 加上 'field_' 前綴以避免與標準欄位或 SQL 關鍵字衝突。
    """
    name = name.strip()
    # 將所有非字母、數字的字元替換為底線
    name = re.sub(r'[^a-zA-Z0-9]', '_', name)
    # 避免以數字開頭的欄位名稱
    if name and name[0].isdigit():
        name = '_' + name
    return f"field_{name.lower()}"

# ====================================================================
#  資料庫相關函式
# ====================================================================
def init_db() -> None:
    """
    初始化資料庫。
    - 創建 forms 表來儲存表單定義。
    - 每個表單的提交記錄將儲存在其獨立的資料表中。
    """
    try:
        conn = sqlite3.connect('database.db')
        
        # 為了完整性，補上 announcements 表的創建（原程式碼有引用但未創建）
        conn.execute('''
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
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
        
        # 主表單，儲存每個表單的元數據
        conn.execute('''
            CREATE TABLE IF NOT EXISTS forms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                custom_fields JSON NOT NULL,
                table_name TEXT, -- 儲存對應的提交記錄資料表名稱
                created_at TEXT NOT NULL
            );
        ''')
        conn.commit()
    except sqlite3.Error as e:
        print(f"資料庫初始化錯誤: {e}")
    finally:
        if conn:
            conn.close()

def get_db_connection() -> Connection:
    """
    建立並回傳資料庫連線，並設定 row_factory 以便將查詢結果當作字典處理。
    """
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

# ====================================================================
#  路由函式 (Flask Routes)
# ====================================================================

@app.route('/form_admin')
def form_admin():
    """
    表單管理主頁，顯示所有已創建的自訂表單。
    """
    try:
        conn = get_db_connection()
        forms = conn.execute(
            'SELECT * FROM forms ORDER BY id DESC'
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        print(f"資料庫查詢錯誤: {e}")
        forms = []
        flash('無法讀取表單列表，請檢查資料庫連線。', 'danger')
        
    return render_template('form_admin.html', forms=forms)

@app.route('/form_admin/create_form', methods=['GET', 'POST'])
def create_form():
    """
    後台創建新表單。
    成功創建後，會動態生成一個專門儲存該表單提交記錄的資料表。
    (已修復中文欄位名稱衝突問題)
    """
    if request.method == 'POST':
        title: str = request.form['title'].strip()
        description: str = request.form['description'].strip()
        custom_fields_input: str = request.form.get('custom_fields', '').strip()

        # --- 輸入驗證 ---
        if not title:
            flash('表單標題不能為空！', 'danger')
            return render_template('create_form.html', title=title, description=description, custom_fields=custom_fields_input)

        if custom_fields_input:
            custom_fields_raw = re.split(r'[,\s]+|，', custom_fields_input)
            custom_fields_raw = list(dict.fromkeys([f.strip() for f in custom_fields_raw if f.strip()]))
        else:
            custom_fields_raw = []

        if len(custom_fields_raw) > 10:
            flash('自訂欄位數量不得超過10個！', 'danger')
            return render_template('create_form.html', title=title, description=description, custom_fields=custom_fields_input)

        for field in custom_fields_raw:
            if len(field) > 50:
                flash(f'自訂欄位 "{field}" 過長，長度不得超過50個字符！', 'danger')
                return render_template('create_form.html', title=title, description=description, custom_fields=custom_fields_input)
        # --- 驗證結束 ---

        # 建立包含原始名稱和唯一淨化名稱的 JSON 結構
        custom_fields_data = []
        # 使用 enumerate 來獲取索引，確保淨化後的欄位名稱是唯一的
        for i, name in enumerate(custom_fields_raw):
            sanitized_base = sanitize_column_name(name)
            # 將索引附加到名稱後面，例如：field____0, field____1
            unique_sanitized_name = f"{sanitized_base}_{i}"
            custom_fields_data.append({
                "original_name": name,
                "sanitized_name": unique_sanitized_name
            })
        
        custom_fields_json = json.dumps(custom_fields_data)
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        conn = get_db_connection()
        try:
            # 步驟 1: 將表單元數據插入 'forms' 表
            cursor = conn.execute(
                'INSERT INTO forms (title, description, custom_fields, created_at) VALUES (?, ?, ?, ?)',
                (title, description, custom_fields_json, created_at)
            )
            form_id = cursor.lastrowid
            table_name = f"form_submissions_{form_id}"

            # 步驟 2: 用新產生的資料表名稱更新 'forms' 表中的記錄
            conn.execute(
                'UPDATE forms SET table_name = ? WHERE id = ?',
                (table_name, form_id)
            )

            # 步驟 3: 動態建立這個表單專屬的提交記錄資料表
            columns = [
                "id INTEGER PRIMARY KEY AUTOINCREMENT",
                "name TEXT NOT NULL",
                "email TEXT NOT NULL",
                "phone TEXT NOT NULL",
                "timestamp TEXT NOT NULL"
            ]
            for field in custom_fields_data:
                columns.append(f'"{field["sanitized_name"]}" TEXT')

            create_table_sql = f"CREATE TABLE {table_name} ({', '.join(columns)});"
            conn.execute(create_table_sql)
            
            conn.commit()
            flash('表單創建成功，並已建立專屬資料表！', 'success')
        except sqlite3.Error as e:
            conn.rollback() # 如果出錯，復原所有操作
            print(f"表單創建失敗: {e}")
            flash('表單創建失敗，資料庫發生錯誤！', 'danger')
        finally:
            conn.close()
            
        return redirect(url_for('form_admin'))

    return render_template('create_form.html')

@app.route('/form_admin/delete_form/<int:form_id>')
def delete_form(form_id: int):
    """
    刪除一個表單及其對應的提交記錄資料表。
    """
    conn = get_db_connection()
    try:
        # 步驟 1: 在刪除前，先取得對應的資料表名稱
        form = conn.execute('SELECT table_name FROM forms WHERE id = ?', (form_id,)).fetchone()
        
        if form and form['table_name']:
            # 步驟 2: 刪除專屬的提交記錄資料表
            conn.execute(f"DROP TABLE IF EXISTS {form['table_name']}")
        
        # 步驟 3: 從 'forms' 表中刪除該表單的定義
        conn.execute('DELETE FROM forms WHERE id = ?', (form_id,))
        
        conn.commit()
        flash('表單及其所有提交記錄已成功刪除！', 'success')
    except sqlite3.Error as e:
        conn.rollback()
        print(f"表單刪除失敗: {e}")
        flash('表單刪除失敗，請稍後再試！', 'danger')
    finally:
        conn.close()
    return redirect(url_for('form_admin'))

@app.route('/form/<int:form_id>', methods=['GET', 'POST'])
def dynamic_form(form_id: int):
    """
    處理動態表單的顯示（GET）和提交（POST）。
    """
    conn = get_db_connection()
    try:
        form = conn.execute('SELECT * FROM forms WHERE id = ?', (form_id,)).fetchone()

        if not form:
            conn.close()
            return render_template('404.html'), 404

        custom_fields_data = json.loads(form['custom_fields'])
        
        if request.method == 'POST':
            table_name = form['table_name']
            if not table_name:
                flash('表單設定錯誤，無法提交！', 'danger')
                return redirect(url_for('dynamic_form', form_id=form_id))

            # 準備要插入的資料
            columns = ['name', 'email', 'phone', 'timestamp']
            values = [
                request.form['name'],
                request.form['email'],
                request.form['phone'],
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ]
            
            # 從 form 中用 "original_name" 來獲取使用者輸入的值
            for field in custom_fields_data:
                columns.append(f'"{field["sanitized_name"]}"')
                values.append(request.form.get(field['original_name'], ''))
                
            placeholders = ', '.join(['?'] * len(values))
            sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
            
            conn.execute(sql, tuple(values))
            conn.commit()
            return redirect(url_for('form_submitted'))

        # 對於 GET 請求，將原始欄位名稱列表傳遞給模板
        original_field_names = [field['original_name'] for field in custom_fields_data]
        return render_template('dynamic_form.html', form=form, custom_fields=original_field_names)

    except sqlite3.Error as e:
        print(f"資料庫錯誤: {e}")
        return render_template('500.html'), 500
    finally:
        if conn:
            conn.close()

@app.route('/form_submitted')
def form_submitted():
    """
    表單提交成功後的確認頁面。
    """
    return render_template('form_submitted.html')

@app.route('/form_admin/form_submissions')
def admin_form_submissions():
    """
    後台頁面，根據選擇的表單，顯示其獨立資料表中的所有提交記錄。
    (已調整欄位順序，將自訂欄位顯示在提交時間之前)
    """
    conn = get_db_connection()
    submissions_data = []
    headers = []
    selected_form_id = request.args.get('form_id', type=int)
    
    try:
        # 取得所有表單列表以供下拉選單使用
        forms = conn.execute('SELECT id, title FROM forms ORDER BY id DESC').fetchall()
        
        if selected_form_id:
            form_info = conn.execute(
                'SELECT table_name, custom_fields FROM forms WHERE id = ?', 
                (selected_form_id,)
            ).fetchone()
            
            if form_info and form_info['table_name']:
                table_name = form_info['table_name']
                
                # 從資料庫 schema 獲取所有實際存在的欄位名稱
                cursor = conn.execute(f"PRAGMA table_info({table_name})")
                db_columns = {row['name'] for row in cursor.fetchall()} # 使用集合(set)以便快速查找
                
                # 建立欄位名稱映射（淨化名稱 -> 原始名稱）
                custom_fields_list = json.loads(form_info['custom_fields'])
                custom_fields_map = {
                    field['sanitized_name']: field['original_name'] 
                    for field in custom_fields_list
                }
                
                # ====================================================================
                #  ↓↓↓ 主要修改區域：手動定義欄位順序 ↓↓↓
                # ====================================================================

                # 1. 定義欄位類型與順序
                standard_cols = ['name', 'email', 'phone']
                timestamp_col = ['timestamp']
                
                # 依據創建時的順序，找出所有存在的自訂欄位
                custom_cols_ordered = [
                    field['sanitized_name']
                    for field in custom_fields_list
                    if field['sanitized_name'] in db_columns
                ]

                # 2. 依照 新順序 (標準欄位 -> 自訂欄位 -> 時間戳) 建立查詢列表和表頭列表
                final_query_cols = []
                display_headers = []
                header_map = {'name': '姓名', 'email': '電子郵件', 'phone': '手機號碼', 'timestamp': '提交時間'}

                # 先加入標準欄位
                for col in standard_cols:
                    if col in db_columns:
                        final_query_cols.append(f'"{col}"')
                        display_headers.append(header_map[col])

                # 接著加入自訂欄位
                for col in custom_cols_ordered:
                    final_query_cols.append(f'"{col}"')
                    display_headers.append(custom_fields_map[col])

                # 最後加入提交時間
                for col in timestamp_col:
                    if col in db_columns:
                        final_query_cols.append(f'"{col}"')
                        display_headers.append(header_map[col])
                
                headers = display_headers
                # ====================================================================
                #  ↑↑↑ 主要修改區域結束 ↑↑↑
                # ====================================================================

                # 3. 使用重新排序後的欄位列表執行查詢
                if final_query_cols:
                    submission_rows = conn.execute(
                        f'SELECT {", ".join(final_query_cols)} FROM {table_name} ORDER BY id DESC'
                    ).fetchall()
                    # 將 sqlite3.Row 對象轉換為普通列表
                    submissions_data = [list(row) for row in submission_rows]

    except sqlite3.Error as e:
        print(f"讀取提交記錄時發生錯誤: {e}")
        flash('讀取提交記錄時發生錯誤，可能是資料表不存在或損毀。', 'danger')
        submissions_data = []
        forms = []
    finally:
        conn.close()
    
    return render_template(
        'form_all.html', 
        submissions=submissions_data, 
        forms=forms, 
        selected_form_id=selected_form_id,
        headers=headers  # 將動態表頭傳遞給模板
    )
# ====================================================================
#  主程式執行入口
# ====================================================================
if __name__ == '__main__':
    # 首次運行前檢查資料庫是否存在，若否，則初始化
    if not os.path.exists('database.db'):
        print("資料庫 'database.db' 不存在，正在進行初始化...")
        init_db()
        print("資料庫初始化完成。")
    app.run(debug=True, port=5000)