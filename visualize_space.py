import sqlite3
import numpy as np
import pandas as pd
import umap
import plotly.express as px
import base64
from PIL import Image
from io import BytesIO
import os

# --- 設定 ---
DB_PATH = "images.db"
THUMB_SIZE = (64, 64)  # 縮圖大小 (太大概網頁會跑不動)
OUTPUT_FILE = "latent_space.html"

def get_image_base64(path):
    """把圖片轉成 Base64 字串，以便嵌入 HTML"""
    try:
        if not os.path.exists(path): return None
        with Image.open(path) as img:
            img.thumbnail(THUMB_SIZE)
            buffered = BytesIO()
            img.save(buffered, format="JPEG", quality=70)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            return f"data:image/jpeg;base64,{img_str}"
    except:
        return None

print("🚀 正在讀取資料庫...")
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
# 🌟 改用 JOIN 語法從 files 與 embeddings 資料表提取資料
cursor.execute("""
    SELECT f.file_path, e.embedding 
    FROM files f
    JOIN embeddings e ON f.id = e.file_id
""")
data = cursor.fetchall()
conn.close()

if not data:
    print("❌ 資料庫是空的！")
    exit()

print(f"📊 載入 {len(data)} 筆資料，正在解析向量...")

paths = []
embeddings = []
filenames = []

for path, blob in data:
    # 將二進位 blob 轉回 numpy array
    emb = np.frombuffer(blob, dtype=np.float32)
    paths.append(path)
    filenames.append(os.path.basename(path))
    embeddings.append(emb)

X = np.array(embeddings)

print("🧠 正在進行 UMAP 降維 (將高維向量壓扁成 2D)...")
# n_neighbors: 控制聚類的緊密程度 (5-50)，min_dist: 控制點之間的最小距離
reducer = umap.UMAP(n_components=2, n_neighbors=15, min_dist=0.1, metric='cosine', random_state=42)
projections = reducer.fit_transform(X)

print("🖼️ 正在生成縮圖 (這可能需要一點時間)...")
# 為了讓 Plotly 顯示圖片，我們把 Base64 塞進 DataFrame
df = pd.DataFrame(projections, columns=['x', 'y'])
df['filename'] = filenames
df['path'] = paths
# 生成縮圖列表
df['image'] = [get_image_base64(p) or "" for p in paths]

print("✨ 正在繪製互動式圖表...")

# 1. 建立圖表，將 image 與 filename 依序打包進 custom_data 供 JS 讀取
fig = px.scatter(
    df, x='x', y='y',
    custom_data=['image', 'filename'], 
    title='AI Image Latent Space (UMAP Projection)',
    template='plotly_dark'
)

# 2. 🌟 關閉 Plotly 預設的 SVG 提示框 (hoverinfo="none")
fig.update_traces(
    marker=dict(size=6, color='#00cc96', opacity=0.8),
    hoverinfo="none" 
)

fig.update_layout(
    dragmode='pan', 
    width=1200, height=800
)

# 3. 🌟 撰寫自訂的 JavaScript 來創造真正的 HTML 懸浮窗
custom_js = """
var plotDiv = document.getElementsByClassName('plotly-graph-div')[0];

// 建立一個真正的 HTML div 作為懸浮窗
var customTooltip = document.createElement('div');
customTooltip.style.position = 'absolute';
customTooltip.style.display = 'none';
customTooltip.style.backgroundColor = 'rgba(30, 30, 30, 0.95)';
customTooltip.style.border = '1px solid #00cc96';
customTooltip.style.borderRadius = '8px';
customTooltip.style.padding = '12px';
customTooltip.style.color = '#ffffff';
customTooltip.style.pointerEvents = 'none'; // 讓滑鼠點擊能穿透，不干擾圖表操作
customTooltip.style.zIndex = '9999';
customTooltip.style.boxShadow = '0px 4px 15px rgba(0,0,0,0.5)';
document.body.appendChild(customTooltip);

// 綁定 Plotly 的滑鼠進入事件
plotDiv.on('plotly_hover', function(data) {
    if(data.points.length > 0) {
        var pt = data.points[0];
        // 讀取我們在 Python 塞入的 custom_data
        var imgSrc = pt.customdata[0]; 
        var filename = pt.customdata[1]; 

        // 🌟 防呆處理：判斷是否有合法圖片
        var imgHTML = "";
        if(imgSrc && imgSrc !== "null" && imgSrc !== "NaN" && imgSrc !== "") {
            // 正常顯示圖片
            imgHTML = `<img src="${imgSrc}" style="width: 128px; border-radius: 4px; object-fit: contain;">`;
        } else {
            // 顯示找不到圖片的灰色佔位框
            imgHTML = `<div style="width: 128px; height: 128px; background: #333; border-radius: 4px; display: flex; align-items: center; justify-content: center; color: #888; font-size: 12px; text-align: center;">預覽不可用<br>(格式不支援或遺失)</div>`;
        }

        // 組合並顯示 HTML
        customTooltip.innerHTML = `
            <div style="display: flex; align-items: center; gap: 15px;">
                ${imgHTML}
                <div style="text-align: left; max-width: 250px;">
                    <div style="font-size: 12px; color: #60cdff; font-weight: bold; margin-bottom: 4px;">檔案名稱：</div>
                    <div style="font-size: 14px; word-wrap: break-word;">${filename}</div>
                </div>
            </div>
        `;
        customTooltip.style.display = 'block';
    }
});

// 綁定滑鼠離開事件
plotDiv.on('plotly_unhover', function(data) {
    customTooltip.style.display = 'none';
});

// 讓懸浮窗完美跟隨滑鼠游標移動
window.addEventListener('mousemove', function(e) {
    if(customTooltip.style.display === 'block') {
        customTooltip.style.left = (e.pageX + 15) + 'px';
        customTooltip.style.top = (e.pageY + 15) + 'px';
    }
});
"""

# 4. 🌟 匯出 HTML 並利用 post_script 參數將 JS 腳本注入到網頁中
fig.write_html(OUTPUT_FILE, post_script=custom_js)
print(f"✅ 完成！請用瀏覽器打開: {OUTPUT_FILE}")