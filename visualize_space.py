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
# 讀取路徑和向量
cursor.execute("SELECT file_path, embedding FROM images")
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
df['image'] = [get_image_base64(p) for p in paths]

print("✨ 正在繪製互動式圖表...")

fig = px.scatter(
    df, x='x', y='y',
    hover_name='filename',
    custom_data=['image'], # 把圖片數據藏在 custom_data
    title='AI Image Latent Space (UMAP Projection)',
    template='plotly_dark'
)

#這段黑魔法是為了讓滑鼠 hover 時顯示圖片
fig.update_traces(
    marker=dict(size=5, color='#00cc96', opacity=0.8),
    hovertemplate="<b>%{hovertext}</b><br><br>" +
                  "<img src='%{customdata[0]}' width='128'><br>" +
                  "<extra></extra>"
)

fig.update_layout(
    dragmode='pan', 
    hoverlabel=dict(bgcolor="rgba(30,30,30,0.8)", font_size=14),
    width=1200, height=800
)

fig.write_html(OUTPUT_FILE)
print(f"✅ 完成！請用瀏覽器打開: {OUTPUT_FILE}")