"""
Test_Project_visualize_space_vispy.py — EyeSeeMore 潛在空間「原生」點雲檢視器(PyQt6 + VisPy)
================================================================================
取代原本的網頁(Plotly HTML)顯示,改用 VisPy SceneCanvas 即時繪製,搭配
SolidWorks 規格的四元數軌道相機(solidworks_orbit_camera.SolidWorksCamera)。

特色:
  • 相機姿態全程四元數,旋轉 50 萬點僅改 view matrix(零資料傳輸)。
  • MMB 拖曳 arcball、Ctrl/Shift/Alt+MMB = pan/zoom/roll、滾輪 zoom-to-cursor。
  • 數字鍵 1–6 標準視角、0 / I 等角視(皆 SLERP 飛行);方向鍵固定增量旋轉。
  • MMB 點擊點雲 → 該點設為旋轉中心(picking 在 viewer 端,相機不碰點資料)。

降維:預設用純 numpy 的 PCA-3(無額外相依);若已訓練 Parametric UMAP 且裝了
tensorflow 可加 --reduce umap。
用法:
    python Test_Project_visualize_space_vispy.py [--limit N] [--reduce pca|umap]
"""

import argparse
import os
import sqlite3
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ── 靜音第三方雜訊(務必在 import tensorflow / vispy(Qt) 之前設定才有效) ──
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")           # TF C++ 日誌只留 FATAL(含 oneDNN INFO)
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")          # 關 oneDNN → 移除其提示與 absl 前置 WARNING
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")  # 靜音 Qt 的 DPI「存取被拒」警告

# 避免在非 UTF-8 主控台(如 cp950)印 emoji 時崩潰
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB_PATH = os.path.join(ROOT, "images.db")
ENCODER_SAVE_PATH = os.path.join(ROOT, "models", "parametric_umap_encoder.keras")

STANDARD_KEYS = {"1": "front", "2": "back", "3": "left",
                 "4": "right", "5": "top", "6": "bottom",
                 "0": "iso", "I": "iso"}


def load_embeddings(limit=None):
    if not os.path.exists(DB_PATH):
        print(f"❌ 找不到資料庫:{DB_PATH}(請先執行 indexer.py)")
        return None, None
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT f.file_path, e.embedding FROM files f "
        "JOIN embeddings e ON f.id = e.file_id").fetchall()
    conn.close()
    if not rows:
        print("❌ 資料庫沒有向量。")
        return None, None
    if limit:
        rows = rows[:limit]
    paths = [r[0] for r in rows]
    X = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows]).astype(np.float32)
    print(f"📊 載入 {X.shape[0]} 筆向量,維度 {X.shape[1]}")
    return paths, X


def reduce_pca3(X):
    """純 numpy PCA → 3D(零相依)。"""
    Xc = X - X.mean(axis=0, keepdims=True)
    # 經濟型 SVD;主成分為 Vt 的前 3 列
    _u, _s, vt = np.linalg.svd(Xc, full_matrices=False)
    return (Xc @ vt[:3].T).astype(np.float32)


def reduce_umap(X):
    if not os.path.exists(ENCODER_SAVE_PATH):
        print("⚠️  找不到 UMAP encoder,改用 PCA-3。")
        return reduce_pca3(X)
    try:
        import tensorflow as tf
        tf.get_logger().setLevel("ERROR")   # 靜音 Python 端 tf logger(如 GPU 不可用警告)
        enc = tf.keras.models.load_model(ENCODER_SAVE_PATH, compile=False)
        return np.asarray(enc.predict(X, batch_size=256, verbose=0), dtype=np.float32)
    except Exception as e:
        print(f"⚠️  UMAP 推論失敗({e}),改用 PCA-3。")
        return reduce_pca3(X)


