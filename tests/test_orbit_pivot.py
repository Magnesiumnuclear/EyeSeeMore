"""no-jump 繞樞紐旋轉的核心數學驗證(不需 GL/Qt)。

SolidWorksCamera 的 _do_arcball 用公式
    C_new = P − (P − C0) · R(q0)ᵀ · R(q_new)
讓世界樞紐 P 的「眼睛空間(平移前)位置」在整段拖曳中不變 → 畫面不跳、P 釘住。
這裡用相機相同的旋轉慣例(vispy transforms.rotate 的 (x,z,y) 軸)驗證該不變量。
"""

import math
import unittest

import numpy as np

from quaternion_math import (IDENTITY, axis_angle, from_axis_angle,  # noqa: F401
                             multiply, normalize)

try:
    from vispy.util import transforms as T  # 純 numpy 矩陣工具,不含 Qt
    HAS_VISPY = True
except Exception:
    HAS_VISPY = False

RNG = np.random.default_rng(7)


def _rq():
    q = RNG.standard_normal(4)
    return q / np.linalg.norm(q)


def _rot3(q):
    """與 SolidWorksCamera._rot3 完全相同的旋轉 3x3。"""
    a, x, y, z = axis_angle(q)
    return T.rotate(math.degrees(a), (x, z, y))[:3, :3]


@unittest.skipUnless(HAS_VISPY, "vispy 未安裝")
class TestOrbitPivotPinning(unittest.TestCase):
    def test_rot3_orthonormal(self):
        # 公式依賴 Rᵀ = R⁻¹(正交),這裡確認 vispy rotate 產生正交矩陣
        for _ in range(20):
            R = _rot3(_rq())
            np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-5)

    def test_pivot_pinned_in_eye_space(self):
        # no-jump 公式應使 P 的眼睛空間(平移前)位置在旋轉前後完全不變
        for _ in range(50):
            q0 = _rq()
            C0 = RNG.standard_normal(3) * 5.0
            P = RNG.standard_normal(3) * 5.0
            dq = from_axis_angle(RNG.standard_normal(3), RNG.uniform(0.1, 2.0))
            q_new = normalize(multiply(dq, q0))
            R0, Rn = _rot3(q0), _rot3(q_new)
            C_new = P - (P - C0) @ (R0.T @ Rn)
            eye_before = (P - C0) @ R0.T      # = (P−C0)·R(q0)⁻¹
            eye_after = (P - C_new) @ Rn.T     # = (P−C_new)·R(q_new)⁻¹
            np.testing.assert_allclose(eye_after, eye_before, atol=1e-7)

    def test_no_jump_at_drag_start(self):
        # 拖曳剛開始(q_new == q0)時 center 不應變動 → 不跳
        q0 = _rq()
        C0 = RNG.standard_normal(3) * 3.0
        P = RNG.standard_normal(3) * 3.0
        R0 = _rot3(q0)
        C_new = P - (P - C0) @ (R0.T @ R0)
        np.testing.assert_allclose(C_new, C0, atol=1e-9)

    def test_centroid_pivot_no_pan_stays_origin(self):
        # 樞紐 = 質心(原點)且未平移(C0=原點)時,旋轉中 center 恆為原點(正常繞心轉)
        P = np.zeros(3)
        C0 = np.zeros(3)
        for _ in range(10):
            q0, q_new = _rq(), _rq()
            R0, Rn = _rot3(q0), _rot3(q_new)
            C_new = P - (P - C0) @ (R0.T @ Rn)
            np.testing.assert_allclose(C_new, np.zeros(3), atol=1e-9)


if __name__ == "__main__":
    unittest.main()
