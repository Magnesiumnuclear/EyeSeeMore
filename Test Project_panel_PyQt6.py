import sys
import math
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFrame, 
                             QGridLayout, QProgressBar)
from PyQt6.QtCore import Qt, QPointF, pyqtSignal, QSize
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPolygonF

class RadarWidget(QWidget):
    # 定義訊號：當數值改變時發送 (每個維度的百分比, 正相關總和, 負相關總和)
    valuesChanged = pyqtSignal(list, float, float)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(500, 500)
        self.setStyleSheet("background-color: #F5F5F5;")  # 畫布背景淺灰

        # --- 參數設定 ---
        self.radius = 180
        self.num_vars = 5
        self.labels_list = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        
        # 狀態
        self.negative_indices = set()
        self.control_pos = QPointF(0, 0) # 相對於中心的座標
        self.is_dragging = False
        
        # 初始歸位
        self.reset_position()

    def reset_position(self):
        self.control_pos = QPointF(0, 0)
        self.update()
        self.calculate_and_emit()

    def set_dims(self, count):
        self.num_vars = count
        # 清除超出範圍的負相關索引
        self.negative_indices = {i for i in self.negative_indices if i < self.num_vars}
        self.reset_position()

    def get_center(self):
        return QPointF(self.width() / 2, self.height() / 2)

    def get_vertices(self):
        center = self.get_center()
        vertices = []
        angle_step = 2 * math.pi / self.num_vars
        start_angle = -math.pi / 2
        
        for i in range(self.num_vars):
            angle = start_angle + i * angle_step
            x = center.x() + self.radius * math.cos(angle)
            y = center.y() + self.radius * math.sin(angle)
            vertices.append(QPointF(x, y))
        return vertices

    def calculate_and_emit(self):
        """計算權重並發送訊號"""
        center = self.get_center()
        # 實際控制點在視窗中的絕對座標
        abs_control_x = center.x() + self.control_pos.x()
        abs_control_y = center.y() + self.control_pos.y()
        
        vertices = self.get_vertices()
        distances = []
        
        for v in vertices:
            dist = math.sqrt((abs_control_x - v.x())**2 + (abs_control_y - v.y())**2)
            distances.append(dist)

        power = 1.5
        epsilon = 10
        raw_scores = [1 / ((d + epsilon) ** power) for d in distances]

        pos_indices = [i for i in range(self.num_vars) if i not in self.negative_indices]
        neg_indices = [i for i in range(self.num_vars) if i in self.negative_indices]

        pos_total_score = sum(raw_scores[i] for i in pos_indices)
        neg_total_score = sum(raw_scores[i] for i in neg_indices)

        final_percentages = [0.0] * self.num_vars

        # 分配正相關
        if pos_indices:
            for i in pos_indices:
                if pos_total_score > 0:
                    val = (raw_scores[i] / pos_total_score) * 100
                else:
                    val = 100.0 / len(pos_indices)
                final_percentages[i] = val
        
        # 分配負相關
        if neg_indices:
            for i in neg_indices:
                if neg_total_score > 0:
                    val = (raw_scores[i] / neg_total_score) * 100
                else:
                    val = 100.0 / len(neg_indices)
                final_percentages[i] = val

        # 計算顯示用的總和
        display_pos_sum = sum(final_percentages[i] for i in pos_indices)
        display_neg_sum = sum(final_percentages[i] for i in neg_indices)

        self.valuesChanged.emit(final_percentages, display_pos_sum, display_neg_sum)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        center = self.get_center()
        vertices = self.get_vertices()

        # 1. 繪製多邊形背景
        poly = QPolygonF(vertices)
        
        # 風格：灰色系
        brush_color = QColor("#E0E0E0") # 淺灰底
        painter.setBrush(QBrush(brush_color))
        painter.setPen(QPen(QColor("#BDBDBD"), 2)) # 邊框灰
        
        if self.num_vars > 2:
            painter.drawPolygon(poly)
        else:
            painter.drawLine(vertices[0], vertices[1])

        # 2. 繪製從中心到頂點的放射線 (虛線)
        pen_dash = QPen(QColor("#9E9E9E"), 1)
        pen_dash.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen_dash)
        for v in vertices:
            painter.drawLine(center, v)

        # 3. 繪製控制點連線
        abs_control_pos = center + self.control_pos
        pen_link = QPen(QColor("#B0BEC5"), 2) # 藍灰連接線
        painter.setPen(pen_link)
        if self.num_vars > 2:
            for v in vertices:
                painter.drawLine(abs_control_pos, v)

        # 4. 繪製頂點標籤 (A, B, C...)
        font = QFont("Arial", 12, QFont.Weight.Bold)
        painter.setFont(font)
        
        for i, v in enumerate(vertices):
            # 計算標籤位置 (向外推一點)
            angle = -math.pi / 2 + i * (2 * math.pi / self.num_vars)
            label_offset = 35
            lx = center.x() + (self.radius + label_offset) * math.cos(angle)
            ly = center.y() + (self.radius + label_offset) * math.sin(angle)
            label_point = QPointF(lx, ly)

            is_neg = i in self.negative_indices
            
            # 灰色系設定：正相關為深灰，負相關為中灰
            if is_neg:
                text_color = QColor("#9E9E9E") # 負相關：灰色
            else:
                text_color = QColor("#212121") # 正相關：深灰/黑

            # 繪製點擊區域提示圓圈 (淡淡的背景)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#EEEEEE")))
            painter.drawEllipse(label_point, 18, 18)

            painter.setPen(text_color)
            # 置中繪製文字
            rect_w, rect_h = 40, 40
            painter.drawText(int(lx - rect_w/2), int(ly - rect_h/2), 
                             rect_w, rect_h, 
                             Qt.AlignmentFlag.AlignCenter, 
                             self.labels_list[i])

        # 5. 繪製搖桿 (控制點)
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.setBrush(QBrush(QColor("#424242"))) # 深炭灰搖桿
        painter.drawEllipse(abs_control_pos, 10, 10)

    def mousePressEvent(self, event):
        click_pos = event.position()
        center = self.get_center()
        
        # 1. 檢查是否點擊標籤
        vertices = self.get_vertices()
        for i, _ in enumerate(vertices):
            angle = -math.pi / 2 + i * (2 * math.pi / self.num_vars)
            label_offset = 35
            lx = center.x() + (self.radius + label_offset) * math.cos(angle)
            ly = center.y() + (self.radius + label_offset) * math.sin(angle)
            
            # 判定距離
            dist = math.sqrt((click_pos.x() - lx)**2 + (click_pos.y() - ly)**2)
            if dist < 20:
                if i in self.negative_indices:
                    self.negative_indices.remove(i)
                else:
                    self.negative_indices.add(i)
                self.update()
                self.calculate_and_emit()
                return

        # 2. 檢查是否點擊搖桿
        abs_control_pos = center + self.control_pos
        dist_ctrl = math.sqrt((click_pos.x() - abs_control_pos.x())**2 + 
                              (click_pos.y() - abs_control_pos.y())**2)
        
        if dist_ctrl < 20:
            self.is_dragging = True

    def mouseMoveEvent(self, event):
        if not self.is_dragging:
            return
            
        target_pos = event.position()
        center = self.get_center()
        
        # 計算相對於中心的向量
        dx = target_pos.x() - center.x()
        dy = target_pos.y() - center.y()
        
        if self.num_vars == 2:
            # 2維時限制在直線上 (Y軸)
            dx = 0
            
        dist = math.sqrt(dx*dx + dy*dy)
        
        if dist <= self.radius:
            self.control_pos = QPointF(dx, dy)
        else:
            ratio = self.radius / dist
            self.control_pos = QPointF(dx * ratio, dy * ratio)
            
        self.update()
        self.calculate_and_emit()

    def mouseReleaseEvent(self, event):
        self.is_dragging = False

