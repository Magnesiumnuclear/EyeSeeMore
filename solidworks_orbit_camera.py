"""
solidworks_orbit_camera.py — SolidWorks 規格的 VisPy 四元數軌道相機
====================================================================
可嵌入 VisPy SceneCanvas 的軌道相機,姿態全程以單位四元數表示(禁用 Euler 角)。
subclass vispy 的 Base3DRotationCamera(屬 PerspectiveCamera),override
viewbox_mouse_event / viewbox_key_event。

姿態狀態(唯一來源)
  q     : 單位四元數 (w,i,j,k),初始 (1,0,0,0)
  pivot : 旋轉中心(對應 vispy 的 self.center)
  dist  : 縮放(對應 vispy 的 self.scale_factor;fov>0 時換算成實際相機距離)
相機位置由狀態推導。旋轉矩陣由 q 的 axis-angle 經 vispy transforms.rotate 注入
(_get_rotation_tr),沿用 ArcballCamera 的 (x,z,y) 軸慣例,確保渲染方向正確。

約束:
  • 相機只改 view matrix,絕不觸碰任何 per-point buffer(旋轉 = 零資料傳輸)。
  • animate_to 進行中收到任何使用者輸入立即中斷,切回手動。
  • 不引入 Euler、不用 look-at 重算姿態繞過 q。
"""

from __future__ import annotations

import math
import time

import numpy as np

from vispy.scene.cameras.perspective import Base3DRotationCamera
from vispy.scene.cameras.base_camera import BaseCamera
from vispy.util import keys, transforms
from vispy.visuals.transforms import MatrixTransform

import quaternion_math as Q

_S = 0.70710678118654752  # 1/√2


# 標準視角(Y up 慣例,號數視 look 方向校正;Iso 於 __init__ 動態算出)
STANDARD_VIEWS = {
    "front": np.array([1.0, 0.0, 0.0, 0.0]),
    "right": np.array([_S, 0.0, _S, 0.0]),
    "top":   np.array([_S, -_S, 0.0, 0.0]),
    "back":  Q.multiply((0.0, 0.0, 1.0, 0.0), (1.0, 0.0, 0.0, 0.0)),
    "left":  np.array([_S, 0.0, -_S, 0.0]),
    "bottom": np.array([_S, _S, 0.0, 0.0]),
}


