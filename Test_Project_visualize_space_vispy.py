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

# ── 旋轉樞紐遲滯狀態機 + 調適面板 ──
SHOW_TUNING = True        # 程式內 True/False 控制右上調適面板顯示(調適用,非常駐)
PIVOT_FRAC_LOW = 0.90     # 低門檻:可見比例 < 此值 → 由「質心」切到「最近點」
PIVOT_FRAC_HIGH = 1.00    # 高門檻:可見比例 ≥ 此值 → 由「最近點」回到「質心」
TUNING_FACE = "Microsoft JhengHei UI"   # 面板字型(繁中);vispy 載不到時自動退回英文標籤


def _resolve_cjk_face(preferred=TUNING_FACE):
    """挑一個 vispy 能載入的 CJK 字型(回 face 名);全失敗回 None → 改用英文標籤。

    vispy 預設 OpenSans 無中文字形(會變方框),且部分字型(YaHei/SimSun)在
    vispy 的 freetype 載入器會丟 AssertionError——這裡先用 find_font 試解析,
    只回傳能成功解析的 face。
    """
    try:
        from vispy.util.fonts._win32 import find_font   # 僅 Windows 有
    except Exception:
        return None
    import warnings as _w
    for face in (preferred, "Microsoft JhengHei UI", "Microsoft JhengHei",
                 "MingLiU", "Noto Sans TC", "MS Gothic", "Yu Gothic UI"):
        try:
            with _w.catch_warnings():
                _w.simplefilter("ignore")
                if find_font(face, False, False):
                    return face
        except Exception:
            continue
    return None


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

    # ── 旋轉樞紐:遲滯狀態機(只在中鍵按下算一次,狀態在兩次按下之間保留) ──
    #   可見比例 = 投影落在 viewport 內且在相機前方的點數 ÷ 總點數
    #     [質心] ──(可見比例 < 低門檻)──▶ [最近點]
    #     [最近點] ──(可見比例 ≥ 高門檻)──▶ [質心]   ;低~高之間黏住當前狀態(遲滯)
    #   預設起始 = 質心;讀點資料只在此 callback(press 當下)發生一次,相機不碰
    #   per-point buffer,拖曳旋轉過程零資料傳輸。
    pivot_state = {"mode": "centroid", "low": PIVOT_FRAC_LOW,
                   "high": PIVOT_FRAC_HIGH, "last_frac": 1.0}

    # ── 右上調適面板(SHOW_TUNING 控制;非常駐)──
    #   逐行用獨立 pos 偏移繪製(vispy 多行 "\n" 的垂直錨點不可靠,會整塊跑出畫面);
    #   字型挑能載入的 CJK,找不到就退回英文標籤(預設字型無中文字形會變方框)。
    _face = _resolve_cjk_face() if SHOW_TUNING else None
    _cjk = _face is not None

    def _panel_lines():
        s = pivot_state
        if _cjk:
            mode = "質心" if s["mode"] == "centroid" else "最近點"
            return [f"旋轉中心: {mode}",
                    f"低門檻 {s['low'] * 100:.0f}%   高門檻 {s['high'] * 100:.0f}%",
                    f"上次可見 {s['last_frac'] * 100:.0f}%",
                    "[Z/X] 低門檻 -/+   [C/V] 高門檻 -/+"]
        mode = "CENTROID" if s["mode"] == "centroid" else "NEAREST"
        return [f"pivot: {mode}",
                f"low {s['low'] * 100:.0f}%   high {s['high'] * 100:.0f}%",
                f"visible {s['last_frac'] * 100:.0f}%",
                "[Z/X] low -/+   [C/V] high -/+"]

    tuning_text = None
    if SHOW_TUNING:
        from vispy.visuals.transforms import STTransform
        _TUNING_TOP = 48     # 距畫面頂端的留白(避開 Windows 標題列)
        _TUNING_LINE = 26    # 行距(px)
        # 每行相對偏移(右上角為基準,往下堆疊);STTransform 負責絕對定位
        _line_pos = np.array([[0, i * _TUNING_LINE] for i in range(4)],
                             dtype=np.float32)
        tuning_text = scene.visuals.Text(
            _panel_lines(), pos=_line_pos,
            color=(0.92, 0.92, 0.98, 1.0), font_size=9,
            face=(_face or "OpenSans"), bold=False,
            anchor_x="right", anchor_y="top", parent=canvas.scene)
        tuning_text.transform = STTransform()

        @canvas.events.resize.connect
        def _place_tuning(ev=None):
            tuning_text.transform.translate = (canvas.size[0] - 14, _TUNING_TOP, 0, 0)
        _place_tuning()

    def _update_tuning():
        if tuning_text is None:
            return
        tuning_text.text = _panel_lines()
        canvas.update()
    _update_tuning()

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
        pivot_state["last_frac"] = frac

        # 遲滯狀態轉移(只用兩個門檻;區間內維持原狀態)
        if pivot_state["mode"] == "centroid" and frac < pivot_state["low"]:
            pivot_state["mode"] = "nearest"
        elif pivot_state["mode"] == "nearest" and frac >= pivot_state["high"]:
            pivot_state["mode"] = "centroid"
        _update_tuning()

        if pivot_state["mode"] == "centroid":
            return (0.0, 0.0, 0.0)            # 質心(原點)
        cand = np.where(infront)[0]           # 最近點(相機前方,沿用舊算法)
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

    # ── 數字鍵標準視角(SLERP 飛行) + 調適面板門檻微調 ──
    @canvas.events.key_press.connect
    def _key(ev):
        name = getattr(ev.key, "name", "")
        std = STANDARD_KEYS.get(name)
        if std:
            cam.view_standard(std, animate=True)
            return
        if SHOW_TUNING and name in ("Z", "X", "C", "V"):
            step = 0.01
            if name == "Z":      # 低門檻 -
                pivot_state["low"] = max(0.0, pivot_state["low"] - step)
            elif name == "X":    # 低門檻 +(不超過高門檻)
                pivot_state["low"] = min(pivot_state["high"], pivot_state["low"] + step)
            elif name == "C":    # 高門檻 -(不低於低門檻)
                pivot_state["high"] = max(pivot_state["low"], pivot_state["high"] - step)
            elif name == "V":    # 高門檻 +
                pivot_state["high"] = min(1.0, pivot_state["high"] + step)
            _update_tuning()

    
    app.run()


if __name__ == "__main__":
    main()