class ControlPanel(QFrame):
    def __init__(self, radar_widget):
        super().__init__()
        self.radar = radar_widget
        self.setFixedWidth(280)
        self.setStyleSheet("""
            QFrame { background-color: #ECECEC; border-left: 1px solid #D6D6D6; }
            QLabel { color: #424242; font-family: Arial; }
            QPushButton { 
                background-color: #E0E0E0; 
                border: 1px solid #BDBDBD; 
                border-radius: 4px;
                padding: 4px;
                color: #424242;
            }
            QPushButton:hover { background-color: #D6D6D6; }
            QProgressBar {
                border: 1px solid #BDBDBD;
                border-radius: 2px;
                background-color: #FFFFFF;
                text-align: center;
                color: transparent; 
            }
            QProgressBar::chunk { background-color: #757575; }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 20, 15, 20)

        # 標題區
        title_lbl = QLabel("控制面板")
        title_lbl.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_lbl)

        desc_lbl = QLabel("點擊圖上文字 (A,B...)\n可切換 正/負 相關")
        desc_lbl.setStyleSheet("color: #757575; font-size: 12px;")
        desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc_lbl)
        
        # 分隔線
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #BDBDBD;")
        layout.addWidget(line)

        # 維度控制
        dim_layout = QHBoxLayout()
        btn_minus = QPushButton("-")
        btn_minus.setFixedSize(30, 30)
        btn_minus.clicked.connect(self.decrease_dim)
        
        self.dim_label = QLabel(f"{self.radar.num_vars} 維")
        self.dim_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.dim_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        btn_plus = QPushButton("+")
        btn_plus.setFixedSize(30, 30)
        btn_plus.clicked.connect(self.increase_dim)
        
        dim_layout.addWidget(btn_minus)
        dim_layout.addWidget(self.dim_label)
        dim_layout.addWidget(btn_plus)
        layout.addLayout(dim_layout)

        # 重置按鈕
        btn_reset = QPushButton("歸位 (Reset)")
        btn_reset.setStyleSheet("""
            QPushButton { background-color: #BDBDBD; color: white; font-weight: bold; }
            QPushButton:hover { background-color: #9E9E9E; }
        """)
        btn_reset.clicked.connect(self.radar.reset_position)
        layout.addWidget(btn_reset)

        # 數值顯示區容器
        self.stats_container = QWidget()
        self.stats_layout = QVBoxLayout(self.stats_container)
        self.stats_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_layout.setSpacing(8)
        layout.addWidget(self.stats_container)
        
        # 彈性空間
        layout.addStretch()

        # 連接訊號
        self.radar.valuesChanged.connect(self.update_stats)
        
        # 初始化介面
        self.refresh_stats_ui()

    def decrease_dim(self):
        if self.radar.num_vars > 2:
            self.radar.set_dims(self.radar.num_vars - 1)
            self.dim_label.setText(f"{self.radar.num_vars} 維")
            self.refresh_stats_ui()
            self.radar.calculate_and_emit()

    def increase_dim(self):
        if self.radar.num_vars < 10:
            self.radar.set_dims(self.radar.num_vars + 1)
            self.dim_label.setText(f"{self.radar.num_vars} 維")
            self.refresh_stats_ui()
            self.radar.calculate_and_emit()

    def refresh_stats_ui(self):
        # 清除舊的數值顯示
        for i in reversed(range(self.stats_layout.count())):
            self.stats_layout.itemAt(i).widget().setParent(None)
        
        self.stat_rows = []
        
        # 總和顯示
        sum_widget = QWidget()
        sum_layout = QHBoxLayout(sum_widget)
        sum_layout.setContentsMargins(0, 5, 0, 5)
        self.lbl_sum_pos = QLabel("正: 100%")
        self.lbl_sum_pos.setStyleSheet("color: #212121; font-weight: bold;")
        self.lbl_sum_neg = QLabel("負: 0%")
        self.lbl_sum_neg.setStyleSheet("color: #9E9E9E; font-weight: bold;")
        
        sum_layout.addWidget(self.lbl_sum_pos)
        sum_layout.addStretch()
        sum_layout.addWidget(self.lbl_sum_neg)
        self.stats_layout.addWidget(sum_widget)

        # 個別維度
        for i in range(self.radar.num_vars):
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            
            lbl = QLabel(f"{self.radar.labels_list[i]}: 0.0%")
            lbl.setFixedWidth(70)
            
            pbar = QProgressBar()
            pbar.setFixedHeight(10)
            pbar.setRange(0, 100)
            pbar.setTextVisible(False)
            
            row_layout.addWidget(lbl)
            row_layout.addWidget(pbar)
            
            self.stats_layout.addWidget(row_widget)
            self.stat_rows.append((lbl, pbar))

    def update_stats(self, percentages, pos_sum, neg_sum):
        # 更新總和
        self.lbl_sum_pos.setText(f"正: {pos_sum:.1f}%")
        self.lbl_sum_neg.setText(f"負: {neg_sum:.1f}%")
        
        # 更新每一列
        for i, val in enumerate(percentages):
            if i >= len(self.stat_rows):
                break
                
            lbl, pbar = self.stat_rows[i]
            label_char = self.radar.labels_list[i]
            
            is_neg = i in self.radar.negative_indices
            
            # 文字與顏色更新 (灰色系)
            if is_neg:
                # 負相關：淡灰字體，進度條顏色較淺
                lbl.setStyleSheet("color: #9E9E9E;") 
                # 使用 PyQt StyleSheet 動態改變 Chunk 顏色
                pbar.setStyleSheet("""
                    QProgressBar { border: 1px solid #E0E0E0; background: white; }
                    QProgressBar::chunk { background-color: #BDBDBD; }
                """)
            else:
                # 正相關：深灰字體，進度條深灰
                lbl.setStyleSheet("color: #212121; font-weight: bold;")
                pbar.setStyleSheet("""
                    QProgressBar { border: 1px solid #BDBDBD; background: white; }
                    QProgressBar::chunk { background-color: #424242; }
                """)
                
            lbl.setText(f"{label_char}: {val:.1f}%")
            pbar.setValue(int(val))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("雷達圖能力控制器 (灰色系 PyQT6 版)")
        self.resize(850, 650)
        self.setStyleSheet("background-color: #F5F5F5;")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 左側雷達圖
        self.radar_widget = RadarWidget()
        main_layout.addWidget(self.radar_widget, stretch=1)

        # 右側控制面板
        self.control_panel = ControlPanel(self.radar_widget)
        main_layout.addWidget(self.control_panel, stretch=0)
        
        # 初始化數據流
        self.radar_widget.calculate_and_emit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 全局字體設定
    font = QFont("Arial", 10)
    app.setFont(font)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())