def position_colors(P):
    """以空間位置映射成 RGB(零相依的好看著色)。"""
    lo, hi = P.min(axis=0), P.max(axis=0)
    span = np.where(hi - lo < 1e-6, 1.0, hi - lo)
    rgb = (P - lo) / span
    rgba = np.ones((len(P), 4), dtype=np.float32)
    rgba[:, :3] = (0.25 + 0.7 * rgb).astype(np.float32)
    return rgba


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="只取前 N 點(加速)")
    ap.add_argument("--reduce", choices=["pca", "umap"], default="pca")
    args = ap.parse_args()

    paths, X = load_embeddings(args.limit)
    if X is None:
        return

    print(f"🔻 降維({args.reduce})...")
    P = reduce_umap(X) if args.reduce == "umap" else reduce_pca3(X)
    # 置中並縮放到合理尺度
    P = P - P.mean(axis=0, keepdims=True)
    radius = float(np.linalg.norm(P, axis=1).max()) or 1.0
    P = (P / radius * 5.0).astype(np.float32)
    colors = position_colors(P)

    # ── VisPy 場景 ──
    from vispy import scene, app
    app.use_app("pyqt6")
    from solidworks_orbit_camera import SolidWorksCamera

    canvas = scene.SceneCanvas(title="EyeSeeMore — Latent Space (VisPy / Quaternion Orbit)",
                               keys="interactive", bgcolor="#0c0c14",
                               size=(1280, 860), show=True)
    view = canvas.central_widget.add_view()
    markers = scene.visuals.Markers(parent=view.scene)
    markers.set_data(P, face_color=colors, size=6, edge_width=0)

    cam = SolidWorksCamera(fov=45.0)
    view.camera = cam
    cam.center = (0.0, 0.0, 0.0)
    cam.scale_factor = 14.0
    cam.view_standard("iso", animate=False)

    # ── 方位儀(orientation gizmo):固定在右下角的 XYZ triad，隨視角旋轉但定位不動 ──
    # 用獨立的小 ViewBox + 自己的正交相機,姿態與主相機 q 同步。
    GIZ = 130  # 像素
    gizmo = scene.widgets.ViewBox(parent=canvas.scene)
    gizmo.interactive = False          # 不吃滑鼠事件
    gizmo.bgcolor = None               # 透明,疊在主畫面上
    gizmo_cam = SolidWorksCamera(fov=0.0)   # 正交,無透視變形
    gizmo.camera = gizmo_cam
    gizmo_cam.center = (0.0, 0.0, 0.0)
    gizmo_cam.scale_factor = 3.0
    scene.visuals.XYZAxis(parent=gizmo.scene)

    def _place_gizmo(ev=None):
        w, h = canvas.size
        gizmo.pos = (w - GIZ, h - GIZ)   # 畫布 (0,0) 在左上,故右下角 = (W-GIZ, H-GIZ)
        gizmo.size = (GIZ, GIZ)
    _place_gizmo()
    canvas.events.resize.connect(_place_gizmo)

    # 主相機姿態變動時才同步方位儀(q 沒變就不更新,避免閒置時忙重繪)
    _last = {"q": None}

    @canvas.events.draw.connect
    def _sync_gizmo(ev):
        if _last["q"] is None or not np.array_equal(_last["q"], cam.q):
            gizmo_cam.set_q(cam.q)
            _last["q"] = cam.q.copy()
    gizmo_cam.set_q(cam.q)

    # ── 旋轉樞紐:中鍵按下時依「點雲在畫面中的可見比例」決定(取代舊的點擊 picking) ──
    #   可見比例 = 投影落在 viewport 內且在相機前方的點數 ÷ 總點數
    #     = 100%(整個點雲全在畫面內) → 點雲質心(本場景已置中於原點)
    #     < 100%(只要有任何點被裁到畫面外) → 游標 2D 最近點(相機前方)
    #   讀點資料只在此 callback(press 當下)發生一次;相機本身不碰 per-point buffer,
    #   拖曳旋轉過程零資料傳輸。
    PIVOT_VISIBLE_FRAC = 1.0    # 只有「整團點雲都在畫面內」才繞質心,否則一律繞游標最近點

    def _pivot_for_press(press_pos):
        tr = markers.get_transform("visual", "canvas")
        scr = tr.map(P)                       # (N,4) 齊次像素座標
        w = scr[:, 3]
        infront = w > 1e-6                    # 相機前方(w>0)
        denom = np.where(infront, w, 1.0)
        sx, sy = scr[:, 0] / denom, scr[:, 1] / denom
        W, H = canvas.size
        inview = infront & (sx >= 0) & (sx <= W) & (sy >= 0) & (sy <= H)
        frac = float(inview.sum()) / max(1, len(P))
        if frac >= PIVOT_VISIBLE_FRAC:
            return (0.0, 0.0, 0.0)            # 整體 → 質心(原點)
        cand = np.where(infront)[0]           # 局部 → 2D 最近點
        if cand.size == 0:
            return None
        d2 = (sx[cand] - press_pos[0]) ** 2 + (sy[cand] - press_pos[1]) ** 2
        return tuple(float(c) for c in P[cand[int(np.argmin(d2))]])

    cam.pivot_provider = _pivot_for_press

    # ── 旋轉中心標示:中鍵旋轉時在樞紐處顯示一個環(no-jump 下樞紐釘住,標示穩定不動) ──
    pivot_marker = scene.visuals.Markers(parent=view.scene)
    pivot_marker.visible = False
    pivot_marker.set_gl_state(depth_test=False, blend=True)   # 永遠畫在最上層,不被點遮住

    def _show_pivot(world_pt):
        pivot_marker.set_data(np.array([world_pt], dtype=np.float32),
                              face_color=(1, 1, 1, 0.0),            # 中空
                              edge_color=(1.0, 0.85, 0.1, 1.0),     # 亮黃環
                              size=22, edge_width=2.5, symbol="ring")
        pivot_marker.visible = True
        canvas.update()

    def _hide_pivot():
        pivot_marker.visible = False
        canvas.update()

    cam.on_orbit_begin = _show_pivot
    cam.on_orbit_end = _hide_pivot

    # ── 數字鍵標準視角(SLERP 飛行) ──
    @canvas.events.key_press.connect
    def _key(ev):
        name = STANDARD_KEYS.get(getattr(ev.key, "name", ""))
        if name:
            cam.view_standard(name, animate=True)

    
    app.run()


if __name__ == "__main__":
    main()
