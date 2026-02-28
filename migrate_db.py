import sqlite3
import os
import shutil
import json

def run_migration():
    db_path = "images.db"
    backup_path = "images_backup.db"

    # 1. 安全第一：備份資料庫
    if os.path.exists(db_path):
        shutil.copy2(db_path, backup_path)
        print(f"✅ 已建立資料庫備份: {backup_path}")
    else:
        print("❌ 找不到 images.db，請確認是否在正確的目錄。")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("⏳ 正在建立新的 ocr_results 子表...")
        # 2. 建立完美的子表架構
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ocr_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER,
                lang TEXT,
                ocr_text TEXT,
                ocr_data TEXT,
                confidence REAL,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
            )
        ''')

        print("⏳ 正在轉移現有 OCR 資料...")
        # 3. 讀取現有資料
        # 注意：我們使用 PRAGMA table_info 來確保欄位存在，避免報錯
        cursor.execute("PRAGMA table_info(files)")
        columns = [info[1] for info in cursor.fetchall()]
        
        has_jp = 'ocr_text_jp' in columns
        
        if has_jp:
            cursor.execute("SELECT id, ocr_text, ocr_data, ocr_text_jp, ocr_data_jp FROM files")
            rows = cursor.fetchall()

            for row in rows:
                file_id, text_ch, data_ch, text_jp, data_jp = row
                
                # 遷移中文資料 (原本的 ocr_text)
                if text_ch and text_ch != "[NONE]":
                    cursor.execute("INSERT INTO ocr_results (file_id, lang, ocr_text, ocr_data) VALUES (?, ?, ?, ?)", 
                                   (file_id, 'ch', text_ch, data_ch))
                
                # 遷移日文資料 (如果之前有存的話)
                if text_jp and text_jp != "[NONE]":
                    cursor.execute("INSERT INTO ocr_results (file_id, lang, ocr_text, ocr_data) VALUES (?, ?, ?, ?)", 
                                   (file_id, 'jp', text_jp, data_jp))
        else:
            print("⏭️ 未偵測到舊的日文欄位，只需建立新表。")

        print("⏳ 正在清理 files 表的遺留欄位...")
        # 4. 結構清理：刪除那些佔位子的欄位
        # Python 3.10 內建的 SQLite 支援 DROP COLUMN
        columns_to_drop = ['ocr_text_jp', 'ocr_data_jp', 'active_ocr_lang']
        
        for col in columns_to_drop:
            if col in columns:
                cursor.execute(f"ALTER TABLE files DROP COLUMN {col};")
                print(f"  🗑️ 已刪除欄位: {col}")

        # 💡 注意：我們暫時保留了 files 表裡的 ocr_text 和 ocr_data
        # 因為你「還沒改主程式」，如果現在全砍了，indexer.py 會有寫入錯誤。
        # 等到我們正式重構 indexer.py 時，再來把它們徹底拿掉！

        conn.commit()
        print("\n🎉 資料庫遷移與清理成功！你的 images.db 現在擁有完美的子表架構了！")

    except sqlite3.OperationalError as e:
        print(f"\n❌ SQLite 執行錯誤: {e}")
        print("這可能是因為有程式(如 Blur-main.py)正在佔用資料庫，請先關閉主程式再執行此腳本。")
        conn.rollback()
    except Exception as e:
        print(f"\n❌ 發生未知的錯誤: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    print("🚀 開始執行資料庫清理手術...\n")
    run_migration()