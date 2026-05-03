"""
visualize_space_parametric.py
EyeSeeMore — AI 圖片潛在空間視覺化工具 (Parametric UMAP 3D 版本)

核心優勢：
  - 使用 Parametric UMAP (神經網絡降維)，訓練完成後座標系「永久固定」
  - 新圖片可直接推論插入，不影響既有點位（解決穩定性-可塑性兩難）
  - 內建 K 近鄰殘差偵測，用顏色與大小標示 AI 難以歸類的「孤兒點」
  - 修正原版對 PNG (RGBA) 無法預覽的問題

依賴套件：
  pip install umap-learn[parametric] tensorflow scikit-learn plotly pandas Pillow
"""

import os
import sqlite3
import numpy as np
import pandas as pd
from PIL import Image
from io import BytesIO
import base64
import plotly.express as px

# ─── 設定常數 ──────────────────────────────────────────────────────────────────

DB_PATH = "images.db"

# Parametric UMAP Encoder (Keras SavedModel) 的儲存路徑
# 訓練完成後，未來所有執行都只使用這個固定模型
ENCODER_SAVE_PATH = "models/parametric_umap_encoder.keras"

THUMB_SIZE  = (80, 80)   # 懸浮視窗縮圖尺寸 (不要太大，否則 HTML 會很肥)
OUTPUT_FILE = "latent_space_3d.html"

N_COMPONENTS     = 3    # 降維目標維度：3D
K_NEIGHBORS_UMAP = 15   # UMAP 訓練時的 n_neighbors 超參數
K_RESIDUAL       = 15   # 殘差計算使用的 K 近鄰數 (建議與 UMAP 相同)


# ─── 工具函式 ──────────────────────────────────────────────────────────────────

def get_image_base64(path: str) -> str | None:
    """
    將圖片讀取並壓縮為 Base64 JPEG 字串，嵌入 HTML 用。

    修正原版問題：
      PNG 含透明通道 (RGBA/P/LA) 直接存 JPEG 會報錯或顯示全黑。
      解法：先合成純白背景，再轉 JPEG，確保任何格式的圖片都能正常預覽。
    """
    try:
        if not os.path.exists(path):
            return None

        with Image.open(path) as img:
            img.thumbnail(THUMB_SIZE)

            # 若圖片有透明通道，先合成白色背景再轉 RGB
            if img.mode in ("RGBA", "LA", "P"):
                # P (調色盤模式) 可能含透明資訊，先轉 RGBA 確保正確
                img_rgba = img.convert("RGBA")
                background = Image.new("RGB", img_rgba.size, (255, 255, 255))
                # split()[3] 取出 alpha 通道作為合成遮罩
                background.paste(img_rgba, mask=img_rgba.split()[3])
                img = background
            elif img.mode != "RGB":
                # 其他非標準模式 (如 CMYK、I、F) 直接轉 RGB
                img = img.convert("RGB")

            buffered = BytesIO()
            img.save(buffered, format="JPEG", quality=75)
            encoded = base64.b64encode(buffered.getvalue()).decode("utf-8")
            return f"data:image/jpeg;base64,{encoded}"

    except Exception as e:
        print(f"  ⚠️  無法處理圖片 {os.path.basename(path)}: {e}")
        return None


def compute_knn_residuals(
    X_high: np.ndarray,
    X_low:  np.ndarray,
    k:      int = 15,
) -> np.ndarray:
    """
    計算每個點的「降維殘差」——衡量其鄰域結構在高維與低維空間中的保留程度。

    演算法：K 近鄰 Jaccard 殘差
      1. 在高維空間 (cosine 距離) 找每個點的 K 個最近鄰
      2. 在低維空間 (euclidean 距離) 找每個點的 K 個最近鄰
      3. 計算兩組鄰居集合的 Jaccard 相似度
         Jaccard = |高維鄰居 ∩ 低維鄰居| / |高維鄰居 ∪ 低維鄰居|
      4. 殘差 = 1 - Jaccard  (越高 = 鄰域結構扭曲越嚴重 = 孤兒點)

    返回值：float32 陣列，範圍 [0, 1]，值越高代表降維越不可信。
    """
    from sklearn.neighbors import NearestNeighbors

    print("   計算高維空間 K 近鄰 (cosine)...")
    nn_high = NearestNeighbors(n_neighbors=k + 1, metric="cosine", n_jobs=-1)
    nn_high.fit(X_high)
    _, idx_high = nn_high.kneighbors(X_high)
    idx_high = idx_high[:, 1:]  # 第 0 欄是自身 (距離=0)，捨去

    print("   計算低維空間 K 近鄰 (euclidean)...")
    nn_low = NearestNeighbors(n_neighbors=k + 1, metric="euclidean", n_jobs=-1)
    nn_low.fit(X_low)
    _, idx_low = nn_low.kneighbors(X_low)
    idx_low = idx_low[:, 1:]  # 同上，捨去自身

    print("   計算 Jaccard 殘差...")
    n = len(X_high)
    residuals = np.empty(n, dtype=np.float32)
    for i in range(n):
        s_high = set(idx_high[i])
        s_low  = set(idx_low[i])
        # Jaccard 相似度 ∈ [0, 1]
        jaccard   = len(s_high & s_low) / len(s_high | s_low)
        residuals[i] = 1.0 - jaccard  # 殘差 ∈ [0, 1]

    return residuals


