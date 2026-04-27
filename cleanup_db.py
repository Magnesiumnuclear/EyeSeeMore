import sqlite3

def cleanup():
    conn = sqlite3.connect("images.db")
    cursor = conn.cursor()
    
    # 1. 刪除所有找不到對應 collection 的項目
    cursor.execute("DELETE FROM collection_items WHERE collection_id NOT IN (SELECT id FROM collections);")
    print(f"已清理孤兒圖片關聯，影響行數: {cursor.rowcount}")
    
    conn.commit()
    conn.close()

def reset_id():
    conn = sqlite3.connect("images.db")
    cursor = conn.cursor()
    
    # 檢查 collections 是否為空
    cursor.execute("SELECT COUNT(*) FROM collections")
    if cursor.fetchone()[0] == 0:
        # 重置自增計數器
        cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'collections';")
        print("collections ID 已成功歸零重置。")
    else:
        print("警告：表內還有資料，無法歸零。請先刪除所有收藏夾。")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    cleanup()