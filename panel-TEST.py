import tkinter as tk
import math

class RadarController:
    def __init__(self, root):
        self.root = root
        self.root.title("雷達圖能力控制器 (2D~10D)")
        
        # --- 參數設定 ---
        self.width = 600
        self.height = 600
        self.center_x = self.width // 2
        self.center_y = self.height // 2
        self.radius = 200  # 雷達圖半徑
        self.num_vars = 5  # 初始維度
        self.labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" 
        
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
        self.total_label = None

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

        self.total_label = tk.Label(self.values_frame, text="總和: 100.0%", font=("Arial", 9, "bold"), fg="gray")
        self.total_label.pack(pady=2)

        for i in range(self.num_vars):
            label_char = self.labels[i]
            frame_row = tk.Frame(self.values_frame)
            frame_row.pack(fill="x", pady=2)
            
            lbl = tk.Label(frame_row, text=f"{label_char}: 0.0%", width=8, anchor="w")
            lbl.pack(side=tk.LEFT)
            
            c_bar = tk.Canvas(frame_row, height=8, bg="white")
            c_bar.pack(side=tk.LEFT, fill="x", expand=True)
            rect_id = c_bar.create_rectangle(0, 0, 0, 8, fill="#4FC3F7", width=0)
            
            self.stat_widgets.append((lbl, c_bar, rect_id))

    def reset_position(self):
        self.control_x = self.center_x
        self.control_y = self.center_y
        self.refresh_ui()

    def decrease_dim(self):
        # 修改：允許最小維度降到 2
        if self.num_vars > 2:
            self.num_vars -= 1
            self.dim_label.config(text=f"{self.num_vars} 維")
            # 如果從 3 變 2，或是其他變化，都要重置搖桿位置以免跑出範圍
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
        """核心演算法"""
        distances = []
        for vx, vy in vertices:
            dist = math.sqrt((self.control_x - vx)**2 + (self.control_y - vy)**2)
            distances.append(dist)
        
        power = 1.5 
        epsilon = 10 
        raw_weights = [1 / ((d + epsilon) ** power) for d in distances]
        total_raw_weight = sum(raw_weights)

        percentages = []
        for w in raw_weights:
            if total_raw_weight > 0:
                share = (w / total_raw_weight) * 100
            else:
                share = 100.0 / self.num_vars
            percentages.append(share)
        
        return percentages

    def refresh_ui(self):
        self.canvas.delete("all")
        vertices = self.get_vertices()
        
        # 1. 繪製圖形背景
        # 修改：如果是 2 維，畫一條粗線；如果是 3 維以上，畫多邊形
        coords = [coord for point in vertices for coord in point]
        if self.num_vars == 2:
            # 畫一條連接 A 和 B 的粗線
            self.canvas.create_line(coords, fill="#b2ebf2", width=10, capstyle=tk.ROUND)
            # 再畫一條細黑線當軸心
            self.canvas.create_line(coords, fill="black", width=2, dash=(4, 4))
        else:
            self.canvas.create_polygon(coords, outline="black", fill="#e0f7fa", width=2)
            # 輻射線
            for vx, vy in vertices:
                self.canvas.create_line(self.center_x, self.center_y, vx, vy, fill="gray", dash=(4, 4))

        # 2. 計算數值
        percentages = self.calculate_percentages(vertices)
        
        # 3. 更新數值顯示
        if self.total_label:
            self.total_label.config(text=f"總和: {sum(percentages):.1f}%")

        for i, (vx, vy) in enumerate(vertices):
            val = percentages[i]
            label_char = self.labels[i]
            
            # 更新雷達圖上的文字
            label_x = self.center_x + (self.radius + 30) * math.cos(-math.pi/2 + i * (2*math.pi/self.num_vars))
            label_y = self.center_y + (self.radius + 30) * math.sin(-math.pi/2 + i * (2*math.pi/self.num_vars))
            self.canvas.create_text(label_x, label_y, text=f"{label_char}", font=("Arial", 12, "bold"))

            # 更新右側列表
            if i < len(self.stat_widgets):
                lbl, c_bar, rect_id = self.stat_widgets[i]
                lbl.config(text=f"{label_char}: {val:.1f}%")
                c_bar.coords(rect_id, 0, 0, val * 2, 8)

        # 4. 繪製連線與搖桿
        # 2維時不需要畫紅色輻射連線，因為搖桿就在線上，會重疊
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
        dist = math.sqrt((event.x - self.control_x)**2 + (event.y - self.control_y)**2)
        if dist < 20:
            self.is_dragging = True

    def on_drag(self, event):
        if self.is_dragging:
            # --- 修改：增加 2D 模式的軌道鎖定 ---
            if self.num_vars == 2:
                # 強制鎖定 X 軸在中心，只允許 Y 軸移動
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