# ─── 自訂 JavaScript：3D 懸浮圖片預覽 ──────────────────────────────────────────

# 注入 HTML body 後的腳本；Plotly 的 post_script 參數會在圖表渲染後執行此段 JS
CUSTOM_JS = r"""
(function () {
    /* ── 建立懸浮視窗 DOM 元素 ── */
    var tooltip = document.createElement('div');
    tooltip.style.cssText = [
        'position:fixed',
        'display:none',
        'background:rgba(15,15,25,0.97)',
        'border:1px solid #7c3aed',
        'border-radius:10px',
        'padding:14px 16px',
        'color:#f0f0f0',
        'pointer-events:none',     /* 允許滑鼠穿透，不干擾 3D 旋轉 */
        'z-index:9999',
        'box-shadow:0 6px 28px rgba(124,58,237,0.45)',
        'max-width:360px',
        'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif'
    ].join(';');
    document.body.appendChild(tooltip);

    /* ── 懸浮視窗跟隨滑鼠 ── */
    window.addEventListener('mousemove', function (e) {
        if (tooltip.style.display === 'none') return;
        var x = e.clientX + 20;
        var y = e.clientY + 20;
        /* 防止超出視窗邊界 */
        if (x + 370 > window.innerWidth)  x = e.clientX - 370;
        if (y + 230 > window.innerHeight) y = e.clientY - 230;
        tooltip.style.left = x + 'px';
        tooltip.style.top  = y + 'px';
    });

    /* ── 等待 Plotly 圖表就緒後再綁定事件 ── */
    function bindEvents() {
        var plotDiv = document.getElementsByClassName('plotly-graph-div')[0];
        if (!plotDiv || !plotDiv.on) {
            setTimeout(bindEvents, 200);
            return;
        }

        /* Plotly hover：顯示懸浮視窗 */
        plotDiv.on('plotly_hover', function (eventData) {
            if (!eventData || !eventData.points || !eventData.points.length) return;

            var pt       = eventData.points[0];
            var cd       = pt.customdata;
            var imgSrc   = cd[0];             /* Base64 縮圖 */
            var filename = cd[1];             /* 檔案名稱 */
            var residual = parseFloat(cd[2]); /* 降維殘差 */

            /* 殘差顏色條：綠 (低) → 橙 → 紅 (高) */
            var hue   = Math.round((1.0 - Math.min(residual, 1.0)) * 120);
            var badge = residual > 0.5
                ? '<span style="background:#92400e;color:#fef3c7;font-size:10px;padding:1px 6px;border-radius:4px;margin-left:4px;">⚠ 孤兒點</span>'
                : '';

            /* 圖片預覽：有效 Base64 才顯示，否則顯示佔位框 */
            var imgHTML = (imgSrc && imgSrc !== '' && imgSrc !== 'NaN' && imgSrc.startsWith('data:'))
                ? '<img src="' + imgSrc + '" style="width:100px;height:100px;object-fit:contain;border-radius:6px;background:#1a1a2e;flex-shrink:0;">'
                : '<div style="width:100px;height:100px;background:#2a2a3e;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#666;font-size:10px;text-align:center;flex-shrink:0;">預覽不可用</div>';

            tooltip.innerHTML =
                '<div style="display:flex;align-items:flex-start;gap:12px;">' +
                    imgHTML +
                    '<div style="min-width:0;flex:1;">' +
                        '<div style="font-size:10px;color:#a78bfa;margin-bottom:2px;letter-spacing:.5px;">檔案名稱' + badge + '</div>' +
                        '<div style="font-size:12px;word-break:break-all;margin-bottom:10px;line-height:1.4;">' + filename + '</div>' +
                        '<div style="font-size:10px;color:#a78bfa;margin-bottom:2px;letter-spacing:.5px;">降維殘差</div>' +
                        '<div style="font-size:15px;font-weight:700;color:hsl(' + hue + ',80%,60%);">' +
                            residual.toFixed(4) + '</div>' +
                        '<div style="font-size:9px;color:#666;margin-top:2px;">' +
                            (residual > 0.5 ? '⚠ 鄰域結構扭曲嚴重，可信度低' : '鄰域結構保留良好') +
                        '</div>' +
                    '</div>' +
                '</div>';
            tooltip.style.display = 'block';
        });

        /* Plotly unhover：隱藏懸浮視窗 */
        plotDiv.on('plotly_unhover', function () {
            tooltip.style.display = 'none';
        });

        /* 點擊時在新分頁顯示原尺寸縮圖 (選用) */
        plotDiv.on('plotly_click', function (eventData) {
            if (!eventData || !eventData.points || !eventData.points.length) return;
            var cd = eventData.points[0].customdata;
            if (cd[0] && cd[0].startsWith('data:')) {
                var w = window.open('', '_blank');
                w.document.write(
                    '<!doctype html><html><body style="margin:0;background:#000;">' +
                    '<img src="' + cd[0] + '" style="max-width:100%;max-height:100vh;object-fit:contain;">' +
                    '<p style="color:#aaa;font-size:12px;text-align:center;padding:8px;">' + cd[1] + '</p>' +
                    '</body></html>'
                );
            }
        });
    }

    bindEvents();
})();
"""