class SolidWorksCamera(Base3DRotationCamera):
    """SolidWorks 風格的四元數軌道相機。

    鍵鼠映射(操作 → 行為):
      MMB 拖              : arcball 旋轉(virtual trackball,shortest-arc)
      Ctrl + MMB 拖       : pan(沿相機 right/up 平移 pivot)
      Shift + MMB / 滾輪  : zoom(改 dist;滾輪為 zoom-to-cursor)
      Alt + MMB 拖        : roll(繞視軸)
      MMB 點實體後旋轉    : 由 viewer 呼叫 set_pivot() 改旋轉中心
      方向鍵 / Shift / Alt / Ctrl + 方向鍵 : 固定增量 旋轉 / 90°步進 / roll / pan
    """

    # vispy Qt 後端按鈕碼:left=1, right=2, middle=3
    MMB = 3

    def __init__(self, fov=45.0, distance=None, translate_speed=1.0,
                 key_step_deg=15.0, **kwargs):
        super().__init__(fov=fov, **kwargs)
        # ── 姿態唯一來源 ──
        self.q = Q.IDENTITY.copy()
        self.distance = distance
        self.translate_speed = translate_speed
        self.key_step_deg = float(key_step_deg)

        # ── 手性/慣例校正旋鈕(以實測對齊 SolidWorks,不硬套單一公式) ──
        self.screen_y_sign = 1.0      # 螢幕 y 軸正負(trackball)
        # 中鍵 arcball 旋轉方向:實測 SolidWorks 與「抓住模型拖曳」式 arcball 相反,
        # 故預設反轉(對 Δq 取共軛 = 反向旋轉)。要切回原向把這設 False 即可。
        self.invert_orbit = True
        self.roll_axis = np.array([0.0, 0.0, 1.0])  # 視軸(roll 用)
        self.zoom_drag_factor = 0.0015
        self.key_yaw_axis = np.array([0.0, 1.0, 0.0])    # 左右鍵繞螢幕垂直軸
        self.key_pitch_axis = np.array([1.0, 0.0, 0.0])  # 上下鍵繞螢幕水平軸

        # ── 拖曳起點快照(絕對式,避免累積漂移) ──
        self._q0 = None
        self._center0 = None
        self._sf0 = None
        self._dist0 = None
        self._press_pos = None

        # ── 動畫狀態 ──
        self._anim = None
        self._timer = None

        # Iso = q_x(35.264°) ⊗ q_y(-45°)   # 35.264° = atan(1/√2)
        iso = Q.multiply(
            Q.from_axis_angle((1, 0, 0), math.radians(35.264)),
            Q.from_axis_angle((0, 1, 0), math.radians(-45.0)),
        )
        self._iso = Q.normalize(iso)

    # ==================================================================
    #  姿態 → view matrix(注入 Base3DRotationCamera 的組裝流程)
    # ==================================================================
    def set_q(self, q, *, update=True):
        """直接設定姿態四元數(會 normalize)。"""
        self.q = Q.normalize(q)
        if update:
            self.view_changed()

    def set_pivot(self, point, *, update=True):
        """改旋轉中心為世界座標 point(供 viewer 在 MMB 命中實體後呼叫)。

        注意:相機本身不做 picking、不讀 per-point buffer;命中點由 viewer 提供。
        """
        self.center = tuple(float(c) for c in point)  # PerspectiveCamera.center setter 會觸發更新
        if update:
            self.view_changed()

    def _get_rotation_tr(self):
        # 由 q 的 axis-angle 經 vispy transforms.rotate 注入;(x,z,y) 沿用 ArcballCamera 慣例
        rot, x, y, z = Q.axis_angle(self.q)
        return transforms.rotate(math.degrees(rot), (x, z, y))

    def _dist_to_trans(self, dist):
        rot, x, y, z = Q.axis_angle(self.q)
        tr = MatrixTransform()
        tr.rotate(math.degrees(rot), (x, y, z))
        dx, dz, dy = np.dot(tr.matrix[:3, :3],
                            (dist[0], dist[1], 0.0)) * self.translate_speed
        return dx, dy, dz

    def _get_dim_vectors(self):
        # 與 ArcballCamera 一致:相機沒有「up」概念,旋轉全由 q 決定
        return np.eye(3)[::-1]

    # ==================================================================
    #  滑鼠事件(SolidWorks 映射)
    # ==================================================================
    def viewbox_mouse_event(self, event):
        if event.handled or not self.interactive:
            return

        # 任何使用者輸入立即中斷動畫,切回手動
        if event.type in ("mouse_press", "mouse_move", "mouse_wheel"):
            self._stop_animation()

        if event.type == "mouse_wheel":
            self._zoom_to_cursor(event.pos, 1.1 ** (-event.delta[1]))
            event.handled = True
            return

        if event.type == "mouse_press":
            self._snapshot()
            self._press_pos = np.array(event.pos[:2], dtype=np.float64)
            event.handled = True
            return

        if event.type == "mouse_release":
            self._snapshot_clear()
            return

        if event.type == "mouse_move":
            if event.press_event is None or self.MMB not in event.buttons:
                return
            mods = event.mouse_event.modifiers
            p2 = np.array(event.mouse_event.pos[:2], dtype=np.float64)
            if keys.CONTROL in mods:
                self._do_pan(p2)
            elif keys.SHIFT in mods:
                self._do_zoom_drag(p2)
            elif keys.ALT in mods:
                self._do_roll(p2)
            else:
                self._do_arcball(p2)
            event.handled = True

    # ── 拖曳起點快照 ──
    def _snapshot(self):
        self._q0 = self.q.copy()
        self._center0 = np.array(self.center, dtype=np.float64)
        self._sf0 = float(self._scale_factor)
        self._dist0 = None if self._distance is None else float(self._distance)

    def _snapshot_clear(self):
        self._q0 = self._center0 = self._sf0 = self._dist0 = self._press_pos = None

    # ── 螢幕點 → 虛擬球 ──
    def _ball(self, p):
        w, h = self._viewbox.size
        m = min(w, h)
        x = (2.0 * p[0] - w) / m
        y = self.screen_y_sign * (h - 2.0 * p[1]) / m
        return Q.trackball_project(x, y)

    # ── arcball 旋轉:Δq = trackball(press→now),pre-multiply q = Δq ⊗ q0 ──
    def _do_arcball(self, p2):
        a = self._ball(self._press_pos)
        b = self._ball(p2)
        dq = Q.trackball_delta(a, b)
        if self.invert_orbit:          # 反向以對齊 SolidWorks(共軛 = 反轉旋轉)
            dq = Q.conjugate(dq)
        self.q = Q.normalize(Q.multiply(dq, self._q0))
        self.view_changed()

    # ── roll:繞視軸 Z,q = q_roll ⊗ q0 ──
    def _do_roll(self, p2):
        w, h = self._viewbox.size
        c = np.array([w / 2.0, h / 2.0])
        a1 = math.atan2(self._press_pos[1] - c[1], self._press_pos[0] - c[0])
        a2 = math.atan2(p2[1] - c[1], p2[0] - c[0])
        qr = Q.from_axis_angle(self.roll_axis, (a1 - a2))
        self.q = Q.normalize(Q.multiply(qr, self._q0))
        self.view_changed()

    # ── pan:沿相機 right/up 平移 pivot(沿用 Base3DRotationCamera 的換算) ──
    def _do_pan(self, p2):
        norm = np.mean(self._viewbox.size)
        dist = (self._press_pos - p2) / norm * self._sf0
        dist[1] *= -1
        dx, dy, dz = self._dist_to_trans(dist)
        up, forward, right = self._get_dim_vectors()
        dx, dy, dz = right * dx + forward * dy + up * dz
        ff = self._flip_factors
        dx, dy, dz = ff[0] * dx, ff[1] * dy, dz * ff[2]
        self.center = (self._center0[0] + dx, self._center0[1] + dy, self._center0[2] + dz)

    # ── zoom(Shift+MMB 拖):改 dist ──
    def _do_zoom_drag(self, p2):
        dy = p2[1] - self._press_pos[1]
        zoom = (1.0 + self.zoom_drag_factor) ** dy
        self.scale_factor = self._sf0 * zoom
        if self._dist0 is not None:
            self._distance = self._dist0 * zoom
        self.view_changed()

    # ── 滾輪 zoom-to-cursor:縮放並把 pivot 朝游標方向位移,使游標下的點近似不動 ──
    def _zoom_to_cursor(self, pos, s):
        w, h = self._viewbox.size
        off = np.array([pos[0] - w / 2.0, pos[1] - h / 2.0], dtype=np.float64)
        norm = np.mean((w, h))
        dist = off / norm * self._scale_factor
        dist[1] *= -1
        dx, dy, dz = self._dist_to_trans(dist)
        up, forward, right = self._get_dim_vectors()
        dx, dy, dz = right * dx + forward * dy + up * dz
        ff = self._flip_factors
        dx, dy, dz = ff[0] * dx, ff[1] * dy, dz * ff[2]
        k = (1.0 - s)
        c = self.center
        self._scale_factor *= s
        if self._distance is not None:
            self._distance *= s
        self.center = (c[0] + k * dx, c[1] + k * dy, c[2] + k * dz)
        self.view_changed()

    # ==================================================================
    #  鍵盤事件(方向鍵固定增量,一律組固定角 Δq 後 ⊗ q)
    # ==================================================================
    def viewbox_key_event(self, event):
        BaseCamera.viewbox_key_event(self, event)
        if event.type != "key_press":
            return
        k = event.key
        if k not in (keys.LEFT, keys.RIGHT, keys.UP, keys.DOWN):
            return
        self._stop_animation()
        mods = event.modifiers
        step = math.radians(90.0 if keys.SHIFT in mods else self.key_step_deg)

        if keys.ALT in mods:
            sign = +1.0 if k in (keys.RIGHT, keys.UP) else -1.0
            dq = Q.from_axis_angle(self.roll_axis, sign * step)
            self.q = Q.normalize(Q.multiply(dq, self.q))
        elif keys.CONTROL in mods:
            self._key_pan(k, step)
            return
        else:
            if k in (keys.LEFT, keys.RIGHT):
                sign = +1.0 if k == keys.RIGHT else -1.0
                dq = Q.from_axis_angle(self.key_yaw_axis, sign * step)
            else:
                sign = +1.0 if k == keys.UP else -1.0
                dq = Q.from_axis_angle(self.key_pitch_axis, sign * step)
            self.q = Q.normalize(Q.multiply(dq, self.q))
        self.view_changed()

    def _key_pan(self, k, step):
        # 固定增量平移 pivot(以螢幕比例換算的小步)
        amount = self._scale_factor * 0.08
        sx = (+1.0 if k == keys.RIGHT else -1.0 if k == keys.LEFT else 0.0)
        sy = (+1.0 if k == keys.UP else -1.0 if k == keys.DOWN else 0.0)
        dx, dy, dz = self._dist_to_trans(np.array([sx * amount, sy * amount]))
        up, forward, right = self._get_dim_vectors()
        dx, dy, dz = right * dx + forward * dy + up * dz
        ff = self._flip_factors
        c = self.center
        self.center = (c[0] + ff[0] * dx, c[1] + ff[1] * dy, c[2] + ff[2] * dz)

    # ==================================================================
    #  標準視角 / fly-to → SLERP 動畫
    # ==================================================================
    def view_standard(self, name, *, animate=True):
        q = self._iso if name == "iso" else STANDARD_VIEWS[name]
        self.animate_to(q) if animate else self.set_q(q)

    def animate_to(self, q_target, pivot_target=None, dist_target=None,
                   duration=0.35):
        """飛行到目標姿態:q 走 SLERP,pivot/dist 走 ease-in-out。"""
        self._anim = {
            "q0": self.q.copy(),
            "q1": Q.normalize(q_target),
            "c0": np.array(self.center, dtype=np.float64),
            "c1": (np.array(self.center, dtype=np.float64) if pivot_target is None
                   else np.asarray(pivot_target, dtype=np.float64)),
            "s0": float(self._scale_factor),
            "s1": (float(self._scale_factor) if dist_target is None else float(dist_target)),
            "dur": max(1e-3, float(duration)),
            "t0": None,
        }
        if self._timer is None:
            from vispy.app import Timer
            self._timer = Timer(interval="auto", connect=self._on_tick, start=False)
        self._timer.start()

    def _on_tick(self, event):
        a = self._anim
        if a is None:
            if self._timer is not None:
                self._timer.stop()
            return
        if a["t0"] is None:
            a["t0"] = time.perf_counter()
        t = (time.perf_counter() - a["t0"]) / a["dur"]
        if t >= 1.0:
            t = 1.0
        te = _ease_in_out(t)
        # q 走 SLERP(線性參數,等角速度);pivot/dist 走 ease-in-out
        self.q = Q.slerp(a["q0"], a["q1"], t)
        self.center = tuple(a["c0"] + (a["c1"] - a["c0"]) * te)
        self.scale_factor = a["s0"] + (a["s1"] - a["s0"]) * te
        self.view_changed()
        if t >= 1.0:
            self._stop_animation()

    def _stop_animation(self):
        self._anim = None
        if self._timer is not None:
            self._timer.stop()


def _ease_in_out(t: float) -> float:
    """smoothstep:3t² − 2t³。"""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)
