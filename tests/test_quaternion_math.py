"""四元數運算單元測試:數學正確性 + 與 vispy Quaternion 慣例交叉驗證。

交叉驗證確保 quaternion_math 的乘法/矩陣與 vispy 完全一致——這是接到
VisPy 相機後旋轉方向正確的前提。vispy 已安裝;若缺則該幾項自動 skip。
"""

import math
import unittest

import numpy as np

import quaternion_math as Q

try:
    from vispy.util.quaternion import Quaternion as _VQ
    HAS_VISPY = True
except Exception:
    HAS_VISPY = False

RNG = np.random.default_rng(20260616)


def _rand_unit_quat():
    q = RNG.standard_normal(4)
    return q / np.linalg.norm(q)


class TestQuaternionMath(unittest.TestCase):
    def test_normalize_unit(self):
        for _ in range(20):
            q = Q.normalize(RNG.standard_normal(4) * 5)
            self.assertAlmostEqual(float(np.linalg.norm(q)), 1.0, places=10)
        np.testing.assert_allclose(Q.normalize([0, 0, 0, 0]), Q.IDENTITY)

    def test_identity_multiply(self):
        for _ in range(10):
            q = _rand_unit_quat()
            np.testing.assert_allclose(Q.multiply(Q.IDENTITY, q), q, atol=1e-12)
            np.testing.assert_allclose(Q.multiply(q, Q.IDENTITY), q, atol=1e-12)

    def test_inverse(self):
        for _ in range(10):
            q = _rand_unit_quat()
            np.testing.assert_allclose(Q.multiply(q, Q.inverse(q)), Q.IDENTITY, atol=1e-10)

    @unittest.skipUnless(HAS_VISPY, "vispy 未安裝")
    def test_multiply_matches_vispy(self):
        for _ in range(50):
            a, b = _rand_unit_quat(), _rand_unit_quat()
            mine = Q.multiply(a, b)
            v = _VQ(*a, normalize=False) * _VQ(*b, normalize=False)
            np.testing.assert_allclose(mine, [v.w, v.x, v.y, v.z], atol=1e-10)

    @unittest.skipUnless(HAS_VISPY, "vispy 未安裝")
    def test_to_matrix_matches_vispy(self):
        for _ in range(30):
            q = _rand_unit_quat()
            mine = Q.to_matrix(q)
            v = _VQ(*q, normalize=False).get_matrix()
            np.testing.assert_allclose(mine, v, atol=1e-5)

    def test_from_axis_angle_roundtrip(self):
        for _ in range(20):
            axis = Q.normalize3(RNG.standard_normal(3))
            angle = RNG.uniform(0.05, math.pi - 0.05)
            q = Q.from_axis_angle(axis, angle)
            a2, x, y, z = Q.axis_angle(q)
            # 軸方向可能整體反號(角度同步反號),統一比對
            rec_axis = np.array([x, y, z])
            if np.dot(rec_axis, axis) < 0:
                rec_axis, a2 = -rec_axis, -a2
            self.assertAlmostEqual(a2 % (2 * math.pi), angle, places=6)
            np.testing.assert_allclose(rec_axis, axis, atol=1e-6)

    def test_rotate_vector_90_about_z(self):
        q = Q.from_axis_angle((0, 0, 1), math.pi / 2)
        np.testing.assert_allclose(Q.rotate_vector(q, (1, 0, 0)), (0, 1, 0), atol=1e-9)

    def test_rotate_vector_preserves_length(self):
        for _ in range(10):
            q = _rand_unit_quat()
            v = RNG.standard_normal(3)
            self.assertAlmostEqual(np.linalg.norm(Q.rotate_vector(q, v)),
                                   np.linalg.norm(v), places=9)

    # ── virtual trackball ──
    def test_trackball_project_inside_on_sphere(self):
        p = Q.trackball_project(0.3, 0.4)  # r²=0.25 ≤ 0.5
        self.assertAlmostEqual(np.linalg.norm(p), 1.0, places=9)

    def test_trackball_project_outside_hyperbola(self):
        x, y = 0.9, 0.9  # r²=1.62 > 0.5
        p = Q.trackball_project(x, y)
        self.assertAlmostEqual(p[2], 0.5 / math.sqrt(x * x + y * y), places=9)

    def test_trackball_delta_identity(self):
        a = Q.trackball_project(0.2, 0.1)
        np.testing.assert_allclose(Q.trackball_delta(a, a), Q.IDENTITY, atol=1e-9)

    def test_trackball_delta_maps_a_to_b(self):
        for _ in range(30):
            a = Q.normalize3(RNG.standard_normal(3))
            b = Q.normalize3(RNG.standard_normal(3))
            if np.dot(a, b) < -0.999:
                continue
            dq = Q.trackball_delta(a, b)
            np.testing.assert_allclose(Q.rotate_vector(dq, a), b, atol=1e-7)

    def test_trackball_delta_antipodal(self):
        a = np.array([0.0, 0.0, 1.0])
        dq = Q.trackball_delta(a, -a)
        np.testing.assert_allclose(Q.rotate_vector(dq, a), -a, atol=1e-6)

    # ── SLERP ──
    def test_slerp_endpoints(self):
        q0, q1 = _rand_unit_quat(), _rand_unit_quat()
        np.testing.assert_allclose(Q.canonical(Q.slerp(q0, q1, 0.0)),
                                   Q.canonical(q0), atol=1e-9)
        np.testing.assert_allclose(Q.canonical(Q.slerp(q0, q1, 1.0)),
                                   Q.canonical(q1), atol=1e-6)

    def test_slerp_unit_everywhere(self):
        q0, q1 = _rand_unit_quat(), _rand_unit_quat()
        for t in np.linspace(0, 1, 11):
            self.assertAlmostEqual(np.linalg.norm(Q.slerp(q0, q1, t)), 1.0, places=9)

    def test_slerp_midpoint_half_angle(self):
        # 從單位四元數 slerp 到「繞 z 轉 90°」,中點應為「轉 45°」
        q0 = Q.IDENTITY
        q1 = Q.from_axis_angle((0, 0, 1), math.pi / 2)
        mid = Q.canonical(Q.slerp(q0, q1, 0.5))
        expect = Q.canonical(Q.from_axis_angle((0, 0, 1), math.pi / 4))
        np.testing.assert_allclose(mid, expect, atol=1e-9)

    def test_slerp_shortest_path(self):
        # q1 與 -q1 同姿態,slerp 應走同一條最短路徑
        q0 = Q.IDENTITY
        q1 = Q.from_axis_angle((0, 1, 0), 0.5)
        a = Q.canonical(Q.slerp(q0, q1, 0.5))
        b = Q.canonical(Q.slerp(q0, -q1, 0.5))
        np.testing.assert_allclose(a, b, atol=1e-9)


if __name__ == "__main__":
    unittest.main()