# ─── 主程式 ────────────────────────────────────────────────────────────────────

def main():

    # ── 1. 讀取資料庫 ──────────────────────────────────────────────────────────
    print("🚀 正在讀取資料庫...")
    if not os.path.exists(DB_PATH):
        print(f"❌ 找不到資料庫：{DB_PATH}，請先執行 indexer.py 建立索引。")
        return

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT f.file_path, e.embedding
        FROM files f
        JOIN embeddings e ON f.id = e.file_id
    """)
    data = cursor.fetchall()
    conn.close()

    if not data:
        print("❌ 資料庫是空的！請先執行 indexer.py 建立索引。")
        return

    print(f"📊 載入 {len(data)} 筆資料，正在解析向量...")

    paths, filenames, embeddings = [], [], []
    for path, blob in data:
        # np.frombuffer 回傳的是唯讀 view，加 .copy() 轉為可寫陣列
        emb = np.frombuffer(blob, dtype=np.float32).copy()
        paths.append(path)
        filenames.append(os.path.basename(path))
        embeddings.append(emb)

    X = np.array(embeddings, dtype=np.float32)
    print(f"   向量矩陣尺寸：{X.shape}  (樣本數 × 維度)")

    # ── 2. 延遲匯入 TensorFlow 與 ParametricUMAP ───────────────────────────────
    # 在這裡才匯入，以便在缺套件時給出明確的錯誤訊息
    try:
        # 抑制 TensorFlow 多餘的 INFO / WARNING 日誌
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
        import tensorflow as tf
        from umap.parametric_umap import ParametricUMAP
    except ImportError as e:
        print(f"❌ 缺少必要套件：{e}")
        print("   請執行：pip install umap-learn[parametric] tensorflow")
        return

    # 設定全域隨機種子（盡量提升 GPU 上的可重現性）
    tf.random.set_seed(42)

    # ── 3. Parametric UMAP：訓練模式 或 推理模式 ──────────────────────────────
    if os.path.exists(ENCODER_SAVE_PATH):
        # ── [推理模式] Encoder 已存在 → 直接推論，舊點座標完全不動 ─────────────
        print(f"\n✅  找到已訓練的 Encoder：{ENCODER_SAVE_PATH}")
        print("🔮  [推理模式] 直接推論，保持座標系穩定不變...")

        # compile=False：跳過優化器重建（推論不需要），也可避免自訂 loss 的序列化問題
        encoder = tf.keras.models.load_model(ENCODER_SAVE_PATH, compile=False)

        # 檢查模型輸入維度與當前資料是否相符
        expected_dim = encoder.input_shape[-1]
        if expected_dim != X.shape[1]:
            print(f"❌  模型期望輸入維度 ({expected_dim}) 與資料維度 ({X.shape[1]}) 不符！")
            print(f"   若你更換了 CLIP 模型或資料庫，請刪除舊模型後重新訓練：")
            print(f"   rmdir /s /q \"{ENCODER_SAVE_PATH}\"")
            return

        # 推論：輸出 shape = (N, N_COMPONENTS)
        projections = encoder.predict(X, batch_size=256, verbose=1)
        print(f"   推論完成，共 {len(projections)} 個點。")

    else:
        # ── [訓練模式] 從零開始訓練，完成後儲存供未來使用 ─────────────────────
        print(f"\n⚠️   未找到已訓練模型，進入訓練模式（首次執行需要幾分鐘）...")
        print("🧠  [訓練模式] 訓練 Parametric UMAP Encoder (n_components=3)...")

        # batch_size：確保不超過樣本總數的 1/4，且在合理範圍內
        batch_size = min(128, max(8, len(X) // 4))

        reducer = ParametricUMAP(
            n_components=N_COMPONENTS,
            n_neighbors=K_NEIGHBORS_UMAP,
            metric="cosine",
            random_state=42,     # 盡量保持可重現（CPU 上有效，GPU 僅供參考）
            verbose=True,
            batch_size=batch_size,
        )
        projections = reducer.fit_transform(X)

        # 儲存 Encoder（Keras SavedModel 格式，會建立一個資料夾）
        os.makedirs("models", exist_ok=True)
        print(f"\n💾  儲存 Encoder 至 {ENCODER_SAVE_PATH} ...")
        reducer.encoder.save(ENCODER_SAVE_PATH)
        print("   ✅  儲存完成！未來執行將直接使用此模型，座標系固定不變。")

    # projections 確保為 float32 的 (N, 3) 陣列
    projections = np.array(projections, dtype=np.float32)

    # ── 4. 殘差/異常偵測 ───────────────────────────────────────────────────────
    print("\n🔬  計算降維殘差（K 近鄰 Jaccard 法）...")

    # 當樣本數很少時，K 不能超過 N-1
    actual_k    = min(K_RESIDUAL, len(X) - 1)
    residuals   = compute_knn_residuals(X, projections, k=actual_k)
    residuals   = np.clip(residuals, 0.0, 1.0)

    n_anomaly   = int((residuals > 0.5).sum())
    print(f"   殘差統計：min={residuals.min():.3f}, "
          f"mean={residuals.mean():.3f}, max={residuals.max():.3f}")
    print(f"   高殘差孤兒點（>0.5）：{n_anomaly} 個 "
          f"({n_anomaly / len(X) * 100:.1f}%)")

    # ── 5. 生成縮圖 ─────────────────────────────────────────────────────────
    print("\n🖼️   正在生成縮圖（Base64 編碼，這可能需要一點時間）...")
    images_b64 = [get_image_base64(p) or "" for p in paths]
    valid_cnt  = sum(1 for s in images_b64 if s)
    print(f"   成功：{valid_cnt} / {len(paths)} 張")

    # ── 6. 建立 DataFrame ──────────────────────────────────────────────────
    df = pd.DataFrame({
        "x":           projections[:, 0],
        "y":           projections[:, 1],
        "z":           projections[:, 2],
        "filename":    filenames,
        "path":        paths,
        "residual":    residuals,
        # marker 大小：殘差越高點越大，讓孤兒點更顯眼，最小 2 避免點消失
        "marker_size": (2.0 + residuals * 9.0).astype(np.float32),
        "image":       images_b64,
    })

    # ── 7. 繪製 3D 散點圖 ──────────────────────────────────────────────────
    print("\n✨  正在繪製 3D 向量空間圖...")

    fig = px.scatter_3d(
        df,
        x="x", y="y", z="z",

        # 用殘差值著色：plasma 色階 → 深紫 (低殘差) → 亮黃 (高殘差孤兒點)
        color="residual",
        color_continuous_scale="plasma",
        range_color=[0.0, 1.0],

        # 用點大小標示殘差程度
        size="marker_size",
        size_max=12,

        # 將縮圖、檔名、殘差塞入 custom_data 供 JS 讀取
        custom_data=["image", "filename", "residual"],

        title="EyeSeeMore — AI Image Latent Space　(Parametric UMAP 3D)",
        template="plotly_dark",
        labels={"residual": "降維殘差"},
        opacity=0.88,
    )

    fig.update_traces(
        # 關閉 Plotly 預設的 SVG 提示框，完全交給自訂 JS
        hoverinfo="none",
        hovertemplate=None,
    )

    fig.update_layout(
        scene=dict(
            xaxis_title="UMAP-1",
            yaxis_title="UMAP-2",
            zaxis_title="UMAP-3",
            bgcolor="rgb(12,12,20)",
            xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.07)"),
            yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.07)"),
            zaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.07)"),
        ),
        coloraxis_colorbar=dict(
            title="降維殘差",
            tickformat=".2f",
            tickfont=dict(size=11),
        ),
        paper_bgcolor="rgb(12,12,20)",
        font_color="white",
        margin=dict(l=0, r=0, b=0, t=45),
        width=1440,
        height=920,
    )

    # ── 8. 注入自訂 JS 並匯出 HTML ─────────────────────────────────────────
    fig.write_html(OUTPUT_FILE, post_script=CUSTOM_JS, include_plotlyjs=True)

    print(f"\n🎉  完成！請用瀏覽器開啟：{OUTPUT_FILE}")
    print(f"   共 {len(df)} 個點，孤兒點（殘差>0.5）：{n_anomaly} 個")
    print(f"\n   色彩說明：深紫 → 低殘差（鄰域保留良好）")
    print(f"             亮黃 → 高殘差（孤兒點，AI 難以歸類）")


if __name__ == "__main__":
    main()
