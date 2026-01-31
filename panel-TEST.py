import tkinter as tk
import math

class RadarController:
    def __init__(self, root):
        self.root = root
        self.root.title("雷達圖能力控制器 (分組模式)")
        
        # --- 參數設定 ---
        self.width = 600
        self.height = 600
        self.center_x = self.width // 2
        self.center_y = self.height // 2
        self.radius = 200  # 雷達圖半徑
        self.num_vars = 5  # 初始維度
        self.labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" 
        
        # 儲存被切換成「負相關」的索引集合
        self.negative_indices = set() 
        
        # 控制點位置
        self.control_x = self.center_x
        self.control_y = self.center_y
        self.is_dragging = False

        # --- 介面佈局 ---
        # 1. 畫布
        self.canvas = tk.Canvas(root, width=self.width, height=self.height, bg="#f0f0f0")
        self.canvas.pack(side=tk.LEFT)
        
        # 2. 控制面板 (右側)
        self.panel = tk.Frame(root, width=220)
        self.panel.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
        
        tk.Label(self.panel, text="控制面板", font=("Arial", 14, "bold")).pack(pady=5)
        tk.Label(self.panel, text="點擊圖上文字(A,B...)\n可切換 正/負 相關", fg="gray", font=("Arial", 10)).pack(pady=2)

        # 區域 1: 維度設定
        dim_frame = tk.LabelFrame(self.panel, text="維度設定", padx=5, pady=5)
        dim_frame.pack(fill="x", pady=5)
        
        btn_frame = tk.Frame(dim_frame)
        btn_frame.pack()
        tk.Button(btn_frame, text="-", width=3, command=self.decrease_dim).pack(side=tk.LEFT, padx=2)
        self.dim_label = tk.Label(btn_frame, text=f"{self.num_vars} 維", font=("Arial", 10, "bold"))
        self.dim_label.pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="+", width=3, command=self.increase_dim).pack(side=tk.LEFT, padx=2)
        
        tk.Button(dim_frame, text="歸位 (Reset)", bg="#ffcc00", command=self.reset_position).pack(fill="x", pady=5)

        # 區域 2: 即時數值顯示區
        self.values_frame = tk.LabelFrame(self.panel, text="即時數值", padx=5, pady=5)
        self.values_frame.pack(fill="both", expand=True, pady=5)

        # --- 儲存 UI 元件 (防閃爍優化) ---
        self.stat_widgets = [] 
        self.total_label_pos = None
        self.total_label_neg = None

        # 初始化建立數值面板
        self.rebuild_stat_panel()

        # --- 事件綁定 ---
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        # 初始繪製
        self.refresh_ui()

    def rebuild_stat_panel(self):
        """重新建立右側數值面板結構"""
        for widget in self.values_frame.winfo_children():
            widget.destroy()
        self.stat_widgets = []

        # 顯示兩個總和
        sum_frame = tk.Frame(self.values_frame)
        sum_frame.pack(fill="x", pady=2)
        self.total_label_pos = tk.Label(sum_frame, text="正: 100%", font=("Arial", 9, "bold"), fg="black")
        self.total_label_pos.pack(side=tk.LEFT, padx=5)
        self.total_label_neg = tk.Label(sum_frame, text="負: 0%", font=("Arial", 9, "bold"), fg="red")
        self.total_label_neg.pack(side=tk.RIGHT, padx=5)

        tk.Frame(self.values_frame, height=2, bg="#ddd").pack(fill="x", pady=5)

        for i in range(self.num_vars):
            label_char = self.labels[i]
            frame_row = tk.Frame(self.values_frame)
            frame_row.pack(fill="x", pady=2)
            
            # 文字標籤
            lbl = tk.Label(frame_row, text=f"{label_char}: 0.0%", width=8, anchor="w")
            lbl.pack(side=tk.LEFT)
            
            # 進度條
            c_bar = tk.Canvas(frame_row, height=8, bg="white")
            c_bar.pack(side=tk.LEFT, fill="x", expand=True)
            rect_id = c_bar.create_rectangle(0, 0, 0, 8, fill="#4FC3F7", width=0)
            
            self.stat_widgets.append((lbl, c_bar, rect_id))

    def reset_position(self):
        self.control_x = self.center_x
        self.control_y = self.center_y
        self.refresh_ui()

    def decrease_dim(self):
        if self.num_vars > 2:
            self.num_vars -= 1
            self.dim_label.config(text=f"{self.num_vars} 維")
            # 維度減少時，清理超出範圍的負相關索引
            self.negative_indices = {i for i in self.negative_indices if i < self.num_vars}
            self.reset_position()
            self.rebuild_stat_panel()

    def increase_dim(self):
        if self.num_vars < 10:
            self.num_vars += 1
            self.dim_label.config(text=f"{self.num_vars} 維")
            self.reset_position()
            self.rebuild_stat_panel()

    def get_vertices(self):
        vertices = []
        angle_step = 2 * math.pi / self.num_vars
        start_angle = -math.pi / 2
        
        for i in range(self.num_vars):
            angle = start_angle + i * angle_step
            x = self.center_x + self.radius * math.cos(angle)
            y = self.center_y + self.radius * math.sin(angle)
            vertices.append((x, y))
        return vertices

    def calculate_percentages(self, vertices):
        """核心演算法：分組計算權重"""
        distances = []
        for vx, vy in vertices:
            dist = math.sqrt((self.control_x - vx)**2 + (self.control_y - vy)**2)
            distances.append(dist)
        
        power = 1.5 
        epsilon = 10 
        # 計算所有點的原始權重分數 (IDW)
        raw_scores = [1 / ((d + epsilon) ** power) for d in distances]
        
        # --- 分組處理 ---
        pos_indices = [i for i in range(self.num_vars) if i not in self.negative_indices]
        neg_indices = [i for i in range(self.num_vars) if i in self.negative_indices]
        
        # 計算正相關組總分
        pos_total_score = sum(raw_scores[i] for i in pos_indices)
        # 計算負相關組總分
        neg_total_score = sum(raw_scores[i] for i in neg_indices)
        
        final_percentages = [0.0] * self.num_vars
        
        # 分配正相關 % (總和 100)
        if pos_indices:
            for i in pos_indices:
                if pos_total_score > 0:
                    val = (raw_scores[i] / pos_total_score) * 100
                else:
                    val = 100.0 / len(pos_indices)
                final_percentages[i] = val
        
        # 分配負相關 % (總和 100)
        if neg_indices:
            for i in neg_indices:
                if neg_total_score > 0:
                    val = (raw_scores[i] / neg_total_score) * 100
                else:
                    val = 100.0 / len(neg_indices)
                final_percentages[i] = val
                
        return final_percentages

    def refresh_ui(self):
        self.canvas.delete("all")
        vertices = self.get_vertices()
        
        # 1. 繪製圖形背景
        coords = [coord for point in vertices for coord in point]
        if self.num_vars == 2:
            self.canvas.create_line(coords, fill="#b2ebf2", width=10, capstyle=tk.ROUND)
            self.canvas.create_line(coords, fill="black", width=2, dash=(4, 4))
        else:
            self.canvas.create_polygon(coords, outline="black", fill="#e0f7fa", width=2)
            for vx, vy in vertices:
                self.canvas.create_line(self.center_x, self.center_y, vx, vy, fill="gray", dash=(4, 4))

        # 2. 計算數值
        percentages = self.calculate_percentages(vertices)
        
        # 3. 更新右側面板
        # 計算各自總和用來顯示 (驗證用)
        pos_sum = sum(percentages[i] for i in range(self.num_vars) if i not in self.negative_indices)
        neg_sum = sum(percentages[i] for i in range(self.num_vars) if i in self.negative_indices)
        
        if self.total_label_pos:
            self.total_label_pos.config(text=f"正: {pos_sum:.1f}%")
        if self.total_label_neg:
            self.total_label_neg.config(text=f"負: {neg_sum:.1f}%")

        for i, (vx, vy) in enumerate(vertices):
            val = percentages[i]
            label_char = self.labels[i]
            is_negative = i in self.negative_indices
            
            # 設定顏色：負相關為紅色，正相關為黑色
            color = "red" if is_negative else "black"
            
            # 更新雷達圖上的文字 (A, B, C...)
            label_x = self.center_x + (self.radius + 30) * math.cos(-math.pi/2 + i * (2*math.pi/self.num_vars))
            label_y = self.center_y + (self.radius + 30) * math.sin(-math.pi/2 + i * (2*math.pi/self.num_vars))
            
            # 畫圓形背景讓點擊區域更明顯
            self.canvas.create_oval(label_x-15, label_y-15, label_x+15, label_y+15, fill="#f0f0f0", outline="")
            self.canvas.create_text(label_x, label_y, text=f"{label_char}", font=("Arial", 12, "bold"), fill=color)

            # 更新右側列表
            if i < len(self.stat_widgets):
                lbl, c_bar, rect_id = self.stat_widgets[i]
                lbl.config(text=f"{label_char}: {val:.1f}%", fg=color)
                
                # 進度條顏色
                bar_color = "#ff8a80" if is_negative else "#4FC3F7"
                c_bar.itemconfig(rect_id, fill=bar_color)
                c_bar.coords(rect_id, 0, 0, val * 2, 8)

        # 4. 繪製連線與搖桿
        if self.num_vars > 2:
            for vx, vy in vertices:
                self.canvas.create_line(self.control_x, self.control_y, vx, vy, fill="#ffcccc", width=2)

        r = 8
        self.canvas.create_oval(
            self.control_x - r, self.control_y - r,
            self.control_x + r, self.control_y + r,
            fill="red", outline="white", width=2, tags="joystick"
        )

    def on_click(self, event):
        # 1. 優先檢查是否點擊了「標籤文字」(切換正負相關)
        for i in range(self.num_vars):
            label_x = self.center_x + (self.radius + 30) * math.cos(-math.pi/2 + i * (2*math.pi/self.num_vars))
            label_y = self.center_y + (self.radius + 30) * math.sin(-math.pi/2 + i * (2*math.pi/self.num_vars))
            
            # 判斷點擊距離 (半徑 20px 內算點中)
            dist_label = math.sqrt((event.x - label_x)**2 + (event.y - label_y)**2)
            if dist_label < 20:
                # 切換狀態
                if i in self.negative_indices:
                    self.negative_indices.remove(i)
                else:
                    self.negative_indices.add(i)
                self.refresh_ui()
                return # 點到文字就不移動搖桿了

        # 2. 檢查是否點擊到控制點附近 (開始拖曳)
        dist = math.sqrt((event.x - self.control_x)**2 + (event.y - self.control_y)**2)
        if dist < 20:
            self.is_dragging = True

    def on_drag(self, event):
        if self.is_dragging:
            if self.num_vars == 2:
                target_x = self.center_x
                target_y = event.y
            else:
                target_x = event.x
                target_y = event.y

            dx = target_x - self.center_x
            dy = target_y - self.center_y
            distance = math.sqrt(dx*dx + dy*dy)
            
            if distance <= self.radius:
                self.control_x = target_x
                self.control_y = target_y
            else:
                ratio = self.radius / distance
                self.control_x = self.center_x + dx * ratio
                self.control_y = self.center_y + dy * ratio
            
            self.refresh_ui()

    def on_release(self, event):
        self.is_dragging = False

if __name__ == "__main__":
    root = tk.Tk()
    app = RadarController(root)
    root.mainloop()