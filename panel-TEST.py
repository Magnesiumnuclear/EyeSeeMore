import tkinter as tk
import math

class RadarController:
    def __init__(self, root):
        self.root = root
        self.root.title("雷達圖能力控制器 (Radar Chart Controller)")
        
        # --- 參數設定 ---
        self.width = 600
        self.height = 600
        self.center_x = self.width // 2
        self.center_y = self.height // 2
        self.radius = 200  # 雷達圖半徑
        self.num_vars = 5  # 初始維度 (例如 5 維)
        self.labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" # 用來自動命名 A, B, C...
        
        # 控制點位置 (初始在正中心)
        self.control_x = self.center_x
        self.control_y = self.center_y
        self.is_dragging = False

        # --- 介面佈局 ---
        # 1. 畫布
        self.canvas = tk.Canvas(root, width=self.width, height=self.height, bg="#f0f0f0")
        self.canvas.pack(side=tk.LEFT)
        
        # 2. 控制面板 (右側)
        self.panel = tk.Frame(root, width=200)
        self.panel.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
        
        # 操作按鈕區 (維度調整 + 歸位)
        btn_frame = tk.Frame(self.panel)
        btn_frame.pack(pady=10)
        
        tk.Button(btn_frame, text="- 維度", command=self.decrease_dim).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="歸位", command=self.reset_position, bg="#ffcc00").pack(side=tk.LEFT, padx=5) # 新增歸位按鈕
        tk.Button(btn_frame, text="+ 維度", command=self.increase_dim).pack(side=tk.LEFT, padx=5)
        
        # 數值顯示區
        self.value_labels = []
        self.values_frame = tk.Frame(self.panel)
        self.values_frame.pack(pady=10)

        # --- 事件綁定 ---
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        # --- 初始繪製 ---
        self.refresh_ui()

    def reset_position(self):
        """將控制點重置回中心"""
        self.control_x = self.center_x
        self.control_y = self.center_y
        self.refresh_ui()

    def decrease_dim(self):
        if self.num_vars > 3:
            self.num_vars -= 1
            # 切換維度時，選擇是否重置 (這裡保留原位置體驗較好，或者也可呼叫 self.reset_position())
            self.refresh_ui()

    def increase_dim(self):
        if self.num_vars < 10:
            self.num_vars += 1
            self.refresh_ui()

    def get_vertices(self):
        """計算多邊形頂點座標"""
        vertices = []
        angle_step = 2 * math.pi / self.num_vars
        # 讓第一個點(A)指向上方，所以減去 pi/2
        start_angle = -math.pi / 2
        
        for i in range(self.num_vars):
            angle = start_angle + i * angle_step
            x = self.center_x + self.radius * math.cos(angle)
            y = self.center_y + self.radius * math.sin(angle)
            vertices.append((x, y))
        return vertices

    def calculate_percentages(self, vertices):
        """
        核心演算法：反距離加權 (Inverse Distance Weighting)
        """
        weights = []
        distances = []
        
        # 1. 計算控制點到每個頂點的距離
        for vx, vy in vertices:
            dist = math.sqrt((self.control_x - vx)**2 + (self.control_y - vy)**2)
            distances.append(dist)
        
        # 2. 計算權重 (距離越近，權重越高)
        power = 1.5 
        epsilon = 10 
        
        raw_weights = []
        for d in distances:
            w = 1 / ((d + epsilon) ** power)
            raw_weights.append(w)
            
        # 3. 歸一化 (Normalize) 到 100%
        total_weight = sum(raw_weights)
        percentages = [(w / total_weight) * 100 for w in raw_weights]
        
        return percentages

    def refresh_ui(self):
        self.canvas.delete("all")
        vertices = self.get_vertices()
        
        # 1. 繪製雷達圖背景 (多邊形)
        self.canvas.create_polygon(
            [coord for point in vertices for coord in point],
            outline="black", fill="#e0f7fa", width=2
        )
        
        # 繪製從中心到頂點的輻射線
        for vx, vy in vertices:
            self.canvas.create_line(self.center_x, self.center_y, vx, vy, fill="gray", dash=(4, 4))

        # 2. 計算數值
        percentages = self.calculate_percentages(vertices)
        
        # 3. 更新數值顯示
        for widget in self.values_frame.winfo_children():
            widget.destroy()
            
        tk.Label(self.values_frame, text=f"總和: {sum(percentages):.1f}%", font=("Arial", 10, "bold")).pack(pady=5)

        for i, (vx, vy) in enumerate(vertices):
            label_char = self.labels[i]
            val = percentages[i]
            
            # 在圖上畫標籤
            label_x = self.center_x + (self.radius + 20) * math.cos(-math.pi/2 + i * (2*math.pi/self.num_vars))
            label_y = self.center_y + (self.radius + 20) * math.sin(-math.pi/2 + i * (2*math.pi/self.num_vars))
            self.canvas.create_text(label_x, label_y, text=label_char, font=("Arial", 12, "bold"))
            
            # 在右側面板顯示數值條
            txt = f"{label_char}: {val:.1f}%"
            lbl = tk.Label(self.values_frame, text=txt, font=("Arial", 12))
            lbl.pack(anchor="w")
            
            # 進度條
            canvas_bar = tk.Canvas(self.values_frame, width=150, height=10, bg="white")
            canvas_bar.pack(anchor="w", pady=2)
            canvas_bar.create_rectangle(0, 0, val * 1.5, 10, fill="skyblue", width=0)

        # 4. 繪製控制點與連線
        # 使用淡紅色線條
        for vx, vy in vertices:
             self.canvas.create_line(self.control_x, self.control_y, vx, vy, fill="#ffcccc", width=2)

        # 畫控制搖桿 (紅點)
        r = 8
        self.canvas.create_oval(
            self.control_x - r, self.control_y - r,
            self.control_x + r, self.control_y + r,
            fill="red", outline="white", width=2, tags="joystick"
        )

    def on_click(self, event):
        # 檢查是否點擊到控制點附近
        dist = math.sqrt((event.x - self.control_x)**2 + (event.y - self.control_y)**2)
        if dist < 20:
            self.is_dragging = True

    def on_drag(self, event):
        if self.is_dragging:
            dx = event.x - self.center_x
            dy = event.y - self.center_y
            distance = math.sqrt(dx*dx + dy*dy)
            
            if distance <= self.radius:
                self.control_x = event.x
                self.control_y = event.y
            else:
                # 限制在圓形範圍內
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