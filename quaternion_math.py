"""
quaternion_math.py — 單位四元數運算(姿態唯一來源,禁用 Euler 角)
=====================================================================
分量順序固定為 (w, i, j, k);所有函式皆以 numpy 陣列 [w, x, y, z] 表示。
零依賴(僅 numpy),供 SolidWorks 規格軌道相機與點雲視覺化共用,亦可單獨單元測試。

慣例對齊:`multiply` 與 `to_matrix` 刻意與 vispy.util.quaternion.Quaternion 的
`__mul__` / `get_matrix` 完全一致,確保接到 VisPy 相機後旋轉方向正確(見對應單元測試)。
"""

from __future__ import annotations

import numpy as np

IDENTITY = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def normalize(q) -> np.ndarray:
    """回傳單位長度四元數;零長度退化為單位四元數(不拋例外)。"""
    q = np.asarray(q, dtype=np.float64)
    n = float(np.linalg.norm(q))
    if n < 1e-15:
        return IDENTITY.copy()
    return q / n


def canonical(q) -> np.ndarray:
    """q 與 -q 表示同一姿態;統一取 w >= 0 的代表,便於比較。"""
    q = normalize(q)
    return -q if q[0] < 0.0 else q


def multiply(a, b) -> np.ndarray:
    """Hamilton 乘積 a ⊗ b(與 vispy Quaternion.__mul__ 同序)。"""
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by + ay * bw + az * bx - ax * bz,
        aw * bz + az * bw + ax * by - ay * bx,
    ], dtype=np.float64)


def conjugate(q) -> np.ndarray:
    q = np.asarray(q, dtype=np.float64)
    return np.array([q[0], -q[1], -q[2], -q[3]], dtype=np.float64)


def inverse(q) -> np.ndarray:
    """單位四元數的逆即共軛。"""
    return conjugate(normalize(q))


def from_axis_angle(axis, angle_rad: float) -> np.ndarray:
    """由旋轉軸(會自動正規化)與角度(弧度)建立四元數。"""
    axis = np.asarray(axis, dtype=np.float64)
    n = float(np.linalg.norm(axis))
    if n < 1e-15:
        return IDENTITY.copy()
    axis = axis / n
    h = 0.5 * float(angle_rad)
    s = np.sin(h)
    return np.array([np.cos(h), axis[0] * s, axis[1] * s, axis[2] * s], dtype=np.float64)


def axis_angle(q):
    """回傳 (angle_rad, ax, ay, az);與 vispy Quaternion.get_axis_angle 一致。"""
    q = normalize(q)
    w, x, y, z = q
    angle = 2.0 * np.arccos(max(min(float(w), 1.0), -1.0))
    scale = float(np.sqrt(x * x + y * y + z * z))
    if scale > 1e-12:
        return angle, x / scale, y / scale, z / scale
    return angle, 1.0, 0.0, 0.0


def to_matrix(q) -> np.ndarray:
    """4x4 旋轉矩陣(佈局與 vispy Quaternion.get_matrix 一致,供驗證/除錯)。"""
    w, x, y, z = normalize(q)
    a = np.zeros((4, 4), dtype=np.float64)
    a[0, 0] = -2.0 * (y * y + z * z) + 1.0
    a[1, 0] = +2.0 * (x * y + z * w)
    a[2, 0] = +2.0 * (x * z - y * w)
    a[0, 1] = +2.0 * (x * y - z * w)
    a[1, 1] = -2.0 * (x * x + z * z) + 1.0
    a[2, 1] = +2.0 * (z * y + x * w)
    a[0, 2] = +2.0 * (x * z + y * w)
    a[1, 2] = +2.0 * (y * z - x * w)
    a[2, 2] = -2.0 * (x * x + y * y) + 1.0
    a[3, 3] = 1.0
    return a


def rotate_vector(q, v) -> np.ndarray:
    """以 q 旋轉 3D 向量 v(用於測試:驗證 trackball Δq 把 a 轉到 b)。"""
    v = np.asarray(v, dtype=np.float64)
    p = np.array([0.0, v[0], v[1], v[2]], dtype=np.float64)
    r = multiply(multiply(normalize(q), p), inverse(q))
    return r[1:]


# ──────────────────────────────────────────────────────────────────────
#  Virtual trackball(球內球面、球外雙曲面,讓邊緣 roll 平滑)
# ──────────────────────────────────────────────────────────────────────
def trackball_project(x: float, y: float) -> np.ndarray:
    """把已正規化到 [-1,1] 的螢幕點映射到虛擬球上的 3D 點。

        r² = x²+y²
        z = sqrt(1-r²)      if r² ≤ 0.5
        z = 0.5 / sqrt(r²)  otherwise
    """
    r2 = x * x + y * y
    if r2 <= 0.5:
        z = np.sqrt(1.0 - r2)
    else:
        z = 0.5 / np.sqrt(r2)
    return np.array([x, y, z], dtype=np.float64)


def trackball_delta(a, b) -> np.ndarray:
    """由球上起點 a、現點 b 取最短弧的旋轉四元數 Δq(shortest-arc)。

        d = dot(â, b̂);  axis = cross(â, b̂)
        Δq = normalize( (1+d, axis.x, axis.y, axis.z) )
        d→1 退化為單位四元數;d→-1 取任意正交軸補 180°。
    """
    a = normalize3(a)
    b = normalize3(b)
    d = float(np.dot(a, b))
    if d > 1.0 - 1e-9:
        return IDENTITY.copy()
    if d < -1.0 + 1e-9:
        # 反向:繞任一與 a 正交的軸轉 180°
        axis = np.cross(a, np.array([1.0, 0.0, 0.0]))
        if float(np.linalg.norm(axis)) < 1e-6:
            axis = np.cross(a, np.array([0.0, 1.0, 0.0]))
        axis = normalize3(axis)
        return np.array([0.0, axis[0], axis[1], axis[2]], dtype=np.float64)
    axis = np.cross(a, b)
    return normalize(np.array([1.0 + d, axis[0], axis[1], axis[2]], dtype=np.float64))


def normalize3(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-15 else np.array([0.0, 0.0, 1.0])


# ──────────────────────────────────────────────────────────────────────
#  SLERP(view cube / 標準視角 / 搜尋飛行共用)
# ──────────────────────────────────────────────────────────────────────
def slerp(q0, q1, t: float) -> np.ndarray:
    """球面線性插值;走最短路徑,近平行時退化為 nlerp。"""
    q0 = normalize(q0)
    q1 = normalize(q1)
    cos = float(np.dot(q0, q1))
    if cos < 0.0:          # 短路徑:q1 與 -q1 同姿態,取夾角較小者
        q1 = -q1
        cos = -cos
    if cos > 0.9995:       # 近平行退化:線性插值再正規化
        return normalize(q0 + t * (q1 - q0))
    omega = np.arccos(max(min(cos, 1.0), -1.0))
    so = np.sin(omega)
    return (np.sin((1.0 - t) * omega) * q0 + np.sin(t * omega) * q1) / so
