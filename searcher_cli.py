import os
from search_engine import ImageSearchEngine

def main():
    # 實例化引擎
    engine = ImageSearchEngine()
    
    if not engine.is_ready:
        return

    print("--------------------------------------------------")
    print("👉 提示：支援通用搜尋介面")
    print("👉 輸入 'q' 離開")
    print("--------------------------------------------------")

    while True:
        query = input("\n🔍 請輸入搜尋關鍵字: ").strip()
        
        if query.lower() in ['q', 'exit']:
            break
        if not query:
            continue
        
        # 呼叫搜尋引擎 (要求回傳 Top 3)
        results = engine.search(query, top_k=3)
        
        print(f"🎯 搜尋結果:")
        for res in results:
            print(f"   [{res['rank']}] 分數: {res['score']} | 📂 {res['filename']}")

        # 自動開啟第一名
        if results:
            best_img = results[0]['path']
            try:
                os.startfile(best_img)
            except Exception as e:
                print(f"⚠️ 無法開啟圖片: {e}")

if __name__ == "__main__":
    main()