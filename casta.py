import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog
import cv2
import numpy as np
from PIL import Image, ImageTk, ImageGrab
import math
import os
import shutil
import tempfile
import io
import ctypes
from collections import deque

try: ctypes.windll.shcore.SetProcessDpiAwareness(1)
except: pass

# --- Theme ---
APP_TITLE = "CASTA — Contact Angle & Surface Tension Analyzer V.39.2026 (Copyright © 2026)"
CANVAS_W = 900
CANVAS_H = int(CANVAS_W * 3 / 4)

THEME = {
    "bg_main": "#F7F9FB",
    "bg_panel": "#FFFFFF",
    "bg_vid":   "#E8F6FF",
    "bg_tool":  "#F4F3FF",
    "bg_info":  "#F0F4F8",    
    "bg_calib": "#EEF7EF",    
    "bg_st":    "#FFF9E6",    
    "bg_ca":    "#FBF4FF",    
    "accent":   "#4DB6AC",
    "line_de":  "#FF1744",    # bright red
    "line_ds":  "#FF6D00",    # bright orange
    "line_base": "#2979FF",   # bright blue
    "line_tan": "#7C4DFF",    # bright purple
    "line_fit": "#D50000",    # bright red (Fit Curve)
    "roi_box":  "#29B6F6",
    "text_res": "#263238"
}

# --- Physics ---
GRAVITY = 9.81
RHO_LIQUID = 997  
RHO_AIR = 1.2
DELTA_RHO = RHO_LIQUID - RHO_AIR

def create_inverted_canvas_text(canvas, x, y, text, font, tags, fill="white", outline="black", anchor="center"):
    text_ids = []
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]:
        text_ids.append(canvas.create_text(x + dx, y + dy, text=text, fill=outline, font=font, tags=tags, anchor=anchor))
    text_ids.append(canvas.create_text(x, y, text=text, fill=fill, font=font, tags=tags, anchor=anchor))
    return text_ids

class DraggablePoint:
    def __init__(self, canvas, x, y, on_drag_callback=None, color='#E91E63', radius=6, tag="point", label="", label_offset_x=0, label_offset_y=-20, label_fill="#FF1744"):
        self.canvas = canvas
        self.x = x; self.y = y; self.r = radius
        self.callback = on_drag_callback
        self.tag = tag
        self.id_oval = canvas.create_oval(x-radius, y-radius, x+radius, y+radius, outline=color, width=2, tags=tag)
        self.id_fill = canvas.create_oval(x-2, y-2, x+2, y+2, fill=color, tags=tag)
        self.id_text = create_inverted_canvas_text(canvas, x+label_offset_x, y+label_offset_y, text=label, fill=label_fill, outline="black", font=("Arial", 12, "bold"), tags=tag) if label else []

    def move(self, x, y):
        dx = x - self.x; dy = y - self.y
        self.canvas.move(self.id_oval, dx, dy)
        self.canvas.move(self.id_fill, dx, dy)
        for text_id in self.id_text:
            self.canvas.move(text_id, dx, dy)
        self.x = x; self.y = y
        if self.callback: self.callback()

    def contains(self, x, y):
        return (self.x - self.r*3 <= x <= self.x + self.r*3) and (self.y - self.r*3 <= y <= self.y + self.r*3)

class CastaApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("2000x1400")
        self.root.configure(bg=THEME["bg_main"])

        # Video State
        self.cap = None; self.temp_file = None
        self.total_frames=0; self.fps=30; self.is_playing=False
        self.original_frame = None; self.display_frame = None
        self.current_time_var = tk.StringVar(value="00:00:000")
        self.total_time_var = tk.StringVar(value="00:00:000")
        self.is_time_entry_editing = False
        self.current_frame_var = tk.StringVar(value="0")
        self.total_frame_var = tk.StringVar(value="0")
        self.is_frame_entry_editing = False
        
        # Image Params
        self.v_bright = tk.IntVar(value=0)
        self.v_contrast = tk.IntVar(value=0)
        self.v_sat = tk.DoubleVar(value=0.0)
        self.v_thresh = tk.IntVar(value=180)
        self.use_binary = False
        self.use_differential = False
        self.v_diff_thresh = tk.IntVar(value=15)
        self.edge_pts_global = None
        self.erase_mode = False
        self.pen_mode = False
        self.v_diff_frames = tk.IntVar(value=5)
        self.prev_frames_raw = deque(maxlen=10)
        
        # Analysis State
        self.crop_rect = None; self.drag_mode = None; self.start_xy = (0,0)
        self.cropped_img = None
        self.rotated_img = None
        self.total_rotation = 0.0
        
        # Calc State
        self.ca_roi = None; self.roi_drag = False; self.rotate_roi = None
        self.baseline_params = None
        self.drop_contour = None
        self.fit_params = None
        self.drawn_fit_points = None
        
        self.scale_factor = None
        self.real_mm = 1.0
        self.img_scale_right = 1.0
        self.offset_x=0; self.offset_y=0
        self.fit_method = tk.StringVar(value="Ellipse")
        
        self.export_data_st = {}
        self.export_data_ca = {}
        self.last_mode_calc = None

        self.calib_points = []; self.baseline_points = []; self.auto_scale_rect = None
        self.mode = "NONE"
        self.btn_set_baseline = None  # Reference to Set Baseline Points button
        self.btn_set_2point = None  # Reference to Set 2-Point button
        self.btn_set_box = None  # Reference to Set Box (Auto) button
        self.btn_select_roi = None  # Reference to Select ROI of Only Drop button
        self.btn_select_drop_rot = None  # Reference to Select Drop button in Rotation
        self.btn_pen = None
        self.btn_erase = None

        self._init_ui()

    def _init_ui(self):
        main = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=THEME["bg_main"], sashwidth=4)
        main.pack(fill=tk.BOTH, expand=True)

        # --- Themed ttk styles (modern / material-like) ---
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except:
            pass
        style.configure('TButton', font=('Segoe UI', 10), padding=6)
        style.configure('Accent.TButton', background=THEME['accent'], foreground='white')
        style.map('Accent.TButton', background=[('active', '#00796B')])
        style.configure('Primary.TButton', background=THEME['line_base'], foreground='white')
        style.map('Primary.TButton', background=[('active', '#254eda')])
        style.configure('Outline.TButton', background='#FFFFFF', foreground=THEME['accent'])
        # Waiting state uses stronger yellow (keeps prominent)
        style.configure('Waiting.TButton', background='#FFB300', foreground='black')
        style.map('Waiting.TButton', background=[('active', '#FF8F00')])
        # Pastel red action buttons
        style.configure('PastelRed.TButton', background='#FFCDD2', foreground='#3E2723')
        style.map('PastelRed.TButton', background=[('active', '#EF9A9A')])

        # === LEFT PANEL ===
        left_frame = tk.Frame(main, bg=THEME["bg_vid"])
        main.add(left_frame, width=700)
        
        self.lbl_file = tk.Label(left_frame, text="[No Video Loaded]", bg=THEME["bg_vid"], font=("Arial", 9, "bold"))
        self.lbl_file.pack(fill=tk.X, padx=10, pady=(5,0))

        self.cv_vid = tk.Canvas(left_frame, width=CANVAS_W, height=CANVAS_H, bg="black", cursor="cross", highlightthickness=0)
        self.cv_vid.pack(fill=tk.X, padx=10, pady=5)
        self.cv_vid.bind("<Configure>", self.on_vid_canvas_configure)
        self.cv_vid.bind("<ButtonPress-1>", self.on_vid_click)
        self.cv_vid.bind("<B1-Motion>", self.on_vid_drag)
        self.cv_vid.bind("<ButtonRelease-1>", self.on_vid_release)

        # Player
        ctrl = tk.Frame(left_frame, bg=THEME["bg_vid"]); ctrl.pack(fill=tk.X, padx=10)
        self.sl_frame = ttk.Scale(ctrl, from_=0, to=100, command=self.on_seek)
        self.sl_frame.pack(fill=tk.X)
        
        btns = tk.Frame(ctrl, bg=THEME["bg_vid"]); btns.pack(fill=tk.X, pady=2)
        ttk.Button(btns, text="📂 Open Video", command=self.load_video, style='PastelRed.TButton').pack(side=tk.LEFT)
        tk.Frame(btns, width=10, bg=THEME["bg_vid"]).pack(side=tk.LEFT)
        ttk.Button(btns, text="<", width=3, command=lambda: self.step_frame(-1)).pack(side=tk.LEFT)
        self.btn_play = ttk.Button(btns, text="▶", width=3, command=self.toggle_play)
        self.btn_play.pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text=">", width=3, command=lambda: self.step_frame(1)).pack(side=tk.LEFT)
        info_box = tk.Frame(btns, bg=THEME["bg_vid"])
        info_box.pack(side=tk.RIGHT)
        time_box = tk.Frame(info_box, bg=THEME["bg_vid"])
        time_box.pack(anchor="e")
        self.ent_time = ttk.Entry(time_box, width=10, textvariable=self.current_time_var, font=("Consolas", 10), justify="center")
        self.ent_time.pack(side=tk.LEFT)
        self.ent_time.bind("<Return>", self.jump_to_time_from_entry)
        self.ent_time.bind("<KP_Enter>", self.jump_to_time_from_entry)
        self.ent_time.bind("<FocusIn>", self.on_time_entry_focus_in)
        self.ent_time.bind("<FocusOut>", self.on_time_entry_focus_out)
        self.ent_time.bind("<Escape>", self.cancel_time_entry)
        tk.Label(time_box, text=" / ", bg=THEME["bg_vid"], font=("Consolas", 10)).pack(side=tk.LEFT)
        self.lbl_total_time = tk.Label(time_box, textvariable=self.total_time_var, bg=THEME["bg_vid"], font=("Consolas", 10))
        self.lbl_total_time.pack(side=tk.LEFT)
        frame_box = tk.Frame(info_box, bg=THEME["bg_vid"])
        frame_box.pack(anchor="e")
        self.ent_frame = ttk.Entry(frame_box, width=6, textvariable=self.current_frame_var, font=("Consolas", 10), justify="center")
        self.ent_frame.pack(side=tk.LEFT)
        self.ent_frame.bind("<Return>", self.jump_to_frame_from_entry)
        self.ent_frame.bind("<KP_Enter>", self.jump_to_frame_from_entry)
        self.ent_frame.bind("<FocusIn>", self.on_frame_entry_focus_in)
        self.ent_frame.bind("<FocusOut>", self.on_frame_entry_focus_out)
        self.ent_frame.bind("<Escape>", self.cancel_frame_entry)
        tk.Label(frame_box, text=" / ", bg=THEME["bg_vid"], font=("Consolas", 10)).pack(side=tk.LEFT)
        self.lbl_total_frame = tk.Label(frame_box, textvariable=self.total_frame_var, bg=THEME["bg_vid"], font=("Consolas", 10))
        self.lbl_total_frame.pack(side=tk.LEFT)

        # Adjustments
        adj = tk.LabelFrame(left_frame, text="Step 1: Load Video & Image Adjustments", bg=THEME["bg_vid"], padx=5, pady=5)
        adj.pack(fill=tk.X, padx=10, pady=5)
        self.create_entry_slider(adj, "Brightness", self.v_bright, -100, 100, 0)
        self.create_entry_slider(adj, "Contrast", self.v_contrast, -50, 100, 1)
        r_bin = tk.Frame(adj, bg=THEME["bg_vid"]); r_bin.grid(row=2, column=0, columnspan=5, sticky="ew", pady=2)
        self.btn_binary = tk.Button(r_bin, text="Solid Black (Off)", bg=THEME["bg_tool"], width=15, command=self.toggle_binary)
        self.btn_binary.pack(side=tk.LEFT)
        ttk.Scale(r_bin, from_=0, to=255, variable=self.v_thresh, command=self._snap_int(self.v_thresh, self.on_live_adjust)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ent_bin = tk.Entry(r_bin, textvariable=self.v_thresh, width=5)
        ent_bin.pack(side=tk.LEFT)
        ent_bin.bind("<Return>", self.on_live_adjust)
        ent_bin.bind("<FocusOut>", self.on_live_adjust)
        tk.Button(r_bin, text="-", width=2, command=lambda: self._step_var(self.v_thresh, -1, 0, 255)).pack(side=tk.LEFT)
        tk.Button(r_bin, text="+", width=2, command=lambda: self._step_var(self.v_thresh, 1, 0, 255)).pack(side=tk.LEFT)
        ttk.Button(r_bin, text="Apply", width=5, command=self.update_view, style='PastelRed.TButton').pack(side=tk.LEFT, padx=2)

        r_diff = tk.Frame(adj, bg=THEME["bg_vid"]); r_diff.grid(row=3, column=0, columnspan=5, sticky="ew", pady=2)
        self.btn_diff = tk.Button(r_diff, text="Differential (Off)", bg=THEME["bg_tool"], width=18, command=self.toggle_differential)
        self.btn_diff.pack(side=tk.LEFT)
        ttk.Scale(r_diff, from_=0, to=100, variable=self.v_diff_thresh, command=self._snap_int(self.v_diff_thresh, self.on_live_adjust)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ent_diff = tk.Entry(r_diff, textvariable=self.v_diff_thresh, width=5)
        ent_diff.pack(side=tk.LEFT)
        ent_diff.bind("<Return>", self.on_live_adjust)
        ent_diff.bind("<FocusOut>", self.on_live_adjust)
        tk.Button(r_diff, text="-", width=2, command=lambda: self._step_var(self.v_diff_thresh, -1, 0, 100)).pack(side=tk.LEFT)
        tk.Button(r_diff, text="+", width=2, command=lambda: self._step_var(self.v_diff_thresh, 1, 0, 100)).pack(side=tk.LEFT)
        ttk.Button(r_diff, text="Apply", width=5, command=self.update_view, style='PastelRed.TButton').pack(side=tk.LEFT, padx=2)

        r_diff_frames = tk.Frame(adj, bg=THEME["bg_vid"]); r_diff_frames.grid(row=4, column=0, columnspan=5, sticky="ew", pady=2)
        tk.Label(r_diff_frames, text="Diff Frames", bg=THEME["bg_vid"]).pack(side=tk.LEFT)
        ttk.Scale(r_diff_frames, from_=1, to=20, variable=self.v_diff_frames, command=self.on_diff_frames_change).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ent_diff_frames = tk.Entry(r_diff_frames, textvariable=self.v_diff_frames, width=5)
        ent_diff_frames.pack(side=tk.LEFT)
        ent_diff_frames.bind("<Return>", self.on_diff_frames_change)
        ent_diff_frames.bind("<FocusOut>", self.on_diff_frames_change)
        tk.Button(r_diff_frames, text="-", width=2, command=lambda: self._step_var(self.v_diff_frames, -1, 1, 20, integer=True, callback=self.on_diff_frames_change)).pack(side=tk.LEFT)
        tk.Button(r_diff_frames, text="+", width=2, command=lambda: self._step_var(self.v_diff_frames, 1, 1, 20, integer=True, callback=self.on_diff_frames_change)).pack(side=tk.LEFT)

        ttk.Button(left_frame, text="Step 2: ✂ Crop Selected Area", command=self.do_crop, style='PastelRed.TButton').pack(fill=tk.X, padx=10, pady=5)

        # Formula (UPDATED AS REQUESTED)
        info_box = tk.LabelFrame(left_frame, text="🎓 Formula & Calculation Methods", bg=THEME["bg_info"], padx=5, pady=5)
        info_box.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        txt_info = tk.Text(info_box, height=8, bg=THEME["bg_info"], relief=tk.FLAT, font=("Consolas", 9))
        txt_info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(info_box, command=txt_info.yview); sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt_info.config(yscrollcommand=sb.set)
        eq_text = (
            "=== 1. SURFACE TENSION (Pendant Drop) ===\n"
            "Method: Selected Plane (Andreas et al. / Misak)\n"
            "Equation: γ = (Δρ · g · De²) / H\n"
            "   • γ (Gamma): Surface Tension [mN/m]\n"
            "   • Δρ: Density difference (Liquid - Air) [kg/m³]\n"
            "   • g: Gravity (9.81 m/s²)\n"
            "   • De: Equatorial Diameter (Max Width)\n"
            "   • Ds: Diameter at distance De from Apex\n"
            "   • S = Ds / De (Shape Factor)\n"
            "   • 1/H = f(S) ≈ a · S^b \n"
            "     (Default constants: a=0.345, b=-2.5)\n\n"
            "=== 2. CONTACT ANGLE (Sessile Drop) ===\n"
            "Method: Tangent Angle at Intersection\n"
            "1. Baseline: Linear fit (y = mx + c) from B1, B2\n"
            "2. Profile Fit: Parabola (y' = Ax'² + Bx' + C) or Ellipse\n"
            "   (Coordinate system rotated to align with baseline)\n"
            "3. Intersection (I1, I2):\n"
            "   • Geometric crossing of Fit Curve & Baseline\n"
            "4. Tangent Slope (m_tan):\n"
            "   • Parabola: dy'/dx' = 2Ax' + B\n"
            "   • Ellipse: Implicit derivative (from F(x,y)=0)\n"
            "5. Contact Angle (θ):\n"
            "   • θ = arctan( |(m_tan - m_base)/(1 + m_tan·m_base)| )\n\n"
            "=== Ellipse Equation Used (Proof / Derivation) ===\n"
            "A) Rotated ellipse from fitEllipse: center(h,k), axes(2a,2b), angle φ\n"
            "   x' = cosφ(x-h) + sinφ(y-k)\n"
            "   y' = -sinφ(x-h) + cosφ(y-k)\n"
            "   F(x,y) = x'²/a² + y'²/b² - 1 = 0\n"
            "B) Intersections with baseline y = mx + c\n"
            "   Substitute y=mx+c into F(x,y)=0 => Ax² + Bx + C = 0\n"
            "   Discriminant D = B² - 4AC\n"
            "   If D>=0 => 2 roots => I1,I2 (contact points)\n"
            "C) Tangent from implicit form (proof)\n"
            "   For F(x,y)=0, gradient n = (Fx,Fy) is normal to curve\n"
            "   Tangent direction t is perpendicular to n\n"
            "   so t = (-Fy, Fx)\n"
            "D) Contact angle between tangent and baseline\n"
            "   baseline direction b = (1,m) (or (0,1) if vertical baseline)\n"
            "   θ = acos( t·b / (|t||b|) )\n"
            "   (interior angle in droplet is reported in this software)"
        )
        txt_info.insert(tk.END, eq_text); txt_info.config(state=tk.DISABLED)

        # === RIGHT PANEL ===
        right_frame = tk.Frame(main, bg="white")
        main.add(right_frame)

        self.cv_res = tk.Canvas(right_frame, bg="#FFFFFF", highlightthickness=0)
        self.cv_res.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        self.cv_res.bind("<ButtonPress-1>", self.on_res_click)
        self.cv_res.bind("<B1-Motion>", self.on_res_drag)
        self.cv_res.bind("<ButtonRelease-1>", self.on_res_release)

        tools = tk.Frame(right_frame, bg="white")
        tools.pack(fill=tk.X, padx=15, pady=10)

        # 0. Rotation
        f0 = tk.LabelFrame(tools, text="Step 3: Rotate Drop to Exact Vertical (Optional)", bg=THEME["bg_tool"]); f0.pack(fill=tk.X, pady=2)
        r_rot = tk.Frame(f0, bg=THEME["bg_tool"]); r_rot.pack(fill=tk.X, padx=2)
        # Select Drop (starts rotate-ROI selection)
        self.btn_select_drop_rot = ttk.Button(r_rot, text="Select Drop", command=self.start_rotate_roi, style='Accent.TButton')
        self.btn_select_drop_rot.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        # Auto Rotate executes rotation immediately
        ttk.Button(r_rot, text="Auto Rotate", command=self.perform_auto_rotate, style='Primary.TButton').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(f0, text="Reset", width=6, command=self.reset_rotate).pack(side=tk.LEFT)
        self.lbl_rot = tk.Label(f0, text="Rotation angle: 0.0°", bg=THEME["bg_tool"], fg="blue"); self.lbl_rot.pack(side=tk.LEFT, padx=5)

        # 1. Calibration
        f1 = tk.LabelFrame(tools, text="Step 4: Image Scale Calibration (Required for Surface Tension Calculations)", bg=THEME["bg_calib"]); f1.pack(fill=tk.X, pady=2)
        r1 = tk.Frame(f1, bg=THEME["bg_calib"]); r1.pack(fill=tk.X)
        tk.Label(r1, text="Real(mm):", bg=THEME["bg_calib"]).pack(side=tk.LEFT)
        self.ent_real = ttk.Entry(r1, width=6); self.ent_real.insert(0, "1.0"); self.ent_real.pack(side=tk.LEFT)
        self.btn_set_2point = ttk.Button(r1, text="Select 2 Ref Points", command=self.start_calib_manual, style='Accent.TButton')
        self.btn_set_2point.pack(side=tk.LEFT, padx=2)
        self.btn_set_box = ttk.Button(r1, text="Select Needle", command=self.start_calib_box, style='Accent.TButton')
        self.btn_set_box.pack(side=tk.LEFT, padx=2)
        ttk.Button(f1, text="Set Image Scale (Pixel/mm)", command=self.calculate_final_scale, style='Primary.TButton').pack(fill=tk.X, pady=2)

        # 2. ST
        f2 = tk.LabelFrame(tools, text="Step 5: Surface Tension Calculations (Pendant Drop Method)", bg=THEME["bg_st"]); f2.pack(fill=tk.X, pady=2)
        r_st = tk.Frame(f2, bg=THEME["bg_st"]); r_st.pack(fill=tk.X)
        tk.Label(r_st, text="a:", bg=THEME["bg_st"]).pack(side=tk.LEFT)
        self.ent_a = ttk.Entry(r_st, width=5); self.ent_a.insert(0, "0.345"); self.ent_a.pack(side=tk.LEFT)
        tk.Label(r_st, text="b:", bg=THEME["bg_st"]).pack(side=tk.LEFT)
        self.ent_b = ttk.Entry(r_st, width=5); self.ent_b.insert(0, "-2.5"); self.ent_b.pack(side=tk.LEFT)
        ttk.Button(r_st, text="Calculate Surface Tension", command=self.calc_st, style='PastelRed.TButton').pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # 3. CA
        f3 = tk.LabelFrame(tools, text="Step 6: Contact Angle Calculations (Sessile Drop Method)", bg=THEME["bg_ca"]); f3.pack(fill=tk.X, pady=2)
        r_ca1 = tk.Frame(f3, bg=THEME["bg_ca"]); r_ca1.pack(fill=tk.X, pady=2)
        self.btn_set_baseline = ttk.Button(r_ca1, text="Set Baseline Points (B1,B2)", command=self.start_baseline, style='Accent.TButton')
        self.btn_set_baseline.pack(side=tk.LEFT, padx=2)
        ttk.Button(r_ca1, text="Apply Baseline", command=self.apply_baseline, style='Primary.TButton').pack(side=tk.LEFT, padx=2)
        
        tk.Radiobutton(r_ca1, text="Parabola", variable=self.fit_method, value="Parabola", bg=THEME["bg_ca"]).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(r_ca1, text="Ellipse", variable=self.fit_method, value="Ellipse", bg=THEME["bg_ca"]).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(r_ca1, text="Robust", variable=self.fit_method, value="Robust", bg=THEME["bg_ca"]).pack(side=tk.LEFT, padx=5)
        
        self.btn_select_roi = ttk.Button(r_ca1, text="Select Drop", command=self.start_roi_ca, style='Accent.TButton')
        self.btn_select_roi.pack(side=tk.LEFT, padx=2)
        ttk.Button(r_ca1, text="Cal Drop Edge", command=self.calc_drop_fit, style='PastelRed.TButton').pack(side=tk.LEFT, padx=2)
        self.btn_pen = tk.Button(r_ca1, text="✏", bg="#00C853", fg="white", width=3, command=self.toggle_pen_mode)
        self.btn_pen.pack(side=tk.LEFT, padx=2)
        self.btn_erase = tk.Button(r_ca1, text="🧹", bg=THEME["bg_tool"], width=3, command=self.toggle_erase_mode)
        self.btn_erase.pack(side=tk.LEFT, padx=2)
        ttk.Button(r_ca1, text="Fit Edge", command=self.fit_edge, style='PastelRed.TButton').pack(side=tk.LEFT, padx=2)
        
        r_ca2 = tk.Frame(f3, bg=THEME["bg_ca"]); r_ca2.pack(fill=tk.X, pady=2)
        ttk.Button(r_ca2, text="Calculate Contact Angle", command=self.calc_contact_angle_final, style='PastelRed.TButton').pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)

        # 4. Export
        f4 = tk.Frame(tools, bg="white"); f4.pack(fill=tk.X, pady=10)
        ttk.Button(f4, text="📋 Copy Results", command=self.copy_results, style='PastelRed.TButton').pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(f4, text="📋 Copy IMG", command=self.copy_image_clip, style='PastelRed.TButton').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(f4, text="💾 Save PNG", command=self.save_png, style='PastelRed.TButton').pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(tools, text="❌ Clear All", command=self.clear_all).pack(fill=tk.X)

    def create_entry_slider(self, p, lbl, var, vmin, vmax, r):
        tk.Label(p, text=lbl, bg=THEME["bg_vid"]).grid(row=r, column=0, sticky="w")
        ttk.Scale(p, from_=vmin, to=vmax, variable=var, command=self._snap_int(var, self.on_live_adjust)).grid(row=r, column=1, sticky="ew", padx=5)
        tk.Entry(p, textvariable=var, width=5).grid(row=r, column=2)
        tk.Button(p, text="-", width=2, command=lambda v=var, a=vmin, b=vmax: self._step_var(v, -1, a, b)).grid(row=r, column=3)
        tk.Button(p, text="+", width=2, command=lambda v=var, a=vmin, b=vmax: self._step_var(v, 1, a, b)).grid(row=r, column=4)
        ttk.Button(p, text="Apply", width=5, command=self.update_view, style='PastelRed.TButton').grid(row=r, column=5, padx=2)

    def _snap_int(self, var, callback=None):
        def _cmd(v):
            var.set(int(round(float(v))))
            if callback:
                callback()
        return _cmd

    def _step_var(self, var, delta, vmin, vmax, integer=True, callback=None):
        try:
            cur = int(round(float(var.get())))
        except Exception:
            cur = 0
        new_val = max(vmin, min(vmax, cur + delta))
        var.set(new_val)
        if callback:
            callback()
        else:
            self.on_live_adjust()

    # --- VIDEO ENGINE ---
    def load_video(self):
        path = filedialog.askopenfilename()
        if not path: return
        self.lbl_file.config(text=f"Loading: {os.path.basename(path)}...")
        self.root.update()
        if self.temp_file and os.path.exists(self.temp_file):
            try: os.remove(self.temp_file)
            except: pass
        try:
            temp_dir = tempfile.gettempdir(); ext = os.path.splitext(path)[1] or ".mp4"
            safe_path = os.path.join(temp_dir, f"da_temp{ext}"); shutil.copy2(path, safe_path); self.temp_file = safe_path
            if self.cap: self.cap.release()
            self.cap = cv2.VideoCapture(self.temp_file)
            if not self.cap.isOpened(): messagebox.showerror("Error", "Failed"); return
            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)); self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
            self.sl_frame.config(to=max(0, self.total_frames-1)); self.sl_frame.set(0); self.set_frame(0)
            self.lbl_file.config(text=f"📄 {os.path.basename(path)}")
        except Exception as e: messagebox.showerror("Error", str(e))

    def get_previous_frames(self, idx, count):
        if not self.cap or idx <= 0 or count <= 0:
            return deque(maxlen=max(1, count))
        refs = deque(maxlen=max(1, count))
        start = max(0, idx - count)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        for _ in range(start, idx):
            ret, frame = self.cap.read()
            if not ret:
                break
            refs.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        return refs

    def set_frame(self, idx):
        if not self.cap: return
        frame_idx = int(idx)
        diff_count = max(1, min(20, int(self.v_diff_frames.get())))
        self.prev_frames_raw = self.get_previous_frames(frame_idx, diff_count)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx); ret, frame = self.cap.read()
        if ret:
            self.original_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self.update_view()
            self.update_time_display(frame_idx=frame_idx)

    def fmt_time(self, ms): s,ms=divmod(ms,1000); m,s=divmod(s,60); return f"{int(m):02}:{int(s):02}:{int(ms):03}"
    def parse_time_to_ms(self, text):
        parts = text.strip().split(":")
        if len(parts) != 3:
            raise ValueError("Time must be in mm:ss:ms format")
        minutes, seconds, milliseconds = [int(part) for part in parts]
        if minutes < 0 or not 0 <= seconds < 60 or not 0 <= milliseconds < 1000:
            raise ValueError("Time is out of range")
        return ((minutes * 60) + seconds) * 1000 + milliseconds

    def update_time_display(self, frame_idx=None, force=False):
        if frame_idx is None:
            frame_idx = int(round(self.sl_frame.get())) if self.cap else 0
        current_ms = (frame_idx / self.fps) * 1000 if self.fps else 0
        total_ms = (self.total_frames / self.fps) * 1000 if self.fps else 0
        if force or not self.is_time_entry_editing:
            self.current_time_var.set(self.fmt_time(current_ms))
        self.total_time_var.set(self.fmt_time(total_ms))
        self.update_frame_display(frame_idx=frame_idx, force=force)

    def update_frame_display(self, frame_idx=None, force=False):
        if frame_idx is None:
            frame_idx = int(round(self.sl_frame.get())) if self.cap else 0
        current_frame = frame_idx + 1 if self.total_frames > 0 else 0
        if force or not self.is_frame_entry_editing:
            self.current_frame_var.set(str(current_frame))
        self.total_frame_var.set(str(self.total_frames))

    def on_time_entry_focus_in(self, _event=None):
        self.is_time_entry_editing = True

    def on_time_entry_focus_out(self, _event=None):
        self.is_time_entry_editing = False
        self.update_time_display(force=True)

    def cancel_time_entry(self, _event=None):
        self.is_time_entry_editing = False
        self.update_time_display(force=True)
        return "break"

    def on_frame_entry_focus_in(self, _event=None):
        self.is_frame_entry_editing = True

    def on_frame_entry_focus_out(self, _event=None):
        self.is_frame_entry_editing = False
        self.update_frame_display(force=True)

    def cancel_frame_entry(self, _event=None):
        self.is_frame_entry_editing = False
        self.update_frame_display(force=True)
        return "break"

    def jump_to_time_from_entry(self, _event=None):
        if not self.cap or self.total_frames <= 0:
            return "break"
        try:
            target_ms = self.parse_time_to_ms(self.current_time_var.get())
        except Exception:
            messagebox.showwarning("Invalid Time", "Please enter time in mm:ss:ms format, for example 00:07:000")
            self.update_time_display(force=True)
            return "break"
        total_ms = (self.total_frames / self.fps) * 1000 if self.fps else 0
        target_ms = max(0, min(target_ms, total_ms))
        frame_idx = int(round((target_ms / 1000.0) * self.fps)) if self.fps else 0
        frame_idx = max(0, min(self.total_frames - 1, frame_idx))
        self.is_time_entry_editing = False
        self.sl_frame.set(frame_idx)
        self.set_frame(frame_idx)
        return "break"

    def jump_to_frame_from_entry(self, _event=None):
        if not self.cap or self.total_frames <= 0:
            return "break"
        try:
            target_frame = int(self.current_frame_var.get())
        except Exception:
            messagebox.showwarning("Invalid Frame", "Please enter a frame number such as 1, 25, or 300")
            self.update_frame_display(force=True)
            return "break"
        target_frame = max(1, min(self.total_frames, target_frame))
        frame_idx = target_frame - 1
        self.is_frame_entry_editing = False
        self.sl_frame.set(frame_idx)
        self.set_frame(frame_idx)
        return "break"

    def on_seek(self, v): self.set_frame(float(v))
    def step_frame(self, s):
        c = self.sl_frame.get()
        target = c + s
        if 0 <= target < self.total_frames:
            self.sl_frame.set(target)
            self.set_frame(target)

    def toggle_play(self): self.is_playing = not self.is_playing; self.btn_play.config(text="⏸" if self.is_playing else "▶"); self.run_play() if self.is_playing else None
    def run_play(self): 
        if self.is_playing and self.cap:
            c=self.sl_frame.get()
            if c<self.total_frames-1: 
                self.sl_frame.set(c+1); self.set_frame(c+1); self.root.after(33, self.run_play)
            else: self.is_playing=False; self.btn_play.config(text="▶")

    def toggle_binary(self):
        self.use_binary = not self.use_binary
        self.btn_binary.config(text="Solid Black (ON)" if self.use_binary else "Solid Black (Off)", bg=THEME["accent"] if self.use_binary else THEME["bg_tool"], fg="white" if self.use_binary else "black")
        self.update_view()

    def on_live_adjust(self, _=None):
        if self.original_frame is not None:
            self.update_view()

    def on_diff_frames_change(self, value=None):
        if value is not None and not hasattr(value, "widget"):
            frame_count = int(round(float(value)))
        else:
            frame_count = int(round(float(self.v_diff_frames.get())))
        self.v_diff_frames.set(max(1, min(20, frame_count)))
        if self.original_frame is not None:
            self.update_view()

    def toggle_differential(self):
        self.use_differential = not self.use_differential
        self.btn_diff.config(
            text="Differential (ON)" if self.use_differential else "Differential (Off)",
            bg=THEME["accent"] if self.use_differential else THEME["bg_tool"],
            fg="white" if self.use_differential else "black"
        )
        if self.use_differential and self.original_frame is None:
            messagebox.showwarning("Differential Mode", "No reference frame found.\nPlease load a video first.")
            self.use_differential = False
            self.btn_diff.config(text="Differential (Off)", bg=THEME["bg_tool"], fg="black")
            return
        if self.cap and self.total_frames > 0:
            if self.use_differential:
                current_frame = int(round(self.sl_frame.get()))
                min_diff_frame = min(max(0, int(self.v_diff_frames.get()) - 1), self.total_frames - 1)
                target_frame = min_diff_frame if current_frame < min_diff_frame else current_frame
            else:
                target_frame = 0
            self.sl_frame.set(target_frame)
            self.set_frame(target_frame)
        else:
            self.update_view()

    def update_view(self):
        if self.original_frame is None: return
        img = self.original_frame.copy()
        alpha = 1.0 + (self.v_contrast.get()/100.0); beta = self.v_bright.get()
        img = cv2.convertScaleAbs(img, alpha=alpha, beta=beta)
        if self.use_differential:
            frame_idx = int(self.sl_frame.get()) if self.cap else 0
            diff_count = max(1, min(20, int(self.v_diff_frames.get())))
            self.prev_frames_raw = self.get_previous_frames(frame_idx, diff_count)
            if self.prev_frames_raw:
                diff_stack = []
                for ref_frame in self.prev_frames_raw:
                    ref_adj = cv2.convertScaleAbs(ref_frame.copy(), alpha=alpha, beta=beta)
                    diff_stack.append(cv2.cvtColor(cv2.absdiff(img, ref_adj), cv2.COLOR_RGB2GRAY))
                gray_diff = np.max(np.stack(diff_stack, axis=0), axis=0)
            else:
                gray_diff = np.zeros(img.shape[:2], dtype=np.uint8)
            thr = int(self.v_diff_thresh.get())
            result = np.full(gray_diff.shape, 255, dtype=np.uint8)
            mask = gray_diff >= thr
            result[mask] = np.clip(255 - gray_diff[mask], 0, 255)
            img = cv2.cvtColor(result, cv2.COLOR_GRAY2RGB)
        if self.use_binary:
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            _, thresh = cv2.threshold(gray, self.v_thresh.get(), 255, cv2.THRESH_BINARY)
            img = cv2.cvtColor(thresh, cv2.COLOR_GRAY2RGB)
        self.display_frame = img
        canvas_w, canvas_h = self.get_vid_canvas_size()
        h,w = img.shape[:2]; r = min(canvas_w/w, canvas_h/h); nw,nh = int(w*r), int(h*r); self.img_scale_left = r
        tk_img = ImageTk.PhotoImage(image=Image.fromarray(cv2.resize(img,(nw,nh))))
        self.cv_vid.delete("img"); self.cv_vid.create_image(0,0,image=tk_img, anchor=tk.NW, tags="img"); self.cv_vid.image = tk_img; self.draw_crop()

    def get_vid_canvas_size(self):
        canvas_w = max(1, self.cv_vid.winfo_width())
        canvas_h = max(1, self.cv_vid.winfo_height())
        if canvas_w <= 1 or canvas_h <= 1:
            return CANVAS_W, CANVAS_H
        return canvas_w, canvas_h

    def on_vid_canvas_configure(self, event):
        target_h = max(200, int(event.width * 3 / 4))
        if abs(event.height - target_h) > 1:
            self.cv_vid.configure(height=target_h)
            return
        if self.original_frame is not None:
            self.update_view()

    # --- Crop ---
    def on_vid_click(self,e):
        x,y=e.x,e.y
        if not self.crop_rect: self.crop_rect=[x,y,x,y]; self.drag_mode='new'; self.start_xy=(x,y)
        else:
            x1,y1,x2,y2=self.crop_rect; th=15
            if abs(x-x1)<th and abs(y-y1)<th: self.drag_mode='nw'
            elif abs(x-x2)<th and abs(y-y2)<th: self.drag_mode='se'
            elif x1<x<x2 and y1<y<y2: self.drag_mode='move'; self.start_xy=(x,y)
            else: self.crop_rect=[x,y,x,y]; self.drag_mode='new'; self.start_xy=(x,y)
    def on_vid_drag(self,e):
        canvas_w, canvas_h = self.get_vid_canvas_size()
        mx,my = max(0,min(canvas_w,e.x)), max(0,min(canvas_h,e.y))
        if self.drag_mode=='new': self.crop_rect=[min(self.start_xy[0],mx),min(self.start_xy[1],my),max(self.start_xy[0],mx),max(self.start_xy[1],my)]
        elif self.drag_mode=='nw': self.crop_rect=[mx,my,self.crop_rect[2],self.crop_rect[3]]
        elif self.drag_mode=='se': self.crop_rect=[self.crop_rect[0],self.crop_rect[1],mx,my]
        elif self.drag_mode=='move': dx=mx-self.start_xy[0]; dy=my-self.start_xy[1]; x1,y1,x2,y2=self.crop_rect; self.crop_rect=[x1+dx,y1+dy,x2+dx,y2+dy]; self.start_xy=(mx,my)
        self.draw_crop()
    def on_vid_release(self,e): self.drag_mode=None
    def draw_crop(self):
        self.cv_vid.delete("crop")
        if self.crop_rect: self.cv_vid.create_rectangle(self.crop_rect, outline=THEME["accent"], width=2, tags="crop")

    def do_crop(self):
        if self.display_frame is None or not self.crop_rect: return
        x1,y1,x2,y2 = [int(v/self.img_scale_left) for v in self.crop_rect]
        h,w = self.display_frame.shape[:2]; x1=max(0,x1); y1=max(0,y1); x2=min(w,x2); y2=min(h,y2)
        if x2-x1<5: return
        self.cropped_img = self.display_frame[y1:y2, x1:x2].copy()
        self.rotated_img = self.cropped_img.copy()
        self.clear_all()

    def clear_all(self):
        self.mode = "NONE"
        self.roi_drag = False
        self.drag_pt = None
        self.calib_points=[]; self.baseline_points=[]; self.ca_roi=None; self.auto_scale_rect=None; self.rotate_roi=None
        self.baseline_params = None; self.drop_contour = None; self.fit_params = None
        self.drawn_fit_points = None; self.edge_pts_global = None
        self.scale_factor=None
        self.total_rotation = 0.0
        self.last_mode_calc = None
        self.export_data_st={}; self.export_data_ca={}
        self.pen_mode = False
        self.erase_mode = False
        if self.btn_pen: self.btn_pen.config(bg="#00C853", fg="white")
        self.btn_erase.config(bg=THEME["bg_tool"], fg="black")
        self.cv_res.config(cursor="")
        self.lbl_rot.config(text="Rot: 0.0°")
        if self.btn_set_2point: self.btn_set_2point.configure(style='Accent.TButton')
        if self.btn_set_box: self.btn_set_box.configure(style='Accent.TButton')
        if self.btn_set_baseline: self.btn_set_baseline.configure(style='Accent.TButton')
        if self.btn_select_roi: self.btn_select_roi.configure(style='Accent.TButton')
        if self.btn_select_drop_rot: self.btn_select_drop_rot.configure(style='Accent.TButton')
        if self.cropped_img is not None: self.rotated_img = self.cropped_img.copy()
        self.cv_res.delete("all")
        self.show_res()

    def show_res(self):
        if self.rotated_img is None: return
        cw,ch = self.cv_res.winfo_width(), self.cv_res.winfo_height()
        if cw<10: cw,ch=500,500
        h,w = self.rotated_img.shape[:2]
        r = min(cw/w, ch/h)
        self.img_scale_right = r
        nw,nh = int(w*r), int(h*r)
        self.tk_res = ImageTk.PhotoImage(image=Image.fromarray(cv2.resize(self.rotated_img,(nw,nh))))
        self.cv_res.delete("img"); self.cv_res.create_image(cw//2, ch//2, image=self.tk_res, tags="img")
        self.cv_res.image = self.tk_res
        self.offset_x=(cw-nw)//2; self.offset_y=(ch-nh)//2
        
        if self.scale_factor:
            self.cv_res.delete("ui_ov_scale")
            self.cv_res.create_text(cw-10, 20, text=f"Scale: {self.scale_factor:.2f} px/mm", anchor="e", fill="red", font=("Arial",10,"bold"), tags="ui_ov_scale")

    # --- Interactive ---
    def start_calib_manual(self): 
        self.mode="CALIB_MANUAL"; self.calib_points=[]
        self.cv_res.delete("ui"); self.clear_ov()
        self.btn_set_2point.configure(style='Waiting.TButton')
        self.root.update()
    
    def start_calib_box(self): 
        self.mode="CALIB_BOX"; self.auto_scale_rect=None
        self.cv_res.delete("ui"); self.clear_ov()
        self.btn_set_box.configure(style='Waiting.TButton')
        self.root.update()
    
    def start_baseline(self): 
        self.mode="BASE"; self.baseline_points=[]
        self.cv_res.delete("ui_base"); self.cv_res.delete("base_line")
        # เปลี่ยนสีปุ่มเป็นสีเหลืองสว่าง
        self.btn_set_baseline.configure(style='Waiting.TButton')
        self.root.update()
        
    def start_roi_ca(self): 
        self.mode="ROI"; self.ca_roi=None
        self.cv_res.delete("ui_roi"); self.cv_res.delete("fit_curve"); self.cv_res.delete("tangent"); self.cv_res.delete("ov_ca")
        self.btn_select_roi.configure(style='Waiting.TButton')
        self.root.update()

    def start_draw_edge(self):
        self.calc_drop_fit()
        
    def start_rotate_roi(self): 
        self.mode="ROTATE_ROI"; self.rotate_roi=None
        self.cv_res.delete("ui_rot")
        self.btn_select_drop_rot.configure(style='Waiting.TButton')
        self.root.update()
    def clear_ov(self): self.cv_res.delete("ui_scale_box"); self.cv_res.delete("ui_scale_final"); self.cv_res.delete("ui_line")

    def on_res_click(self,e):
        if self.rotated_img is None: return
        if self.pen_mode:
            self._do_add_point_at(e.x, e.y)
            return
        if self.erase_mode:
            self._do_erase_at(e.x, e.y)
            return
        if self.mode in ["ROI", "CALIB_BOX", "ROTATE_ROI"]: self.roi_start=(e.x,e.y); self.roi_drag=True; return
        pts = self.calib_points if self.mode=="CALIB_MANUAL" else self.baseline_points
        for p in pts:
            if p.contains(e.x,e.y): self.drag_pt=p; return
        if self.mode in ["CALIB_MANUAL","BASE"] and len(pts)<2:
            lbl = f"B{len(pts)+1}" if self.mode=="BASE" else ""
            # ปรับตำแหน่ง label ตาม B1 หรือ B2
            if lbl == "B1":
                pts.append(DraggablePoint(self.cv_res,e.x,e.y,lambda:self.upd_ui(pts),label=lbl,tag="ui", label_offset_x=-25, label_offset_y=-30))
            elif lbl == "B2":
                pts.append(DraggablePoint(self.cv_res,e.x,e.y,lambda:self.upd_ui(pts),label=lbl,tag="ui", label_offset_x=25, label_offset_y=-30))
            else:
                pts.append(DraggablePoint(self.cv_res,e.x,e.y,lambda:self.upd_ui(pts),label=lbl,tag="ui"))
            self.upd_ui(pts)
            # เปลี่ยนสีปุ่มกลับเมื่อจุด B1 และ B2 ถูกสร้างแล้ว
            if self.mode=="BASE" and len(self.baseline_points)==2:
                self.btn_set_baseline.configure(style='Accent.TButton')

    def on_res_drag(self,e):
        if self.pen_mode:
            self._do_add_point_at(e.x, e.y)
            return
        if self.erase_mode:
            self._do_erase_at(e.x, e.y)
            return
        if self.mode in ["ROI", "CALIB_BOX", "ROTATE_ROI"] and self.roi_drag:
            c=[min(self.roi_start[0],e.x), min(self.roi_start[1],e.y), max(self.roi_start[0],e.x), max(self.roi_start[1],e.y)]
            tag_map = {"ROI":"ui_roi", "CALIB_BOX":"ui_scale_box", "ROTATE_ROI":"ui_rot"}
            col_map = {"ROI":THEME["roi_box"], "CALIB_BOX":"red", "ROTATE_ROI":"blue"}
            tag=tag_map[self.mode]; col=col_map[self.mode]
            self.cv_res.delete(tag)
            self.cv_res.create_rectangle(c, outline=col, width=2, tags=tag)
            if self.mode=="ROI": self.ca_roi=c
            elif self.mode=="CALIB_BOX": self.auto_scale_rect=c
            else: self.rotate_roi=c
            return
        if hasattr(self,'drag_pt') and self.drag_pt: self.drag_pt.move(e.x,e.y)

    def on_res_release(self,e):
        # For CALIB_BOX: keep the drawn box and waiting button state
        if self.mode=="ROTATE_ROI" and self.roi_drag:
            # Select Drop waiting-state -> revert style
            self.btn_select_drop_rot.configure(style='Accent.TButton')
        elif self.mode=="ROI" and self.roi_drag:
            self.btn_select_roi.configure(style='Accent.TButton')
        self.drag_pt=None; self.roi_drag=False

    def upd_ui(self, pts):
        if self.mode == "BASE": return # Don't auto draw line for base, wait for apply
        self.cv_res.delete("ui_line")
        if len(pts)==2:
            self.cv_res.create_line(pts[0].x,pts[0].y,pts[1].x,pts[1].y, fill="red", dash=(4,2), tags="ui_line")

    def calculate_final_scale(self):
        try: self.real_mm = float(self.ent_real.get())
        except: return
        # If user drew a calibration box (Select Needle), compute scale now
        if self.auto_scale_rect is not None:
            self.calc_auto_scale()
            return
        if self.mode=="CALIB_MANUAL" and len(self.calib_points)==2:
             p1,p2 = self.calib_points
             dist = math.hypot(p1.x-p2.x, p1.y-p2.y) / self.img_scale_right
             self.scale_factor = dist/self.real_mm
             self.cv_res.delete("ui"); self.calib_points=[]
             self.cv_res.delete("ui_scale_final")
             self.cv_res.create_line(p1.x, p1.y, p2.x, p2.y, fill="red", width=2, tags="ui_scale_final")
             self.draw_ref(p1.x, p1.y, p2.x, p2.y)
             self.mode="NONE"
             self.btn_set_2point.configure(style='Accent.TButton')
             self.show_res()

    def calc_auto_scale(self):
        if not self.auto_scale_rect or self.rotated_img is None: return
        sc,ox,oy = self.img_scale_right, self.offset_x, self.offset_y
        x1,y1,x2,y2 = self.auto_scale_rect
        rx1=int((x1-ox)/sc); ry1=int((y1-oy)/sc); rx2=int((x2-ox)/sc); ry2=int((y2-oy)/sc)
        h,w = self.rotated_img.shape[:2]
        rx1=max(0,rx1); ry1=max(0,ry1); rx2=min(w,rx2); ry2=min(h,ry2)
        if rx2-rx1<2: return
        roi = self.rotated_img[ry1:ry2, rx1:rx2]
        gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
        cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts: messagebox.showerror("Err","No object found"); return
        c = max(cnts, key=cv2.contourArea)
        bx, by, bw, bh = cv2.boundingRect(c)
        try: self.real_mm = float(self.ent_real.get())
        except: return
        self.scale_factor = bw / self.real_mm
        
        cy = by + bh//2
        lx = (bx+rx1)*sc + ox; ly = (cy+ry1)*sc + oy
        rx = (bx+bw+rx1)*sc + ox; ry = (cy+ry1)*sc + oy
        self.cv_res.delete("ui_scale_box"); self.cv_res.delete("ui_scale_final")
        self.cv_res.create_line(lx,ly,rx,ry, fill="red", width=2, tags="ui_scale_final")
        self.draw_ref(lx,ly,rx,ry)
        self.mode="NONE"
        self.btn_set_box.configure(style='Accent.TButton')
        self.show_res()

    def draw_ref(self, x1, y1, x2, y2):
        left_x = min(x1, x2)
        # Reference text removed per user request (was: "Ref: xx mm")
        return

    # --- Rotation ---
    def perform_auto_rotate(self):
        if not self.rotate_roi or self.rotated_img is None: return
        sc,ox,oy = self.img_scale_right, self.offset_x, self.offset_y
        x1,y1,x2,y2 = self.rotate_roi
        rx1=int((x1-ox)/sc); ry1=int((y1-oy)/sc); rx2=int((x2-ox)/sc); ry2=int((y2-oy)/sc)
        h,w = self.rotated_img.shape[:2]
        rx1=max(0,rx1); ry1=max(0,ry1); rx2=min(w,rx2); ry2=min(h,ry2)
        if rx2-rx1<5: return
        roi = self.rotated_img[ry1:ry2, rx1:rx2]
        gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
        cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts: return
        c = max(cnts, key=cv2.contourArea)
        if len(c) >= 5:
            (xc,yc), (MA,ma), angle = cv2.fitEllipse(c)
            rot_deg = 0
            if angle > 90: rot_deg = 180 - angle
            else: rot_deg = -angle
            self.total_rotation += rot_deg
            M = cv2.getRotationMatrix2D((w/2, h/2), rot_deg, 1)
            self.rotated_img = cv2.warpAffine(self.rotated_img, M, (w,h), borderMode=cv2.BORDER_REPLICATE)
            self.cv_res.delete("ui_rot")
            self.show_res()
            self.lbl_rot.config(text=f"Rotation angle: {self.total_rotation:.1f}°")
            self.mode="NONE"
            self.btn_select_drop_rot.configure(style='Accent.TButton')

    def reset_rotate(self):
        if self.cropped_img is not None:
            self.rotated_img = self.cropped_img.copy()
            self.total_rotation = 0.0
            self.lbl_rot.config(text="Rotation angle: 0.0°")
            self.btn_select_drop_rot.configure(style='Accent.TButton')
            self.clear_all()

    # --- ST ---
    def calc_st(self):
        if not self.scale_factor: messagebox.showerror("Err","Set Scale!"); return
        self.cv_res.delete("ov_st")
        self.cv_res.delete("ui_ov_scale") # Clear old scale text
        self.last_mode_calc = "ST"
        
        gray = cv2.cvtColor(self.rotated_img, cv2.COLOR_RGB2GRAY)
        blur = cv2.GaussianBlur(gray,(5,5),0)
        _, thresh = cv2.threshold(blur,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
        cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts: return
        c = max(cnts, key=cv2.contourArea)
        
        pts=c[:,0,:]; apex=pts[np.argmax(pts[:,1])]
        mask=np.zeros_like(gray); cv2.drawContours(mask,[c],-1,255,-1)
        y,x,h,w = cv2.boundingRect(c)
        
        max_w=0; de_y=apex[1]; de_x1=apex[0]; de_x2=apex[0]
        for r in range(y, apex[1] + 1):
            row=mask[r,:]
            idx=np.where(row>0)[0]
            if len(idx)>0:
                wid=idx[-1]-idx[0]
                if wid>max_w: max_w=wid; de_y=r; de_x1=idx[0]; de_x2=idx[-1]
        de_px=max_w
        
        ds_y=int(apex[1]-de_px); ds_px=0; ds_x1=0; ds_x2=0
        if 0<=ds_y<gray.shape[0]:
            row=mask[ds_y,:]
            idx=np.where(row>0)[0]
            if len(idx)>0: ds_px=idx[-1]-idx[0]; ds_x1=idx[0]; ds_x2=idx[-1]
        if ds_px==0: return
        
        try: val_a=float(self.ent_a.get()); val_b=float(self.ent_b.get())
        except: val_a=0.345; val_b=-2.5
        S=ds_px/de_px; inv_H=val_a*(S**val_b)
        de_m = (de_px/self.scale_factor)/1000.0
        gamma = (DELTA_RHO * GRAVITY * de_m**2) * inv_H * 1000
        
        self.export_data_st = {"Scale":f"{self.scale_factor:.2f}", "Ds":f"{(ds_px/self.scale_factor):.3f}", "De":f"{(de_px/self.scale_factor):.3f}", "ST":f"{gamma:.2f}"}
        
        sc,ox,oy = self.img_scale_right, self.offset_x, self.offset_y
        def to_c(x,y): return x*sc+ox, y*sc+oy
        w_can = self.cv_res.winfo_width()
        
        # Draw De (width=3)
        tx1,ty1=to_c(de_x1,de_y); tx2,ty2=to_c(de_x2,de_y)
        self.cv_res.create_line(tx1,ty1,tx2,ty2, fill=THEME["line_de"], width=3, tags="ov_st")
        
        # Vertical De (width=3)
        # Start at the bottom-most point of the drop and center on the De horizontal line.
        # Vertical length equals De (scaled).
        center_x_img = (de_x1 + de_x2) / 2.0
        base_x_canvas, base_y_canvas = to_c(center_x_img, apex[1])
        # length in canvas coordinates = de_px * scale
        length_canvas = de_px * sc
        top_y_canvas = base_y_canvas - length_canvas
        self.cv_res.create_line(base_x_canvas, base_y_canvas, base_x_canvas, top_y_canvas, fill=THEME["line_de"], dash=(4,4), width=3, tags="ov_st")
        
        # Draw Ds (width=3)
        sx1,sy1=to_c(ds_x1,ds_y); sx2,sy2=to_c(ds_x2,ds_y)
        self.cv_res.create_line(sx1,sy1,sx2,sy2, fill=THEME["line_ds"], width=3, tags="ov_st")
        
        # TEXT BLOCK (Top-Right)
        start_y = 20; gap = 25
        lines = [
            (f"Scale: {self.scale_factor:.2f} px/mm", "red"),
            (f"Ds: {(ds_px/self.scale_factor):.3f} mm", THEME["line_ds"]),
            (f"De: {(de_px/self.scale_factor):.3f} mm", THEME["line_de"]),
            (f"Surface Tension: {gamma:.2f} mN/m", "blue")
        ]
        for txt, col in lines:
            self.cv_res.create_text(w_can-10, start_y, text=txt, anchor="e", fill=col, font=("Arial", 14, "bold"), tags="ov_st")
            start_y += gap

    # --- CA ---
    def apply_baseline(self):
        if len(self.baseline_points)!=2: messagebox.showerror("Err","Set 2 points first"); return
        p1,p2 = self.baseline_points
        if p2.x != p1.x:
            m = (p2.y - p1.y) / (p2.x - p1.x)
            c_val = p1.y - m * p1.x
            w = self.cv_res.winfo_width()
            self.cv_res.delete("base_line")
            self.cv_res.create_line(0, c_val, w, m*w+c_val, fill=THEME["line_base"], width=3, tags="base_line")
            self.cv_res.tag_raise("base_line")
            
            sc, ox, oy = self.img_scale_right, self.offset_x, self.offset_y
            ix1, iy1 = (p1.x - ox) / sc, (p1.y - oy) / sc
            ix2, iy2 = (p2.x - ox) / sc, (p2.y - oy) / sc
            m_img = (iy2 - iy1) / (ix2 - ix1)
            c_img = iy1 - m_img * ix1
            self.baseline_params = (m_img, c_img)
        else: self.baseline_params = (1e9, (p1.x - self.offset_x)/self.img_scale_right)

    def _extract_drop_contour_from_roi_thresh(self, thresh):
        if thresh is None or thresh.size == 0:
            return None, None, None

        work = thresh.copy()

        # 1) Row sums of foreground (drop = 255)
        row_sums = np.sum(work == 255, axis=1)

        # 2) Surface spike detection (robust)
        surface_y = work.shape[0] - 1
        rs = row_sums.astype(np.float32)
        rs_smooth = cv2.GaussianBlur(rs.reshape(-1, 1), (1, 11), 0).ravel()
        diff = np.diff(rs_smooth, prepend=rs_smooth[0])
        strong_jump = np.percentile(diff, 90) if len(diff) > 10 else 0
        h = work.shape[0]
        candidates = np.where((rs_smooth > 50) & (diff > strong_jump) & (np.arange(len(rs_smooth)) > int(0.25 * h)))[0]
        if len(candidates) > 0:
            surface_y = int(candidates[0])
        else:
            surface_y = int(np.argmax(diff)) if len(diff) > 0 else work.shape[0] - 1

        # 3) Remove region below surface
        if 0 <= surface_y < work.shape[0]:
            work[surface_y:, :] = 0

        # Connect nearby pixels to improve contour continuity
        kernel = np.ones((3, 3), np.uint8)
        work = cv2.morphologyEx(work, cv2.MORPH_CLOSE, kernel, iterations=1)

        # 4) Use connected component that contains lowest foreground point
        ys, xs = np.where(work == 255)
        if len(ys) > 0:
            lowest_idx = int(np.argmax(ys))
            seed_x = int(xs[lowest_idx])
            seed_y = int(ys[lowest_idx])

            num_labels, labels, stats, _ = cv2.connectedComponentsWithStats((work > 0).astype(np.uint8), connectivity=8)
            if num_labels > 1:
                target_label = labels[seed_y, seed_x]
                if target_label > 0:
                    component = np.zeros_like(work)
                    component[labels == target_label] = 255
                    component_filled = self._fill_holes(component)
                    cnts, _ = cv2.findContours(component_filled, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    if cnts:
                        return max(cnts, key=cv2.contourArea), component_filled, surface_y

        # 5) Fallback: largest external contour
        cnts, _ = cv2.findContours(work, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            best = max(cnts, key=cv2.contourArea)
            component = np.zeros_like(work)
            cv2.drawContours(component, [best], -1, 255, -1)
            component_filled = self._fill_holes(component)
            cnts2, _ = cv2.findContours(component_filled, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cnts2:
                return max(cnts2, key=cv2.contourArea), component_filled, surface_y
            return best, component_filled, surface_y
        return None, None, surface_y

    def _fill_holes(self, mask):
        if mask is None or mask.size == 0:
            return mask
        h, w = mask.shape[:2]
        flood = mask.copy()
        ff_mask = np.zeros((h + 2, w + 2), np.uint8)
        cv2.floodFill(flood, ff_mask, (0, 0), 255)
        holes = cv2.bitwise_not(flood)
        return cv2.bitwise_or(mask, holes)

    def _mask_below_baseline_in_roi(self, mask, rx1, ry1, baseline_params, margin_px=2.0):
        if mask is None or mask.size == 0 or baseline_params is None:
            return mask
        m, c0 = baseline_params
        work = mask.copy()
        h, w = work.shape[:2]
        yy, xx = np.indices((h, w), dtype=np.float32)
        x_global = xx + float(rx1)
        y_global = yy + float(ry1)
        if abs(m) > 1e8:
            return work
        baseline_y = m * x_global + c0 + float(margin_px)
        work[y_global > baseline_y] = 0
        return work

    def _build_diff_outer_edge_mask(self, gray, rx1, ry1):
        if gray is None or gray.size == 0:
            return np.zeros((0, 0), dtype=np.uint8)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, dark_mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        dark_mask = self._mask_below_baseline_in_roi(dark_mask, rx1, ry1, self.baseline_params, margin_px=3.0)

        # Remove isolated substrate speckles while preserving the thin outer rim.
        dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)
        dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
        return dark_mask

    def _ordered_upper_edge_from_contour(self, points):
        if points is None or len(points) == 0:
            return np.empty((0, 2), dtype=np.float32)
        pts = np.asarray(points, dtype=np.float32)
        row_map = {}
        for p in pts:
            x = int(round(float(p[0])))
            y = float(p[1])
            if x not in row_map or y < row_map[x]:
                row_map[x] = y
        if not row_map:
            return np.empty((0, 2), dtype=np.float32)
        xs = sorted(row_map.keys())
        ys = np.array([row_map[x] for x in xs], dtype=np.float32)
        if len(ys) >= 7:
            ys = cv2.GaussianBlur(ys.reshape(-1, 1), (1, 7), 0).ravel()
        out = np.array([[float(x), float(y)] for x, y in zip(xs, ys)], dtype=np.float32)
        return out

    def _filter_points_above_baseline(self, points, baseline_params, tol_px=2.0):
        if points is None or len(points) == 0 or baseline_params is None:
            return points
        m, c0 = baseline_params
        if abs(m) > 1e8:
            return points
        vals = m * points[:, 0] - points[:, 1] + c0
        keep = vals >= -tol_px
        filtered = points[keep]
        if len(filtered) >= 5:
            return filtered
        return points

    def _trim_points_near_baseline(self, points, baseline_params, trim_ratio=0.10, min_keep=12):
        if points is None or len(points) == 0 or baseline_params is None:
            return points
        m, c0 = baseline_params
        if abs(m) > 1e8:
            return points
        pts = np.asarray(points, dtype=np.float32)
        # Vertical height above baseline: y_baseline(x) - y = (m*x + c0) - y
        # Positive value means the point is above (inside) the baseline (image y increases downward)
        vert_heights = (m * pts[:, 0] + c0) - pts[:, 1]
        positive = vert_heights[vert_heights > 0]
        if len(positive) == 0:
            return points
        drop_height = float(np.max(positive))
        cutoff = drop_height * float(trim_ratio)
        # Keep points where vertical height above baseline >= cutoff
        # Equivalent to shifting the slanted baseline upward by (trim_ratio * drop_height)
        # keeping same slope: y_new(x) = m*x + c0 - cutoff
        keep = vert_heights >= cutoff
        trimmed = pts[keep]
        if len(trimmed) >= int(min_keep):
            return trimmed
        return points

    def _top_edge_points_from_mask(self, mask):
        if mask is None or mask.size == 0:
            return np.empty((0, 2), dtype=np.float32)
        xs = np.where(np.any(mask == 255, axis=0))[0]
        pts = []
        for x in xs:
            ys = np.where(mask[:, x] == 255)[0]
            if len(ys) > 0:
                pts.append([float(x), float(ys[0])])
        if not pts:
            return np.empty((0, 2), dtype=np.float32)
        pts = np.array(pts, dtype=np.float32)
        order = np.argsort(pts[:, 0])
        return pts[order]

    def _clean_upper_edge_points(self, points, smooth_ksize=9, max_dev=4.0, keep_edge_ratio=0.15):
        if points is None or len(points) == 0:
            return np.empty((0, 2), dtype=np.float32)
        pts = np.asarray(points, dtype=np.float32)
        order = np.argsort(pts[:, 0])
        pts = pts[order]

        ys = pts[:, 1].copy()
        k = int(smooth_ksize)
        if k < 3:
            k = 3
        if k % 2 == 0:
            k += 1

        if len(ys) >= k:
            ys_smooth = cv2.GaussianBlur(ys.reshape(-1, 1), (1, k), 0).ravel()
            keep = np.abs(ys - ys_smooth) <= float(max_dev)

            # Preserve side-edge regions (near B1/B2) to avoid over-filtering steep slopes.
            n = len(ys)
            edge_n = max(3, int(n * float(keep_edge_ratio)))
            keep[:edge_n] = True
            keep[n-edge_n:] = True

            pts = pts[keep]

        if len(pts) == 0:
            return np.empty((0, 2), dtype=np.float32)

        # Deduplicate by integer x and keep only top-most y
        x_map = {}
        for p in pts:
            x = int(round(float(p[0])))
            y = float(p[1])
            if x not in x_map or y < x_map[x]:
                x_map[x] = y

        xs = sorted(x_map.keys())
        return np.array([[float(x), float(x_map[x])] for x in xs], dtype=np.float32)

    def _bridge_edge_gaps(self, points, max_gap=12):
        if points is None or len(points) < 2:
            return np.asarray(points, dtype=np.float32) if points is not None else np.empty((0, 2), dtype=np.float32)
        pts = np.asarray(points, dtype=np.float32)
        order = np.argsort(pts[:, 0])
        pts = pts[order]
        out = [pts[0]]
        for idx in range(1, len(pts)):
            prev = pts[idx - 1]
            cur = pts[idx]
            gap = int(round(cur[0] - prev[0]))
            if 1 < gap <= int(max_gap):
                for step in range(1, gap):
                    t = step / float(gap)
                    out.append(np.array([
                        prev[0] + step,
                        prev[1] + t * (cur[1] - prev[1])
                    ], dtype=np.float32))
            out.append(cur)
        return np.array(out, dtype=np.float32)

    def _contour_from_upper_edge_and_baseline(self, upper_pts_global, anchor_pts):
        if upper_pts_global is None or len(upper_pts_global) < 2:
            return None
        upper = np.asarray(upper_pts_global, dtype=np.float32)
        poly = upper.tolist()
        if anchor_pts is not None and len(anchor_pts) == 2:
            anchors = np.asarray(anchor_pts, dtype=np.float32)
            anchors = anchors[np.argsort(anchors[:, 0])]
            poly.append([float(anchors[-1][0]), float(anchors[-1][1])])
            poly.append([float(anchors[0][0]), float(anchors[0][1])])
        else:
            base_y = float(np.max(upper[:, 1]))
            poly.append([float(upper[-1][0]), base_y])
            poly.append([float(upper[0][0]), base_y])
        return np.array(poly, dtype=np.int32).reshape(-1, 1, 2)

    def draw_edge_scatter(self, points, sc, ox, oy):
        self.cv_res.delete("edge_curve")
        if points is None or len(points) == 0:
            return
        step = max(1, len(points) // 1200)
        for p in points[::step]:
            cx = p[0] * sc + ox
            cy = p[1] * sc + oy
            self.cv_res.create_oval(cx-2.2, cy-2.2, cx+2.2, cy+2.2, fill="#00C853", outline="", tags="edge_curve")

    def _robust_polyfit_irls(self, x, y, degree, base_x=None, base_y=None, anchor_weight=10.0, iters=6):
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        if len(x) < degree + 1:
            raise ValueError("Not enough points for polynomial fit")

        x_all = x.copy(); y_all = y.copy(); w_all = np.ones_like(x, dtype=np.float64)
        if base_x is not None and base_y is not None and len(base_x) > 0:
            bx = np.asarray(base_x, dtype=np.float64)
            by = np.asarray(base_y, dtype=np.float64)
            x_all = np.concatenate([x_all, bx])
            y_all = np.concatenate([y_all, by])
            w_all = np.concatenate([w_all, np.full(len(bx), float(anchor_weight), dtype=np.float64)])

        coeffs = np.polyfit(x_all, y_all, degree, w=w_all)
        for _ in range(max(1, int(iters))):
            y_hat = np.polyval(coeffs, x)
            resid = y - y_hat
            mad = np.median(np.abs(resid - np.median(resid)))
            scale = max(1e-6, 1.4826 * mad)
            u = resid / (4.685 * scale)
            robust_w = np.where(np.abs(u) < 1.0, (1.0 - u*u)**2, 0.06)
            robust_w = np.clip(robust_w, 0.06, 1.0)

            x_all = x.copy(); y_all = y.copy(); w_all = robust_w.astype(np.float64)
            if base_x is not None and base_y is not None and len(base_x) > 0:
                bx = np.asarray(base_x, dtype=np.float64)
                by = np.asarray(base_y, dtype=np.float64)
                x_all = np.concatenate([x_all, bx])
                y_all = np.concatenate([y_all, by])
                w_all = np.concatenate([w_all, np.full(len(bx), float(anchor_weight), dtype=np.float64)])
            coeffs = np.polyfit(x_all, y_all, degree, w=w_all)
        return coeffs

    def _poly_real_roots_for_baseline(self, coeffs, y_base, imag_tol=1e-6):
        c = np.array(coeffs, dtype=np.float64).copy()
        c[-1] -= float(y_base)
        roots = np.roots(c)
        return sorted([float(r.real) for r in roots if abs(r.imag) <= imag_tol])

    def _get_baseline_anchor_points_image(self):
        if len(self.baseline_points) != 2:
            return np.empty((0, 2), dtype=np.float32)
        sc, ox, oy = self.img_scale_right, self.offset_x, self.offset_y
        if sc <= 0:
            return np.empty((0, 2), dtype=np.float32)
        anchors = []
        for p in self.baseline_points:
            ix = (p.x - ox) / sc
            iy = (p.y - oy) / sc
            anchors.append([float(ix), float(iy)])
        return np.array(anchors, dtype=np.float32)

    def calc_drop_fit(self):
        if not self.ca_roi or self.rotated_img is None: messagebox.showerror("Err","Select drop first"); return
        self.cv_res.delete("fit_curve"); self.cv_res.delete("edge_curve"); self.cv_res.delete("ui_roi")
        self.fit_params = None
        self.drawn_fit_points = None
        self.edge_pts_global = None
        
        sc,ox,oy = self.img_scale_right, self.offset_x, self.offset_y
        x1,y1,x2,y2 = self.ca_roi
        rx1=int((x1-ox)/sc); ry1=int((y1-oy)/sc); rx2=int((x2-ox)/sc); ry2=int((y2-oy)/sc)
        
        h,w = self.rotated_img.shape[:2]
        rx1=max(0,rx1); ry1=max(0,ry1); rx2=min(w,rx2); ry2=min(h,ry2)
        if rx2-rx1<5: return
        
        roi = self.rotated_img[ry1:ry2, rx1:rx2]
        gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
        if self.use_differential:
            component_mask = self._build_diff_outer_edge_mask(gray, rx1, ry1)
            upper_pts_roi = self._top_edge_points_from_mask(component_mask)
            upper_pts_roi = self._bridge_edge_gaps(upper_pts_roi, max_gap=14)
            upper_pts_roi = self._clean_upper_edge_points(upper_pts_roi, smooth_ksize=7, max_dev=6.0, keep_edge_ratio=0.2)
            contour_pts_global = upper_pts_roi.copy()
            if len(contour_pts_global) == 0:
                messagebox.showerror("Err", "Cannot detect thin outer edge from selected ROI")
                return
            contour_pts_global[:, 0] += rx1
            contour_pts_global[:, 1] += ry1
            upper_pts_global = contour_pts_global.copy()
            self.drop_contour = self._contour_from_upper_edge_and_baseline(upper_pts_global, self._get_baseline_anchor_points_image())
        else:
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)

            cnt, component_mask, surface_y = self._extract_drop_contour_from_roi_thresh(thresh)
            if cnt is None:
                messagebox.showerror("Err", "Cannot detect drop edge from selected ROI")
                return

            # Full contour in global coords (for centroid / downstream geometry)
            cnt_global = cnt.copy().astype(np.float32)
            for p in cnt_global:
                p[0][0] += rx1
                p[0][1] += ry1
            self.drop_contour = cnt_global.astype(np.int32)

            contour_pts_roi = cnt[:, 0, :].astype(np.float32)
            contour_pts_global = contour_pts_roi.copy()
            contour_pts_global[:, 0] += rx1
            contour_pts_global[:, 1] += ry1

            # Build upper-edge points from filled connected mask (robust against inner-hole contour noise)
            upper_pts_roi = self._top_edge_points_from_mask(component_mask)
            upper_pts_roi = self._clean_upper_edge_points(upper_pts_roi, smooth_ksize=9, max_dev=4.0)
            upper_pts_global = upper_pts_roi.copy()
            if len(upper_pts_global) > 0:
                upper_pts_global[:, 0] += rx1
                upper_pts_global[:, 1] += ry1

            # Hard reject any points below detected surface line in ROI
            if surface_y is not None:
                surf_global_y = ry1 + surface_y
                contour_pts_global = contour_pts_global[contour_pts_global[:, 1] <= (surf_global_y + 1.0)]
                if len(upper_pts_global) > 0:
                    upper_pts_global = upper_pts_global[upper_pts_global[:, 1] <= (surf_global_y + 1.0)]

        # Reject points below baseline (primary fix for substrate contamination)
        if self.baseline_params is not None:
            contour_pts_global = self._filter_points_above_baseline(contour_pts_global, self.baseline_params, tol_px=4.0)
            if len(upper_pts_global) > 0:
                upper_pts_global = self._filter_points_above_baseline(upper_pts_global, self.baseline_params, tol_px=4.0)
            contour_pts_global = self._trim_points_near_baseline(contour_pts_global, self.baseline_params, trim_ratio=0.10, min_keep=20)
            if len(upper_pts_global) > 0:
                upper_pts_global = self._trim_points_near_baseline(upper_pts_global, self.baseline_params, trim_ratio=0.10, min_keep=12)

        upper_pts_global = self._clean_upper_edge_points(upper_pts_global, smooth_ksize=7, max_dev=5.0, keep_edge_ratio=0.18)
        anchor_pts = self._get_baseline_anchor_points_image()
        if self.use_differential:
            self.drop_contour = self._contour_from_upper_edge_and_baseline(upper_pts_global, anchor_pts)

        use_pts = upper_pts_global if len(upper_pts_global) > 0 else contour_pts_global
        self.edge_pts_global = use_pts.copy() if len(use_pts) > 0 else None
        if self.edge_pts_global is not None and len(self.edge_pts_global) > 0:
            self.draw_edge_scatter(self.edge_pts_global, sc, ox, oy)
        else:
            messagebox.showerror("Err", "Cannot detect drop edge from selected ROI")

    def fit_edge(self):
        if self.edge_pts_global is None or len(self.edge_pts_global) == 0:
            messagebox.showerror("Err", "Run Cal Drop Edge first"); return
        self.cv_res.delete("fit_curve")
        self.fit_params = None
        self.drawn_fit_points = None
        sc, ox, oy = self.img_scale_right, self.offset_x, self.offset_y
        upper_pts_global = self.edge_pts_global
        anchor_pts = self._get_baseline_anchor_points_image()
        method = self.fit_method.get()
        if method == "Ellipse" and len(upper_pts_global) >= 8:
            try:
                fit_pts_ellipse = upper_pts_global
                if len(anchor_pts) == 2:
                    fit_pts_ellipse = np.vstack([upper_pts_global, anchor_pts, anchor_pts])
                box = cv2.fitEllipse(fit_pts_ellipse.reshape(-1, 1, 2))
                self.fit_params = ("Ellipse", box)
                elp = cv2.ellipse2Poly((int(box[0][0]),int(box[0][1])), (int(box[1][0]/2),int(box[1][1]/2)), int(box[2]), 0, 360, 2)
                self.draw_fit_curve(elp, sc, ox, oy)
                return
            except Exception:
                method = "Robust"

        if self.baseline_params is None:
            messagebox.showerror("Err","Apply Baseline first"); return
        pts = upper_pts_global
        m, c_val = self.baseline_params; ang = math.atan(m)
        cos_a = math.cos(-ang); sin_a = math.sin(-ang)
        rot_pts = []
        for p in pts:
            rot_pts.append([p[0]*cos_a - p[1]*sin_a, p[0]*sin_a + p[1]*cos_a])
        rot_pts = np.array(rot_pts, dtype=np.float64)
        if len(rot_pts) < 5:
            messagebox.showerror("Err", "Not enough edge points to fit"); return

        order = np.argsort(rot_pts[:,0])
        rot_pts = rot_pts[order]
        x_fit = rot_pts[:,0]
        y_fit = rot_pts[:,1]
        y_base_rot = float(np.median(y_fit))
        base_x = np.array([], dtype=np.float64)
        base_y = np.array([], dtype=np.float64)
        if len(anchor_pts) == 2:
            rot_anchor = []
            for p in anchor_pts:
                rot_anchor.append([p[0]*cos_a - p[1]*sin_a, p[0]*sin_a + p[1]*cos_a])
            rot_anchor = np.array(rot_anchor, dtype=np.float64)
            y_base_rot = float(np.mean(rot_anchor[:,1]))
            base_x = rot_anchor[:,0]
            base_y = rot_anchor[:,1]

        try:
            degree = 2 if method == "Parabola" else 3
            coeffs = self._robust_polyfit_irls(x_fit, y_fit, degree=degree, base_x=base_x, base_y=base_y, anchor_weight=10.0, iters=6)
            roots = self._poly_real_roots_for_baseline(coeffs, y_base_rot)
            # Auto-upgrade Parabola to robust cubic when the edge is skew/flat and quadratic cannot cross baseline twice.
            if method == "Parabola" and len(roots) < 2 and len(x_fit) >= 8:
                coeffs = self._robust_polyfit_irls(x_fit, y_fit, degree=3, base_x=base_x, base_y=base_y, anchor_weight=10.0, iters=7)
                roots = self._poly_real_roots_for_baseline(coeffs, y_base_rot)
                method = "Robust"

            x_min = float(np.min(x_fit))
            x_max = float(np.max(x_fit))
            if len(roots) >= 2:
                span = max(1.0, abs(roots[-1] - roots[0]))
                ext = max(2.0, 0.06 * span)
                x_min = roots[0] - ext
                x_max = roots[-1] + ext
            elif len(roots) == 1:
                ext = max(6.0, 0.25 * max(1.0, abs(x_max - x_min)))
                x_min = min(x_min, roots[0] - ext)
                x_max = max(x_max, roots[0] + ext)

            x_range = np.linspace(x_min, x_max, 220)
            y_fit_arr = np.polyval(coeffs, x_range)
            inv_cos = math.cos(ang); inv_sin = math.sin(ang)
            fit_curve_pts = []
            for i in range(len(x_range)):
                fit_curve_pts.append([x_range[i]*inv_cos - y_fit_arr[i]*inv_sin, x_range[i]*inv_sin + y_fit_arr[i]*inv_cos])

            self.fit_params = (("Parabola" if degree == 2 else "Robust"), coeffs, ang)
            self.draw_fit_curve(np.array(fit_curve_pts, dtype=np.float32), sc, ox, oy)
        except Exception as e:
            messagebox.showerror("Err", f"Fit failed: {e}")

    def toggle_erase_mode(self):
        if self.pen_mode:
            self.pen_mode = False
            if self.btn_pen:
                self.btn_pen.config(bg="#00C853", fg="white")
        self.erase_mode = not self.erase_mode
        if self.erase_mode:
            self.btn_erase.config(bg="#FF5722", fg="white")
            self.cv_res.config(cursor="dotbox")
        else:
            self.btn_erase.config(bg=THEME["bg_tool"], fg="black")
            self.cv_res.config(cursor="")

    def toggle_pen_mode(self):
        if self.erase_mode:
            self.erase_mode = False
            self.btn_erase.config(bg=THEME["bg_tool"], fg="black")
        self.pen_mode = not self.pen_mode
        if self.pen_mode:
            self.btn_pen.config(bg="#00A844", fg="white")
            self.cv_res.config(cursor="pencil")
        else:
            self.btn_pen.config(bg="#00C853", fg="white")
            self.cv_res.config(cursor="")

    def _do_add_point_at(self, cx, cy):
        if self.rotated_img is None:
            return
        sc, ox, oy = self.img_scale_right, self.offset_x, self.offset_y
        if sc <= 0:
            return
        ix = (cx - ox) / sc
        iy = (cy - oy) / sc
        h, w = self.rotated_img.shape[:2]
        if ix < 0 or iy < 0 or ix >= w or iy >= h:
            return

        new_pt = np.array([[float(ix), float(iy)]], dtype=np.float32)
        if self.edge_pts_global is None or len(self.edge_pts_global) == 0:
            self.edge_pts_global = new_pt
        else:
            pts = np.asarray(self.edge_pts_global, dtype=np.float32)
            d2 = np.sum((pts - new_pt[0]) ** 2, axis=1)
            if np.min(d2) < 4.0:
                return
            self.edge_pts_global = np.vstack([pts, new_pt])

        self.fit_params = None
        self.drawn_fit_points = None
        self.cv_res.delete("fit_curve")
        self.cv_res.delete("tangent")
        self.cv_res.delete("ov_ca")
        self.draw_edge_scatter(self.edge_pts_global, sc, ox, oy)

    def _do_erase_at(self, cx, cy):
        if self.edge_pts_global is None or len(self.edge_pts_global) == 0:
            return
        sc, ox, oy = self.img_scale_right, self.offset_x, self.offset_y
        if sc <= 0: return
        ix = (cx - ox) / sc
        iy = (cy - oy) / sc
        erase_r = 15.0 / sc
        pts = self.edge_pts_global
        dx = pts[:, 0] - ix; dy = pts[:, 1] - iy
        keep = (dx*dx + dy*dy) > (erase_r * erase_r)
        self.edge_pts_global = pts[keep]
        self.draw_edge_scatter(self.edge_pts_global, sc, ox, oy)

    def draw_fit_curve(self, points, sc, ox, oy):
        draw_pts = []
        for p in points: draw_pts.extend([p[0]*sc+ox, p[1]*sc+oy])
        self.cv_res.create_line(draw_pts, fill=THEME["line_fit"], width=2, tags="fit_curve")
        self.drawn_fit_points = points # Save for intersection

    def _ellipse_intersections_with_baseline(self, box, baseline_params):
        (h, k), (axis_major, axis_minor), angle_deg = box
        a = axis_major / 2.0
        b = axis_minor / 2.0
        if a <= 1e-9 or b <= 1e-9:
            return []

        phi = math.radians(angle_deg)
        cp = math.cos(phi)
        sp = math.sin(phi)
        m, c0 = baseline_params
        pts = []

        if abs(m) > 1e8:
            x0 = c0
            pu = sp
            qu = cp * (x0 - h) - sp * k
            pv = cp
            qv = -sp * (x0 - h) - cp * k
            A = (pu * pu) / (a * a) + (pv * pv) / (b * b)
            B = 2.0 * ((pu * qu) / (a * a) + (pv * qv) / (b * b))
            C = (qu * qu) / (a * a) + (qv * qv) / (b * b) - 1.0
            D = B * B - 4.0 * A * C
            if D < 0:
                return []
            D = max(0.0, D)
            sqrt_D = math.sqrt(D)
            y_roots = [(-B - sqrt_D) / (2.0 * A), (-B + sqrt_D) / (2.0 * A)]
            for yy in y_roots:
                pts.append((x0, yy))
            return pts

        p = cp + sp * m
        q = sp * (c0 - k) - cp * h
        r = -sp + cp * m
        s = cp * (c0 - k) + sp * h
        A = (p * p) / (a * a) + (r * r) / (b * b)
        B = 2.0 * ((p * q) / (a * a) + (r * s) / (b * b))
        C = (q * q) / (a * a) + (s * s) / (b * b) - 1.0
        D = B * B - 4.0 * A * C
        if D < 0:
            return []
        D = max(0.0, D)
        sqrt_D = math.sqrt(D)
        x_roots = [(-B - sqrt_D) / (2.0 * A), (-B + sqrt_D) / (2.0 * A)]
        for xx in x_roots:
            yy = m * xx + c0
            pts.append((xx, yy))
        return pts

    def _polyline_intersections_with_baseline(self, poly, m, c0, tol=1.0):
        pts = np.asarray(poly, dtype=np.float64)
        if len(pts) < 2:
            return []

        vals = m * pts[:, 0] - pts[:, 1] + c0
        candidates = []

        # Accept points already on/very near baseline.
        for i in range(len(pts)):
            if abs(vals[i]) <= tol:
                candidates.append((float(pts[i, 0]), float(pts[i, 1])))

        # Segment-wise crossing (also covers one endpoint very close to baseline).
        for i in range(len(pts) - 1):
            p1 = pts[i]; p2 = pts[i + 1]
            v1 = vals[i]; v2 = vals[i + 1]

            if (v1 < -tol and v2 > tol) or (v1 > tol and v2 < -tol) or (abs(v1) <= tol < abs(v2)) or (abs(v2) <= tol < abs(v1)):
                denom = (v1 - v2)
                if abs(denom) < 1e-12:
                    continue
                t = v1 / denom
                if 0.0 <= t <= 1.0:
                    ix = p1[0] + t * (p2[0] - p1[0])
                    iy = p1[1] + t * (p2[1] - p1[1])
                    candidates.append((float(ix), float(iy)))

        # Deduplicate close points.
        uniq = []
        for p in sorted(candidates, key=lambda q: q[0]):
            if not uniq:
                uniq.append(p)
                continue
            if math.hypot(p[0] - uniq[-1][0], p[1] - uniq[-1][1]) > 1.2:
                uniq.append(p)
        return uniq

    def _poly_model_intersections_with_baseline(self, fit_params, poly_points=None):
        if fit_params is None or len(fit_params) < 3:
            return []
        fit_kind = fit_params[0]
        if fit_kind not in ("Parabola", "Robust"):
            return []

        coeffs = np.asarray(fit_params[1], dtype=np.float64)
        ang = float(fit_params[2])
        anchor_pts = self._get_baseline_anchor_points_image()
        if len(anchor_pts) == 2:
            cos_a = math.cos(-ang); sin_a = math.sin(-ang)
            rot_anchor = []
            for p in anchor_pts:
                rot_anchor.append([p[0]*cos_a - p[1]*sin_a, p[0]*sin_a + p[1]*cos_a])
            rot_anchor = np.array(rot_anchor, dtype=np.float64)
            y_base_rot = float(np.mean(rot_anchor[:, 1]))
        else:
            y_base_rot = 0.0

        roots = self._poly_real_roots_for_baseline(coeffs, y_base_rot)
        if len(roots) == 0:
            return []

        inv_cos = math.cos(ang); inv_sin = math.sin(ang)
        pts = []
        for xr in roots:
            yr = float(np.polyval(coeffs, xr))
            xg = xr * inv_cos - yr * inv_sin
            yg = xr * inv_sin + yr * inv_cos
            pts.append((float(xg), float(yg)))

        # Keep roots near drawn fit span to avoid remote polynomial branches.
        if poly_points is not None and len(poly_points) >= 2:
            poly = np.asarray(poly_points, dtype=np.float64)
            x_min = float(np.min(poly[:, 0])); x_max = float(np.max(poly[:, 0]))
            span = max(1.0, x_max - x_min)
            lo = x_min - 0.5 * span
            hi = x_max + 0.5 * span
            pts = [p for p in pts if lo <= p[0] <= hi]
        return pts

    def _select_i1_i2(self, intersections, poly_points=None):
        if intersections is None or len(intersections) < 2:
            return None, None
        pts = sorted([(float(p[0]), float(p[1])) for p in intersections], key=lambda p: p[0])
        dedup = []
        for p in pts:
            if not dedup or math.hypot(p[0] - dedup[-1][0], p[1] - dedup[-1][1]) > 1.2:
                dedup.append(p)
        pts = dedup
        if len(pts) < 2:
            return None, None

        anchor_pts = self._get_baseline_anchor_points_image()
        if len(anchor_pts) == 2:
            anchors = sorted(anchor_pts.tolist(), key=lambda p: p[0])
            left_anchor_x = float(anchors[0][0])
            right_anchor_x = float(anchors[1][0])
            split_x = 0.5 * (left_anchor_x + right_anchor_x)
        elif poly_points is not None and len(poly_points) > 0:
            poly = np.asarray(poly_points, dtype=np.float64)
            split_x = float(np.median(poly[:, 0]))
            left_anchor_x = float(np.min(poly[:, 0]))
            right_anchor_x = float(np.max(poly[:, 0]))
        else:
            split_x = 0.5 * (pts[0][0] + pts[-1][0])
            left_anchor_x = pts[0][0]
            right_anchor_x = pts[-1][0]

        left_candidates = [p for p in pts if p[0] <= split_x]
        right_candidates = [p for p in pts if p[0] >= split_x]

        if len(left_candidates) == 0:
            left_candidates = pts
        if len(right_candidates) == 0:
            right_candidates = pts

        i1 = min(left_candidates, key=lambda p: abs(p[0] - left_anchor_x))
        i2 = min(right_candidates, key=lambda p: abs(p[0] - right_anchor_x))

        if i1[0] > i2[0]:
            i1, i2 = i2, i1
        if math.hypot(i1[0] - i2[0], i1[1] - i2[1]) < 1e-6:
            i1 = pts[0]
            i2 = pts[-1]
        return i1, i2

    def _ellipse_tangent_vector(self, box, x, y):
        (h, k), (axis_major, axis_minor), angle_deg = box
        a = axis_major / 2.0
        b = axis_minor / 2.0
        phi = math.radians(angle_deg)
        cp = math.cos(phi)
        sp = math.sin(phi)

        xp = cp * (x - h) + sp * (y - k)
        yp = -sp * (x - h) + cp * (y - k)

        fx = 2.0 * (xp / (a * a)) * cp + 2.0 * (yp / (b * b)) * (-sp)
        fy = 2.0 * (xp / (a * a)) * sp + 2.0 * (yp / (b * b)) * cp

        tx = -fy
        ty = fx
        norm = math.hypot(tx, ty)
        if norm < 1e-12:
            return (1.0, 0.0)
        return (tx / norm, ty / norm)

    def _line_direction_from_slope(self, m):
        if abs(m) > 1e8:
            return (0.0, 1.0)
        n = math.hypot(1.0, m)
        return (1.0 / n, m / n)

    def _normalize_vec(self, vx, vy):
        norm = math.hypot(vx, vy)
        if norm < 1e-12:
            return (1.0, 0.0)
        return (vx / norm, vy / norm)

    def _angle_between_vectors_0_180(self, v1, v2):
        v1n = self._normalize_vec(v1[0], v1[1])
        v2n = self._normalize_vec(v2[0], v2[1])
        dot = v1n[0] * v2n[0] + v1n[1] * v2n[1]
        dot = max(-1.0, min(1.0, dot))
        return math.degrees(math.acos(dot))

    def _acute_angle_between_vectors(self, v1, v2):
        dot = abs(v1[0] * v2[0] + v1[1] * v2[1])
        dot = max(-1.0, min(1.0, dot))
        return math.degrees(math.acos(dot))

    def calc_contact_angle_final(self):
        if self.baseline_params is None:
            messagebox.showerror("Err", "Fit drop and Apply baseline first"); return
        if (not hasattr(self, 'drawn_fit_points')) or (self.drawn_fit_points is None) or (len(self.drawn_fit_points) < 2):
            messagebox.showerror("Err", "Fit drop edge first (Cal Drop Edge)"); return
        
        self.cv_res.delete("ov_ca"); self.cv_res.delete("tangent")
        self.last_mode_calc = "CA"
        sc,ox,oy = self.img_scale_right, self.offset_x, self.offset_y
        m, c = self.baseline_params
        
        fit_kind = self.fit_params[0] if self.fit_params else None
        poly = np.asarray(self.drawn_fit_points, dtype=np.float64)
        intersections = []

        if fit_kind == "Ellipse":
            box = self.fit_params[1]
            intersections = self._ellipse_intersections_with_baseline(box, self.baseline_params)
        else:
            intersections.extend(self._poly_model_intersections_with_baseline(self.fit_params, poly_points=poly))

        if len(intersections) < 2:
            intersections.extend(self._polyline_intersections_with_baseline(poly, m, c, tol=1.0))

        if len(intersections) < 2:
            # Force one candidate from each side (left/right) when one side is nearly tangent.
            center_x = float(np.median(poly[:, 0]))
            left = poly[poly[:, 0] <= center_x]
            right = poly[poly[:, 0] > center_x]
            side_candidates = []
            if len(left) > 0:
                dleft = np.abs(m * left[:, 0] - left[:, 1] + c)
                p_left = left[int(np.argmin(dleft))]
                side_candidates.append((float(p_left[0]), float(p_left[1])))
            if len(right) > 0:
                dright = np.abs(m * right[:, 0] - right[:, 1] + c)
                p_right = right[int(np.argmin(dright))]
                side_candidates.append((float(p_right[0]), float(p_right[1])))

            merged = list(intersections) + side_candidates
            merged = sorted(merged, key=lambda p: p[0])
            dedup = []
            for p in merged:
                if not dedup or math.hypot(p[0] - dedup[-1][0], p[1] - dedup[-1][1]) > 1.2:
                    dedup.append(p)
            intersections = dedup

        if len(intersections) < 2:
            dists = [abs(m*p[0] - p[1] + c) for p in poly]
            sorted_idx = np.argsort(dists)
            candidates = poly[sorted_idx[:10]]
            candidates = sorted(candidates, key=lambda p: p[0])
            if len(candidates) >= 2:
                intersections = [candidates[0], candidates[-1]]
            else:
                messagebox.showerror("Err","Cannot find intersection"); return

        # Select I1(left) and I2(right) robustly, prioritizing baseline anchor sides.
        I1, I2 = self._select_i1_i2(intersections, poly_points=poly)
        if I1 is None or I2 is None:
            messagebox.showerror("Err","Cannot find intersection"); return

        if self.drop_contour is not None and len(self.drop_contour) > 0:
            mm = cv2.moments(self.drop_contour)
            if abs(mm["m00"]) > 1e-12:
                drop_center = (mm["m10"] / mm["m00"], mm["m01"] / mm["m00"])
            else:
                drop_center = ((I1[0] + I2[0]) / 2.0, (I1[1] + I2[1]) / 2.0 - 1.0)
        else:
            drop_center = ((I1[0] + I2[0]) / 2.0, (I1[1] + I2[1]) / 2.0 - 1.0)

        # Baseline vectors requested by user:
        # left angle  : I2 - I1 - tangent(left)
        # right angle : I1 - I2 - tangent(right)
        baseline_vec_left = (I2[0] - I1[0], I2[1] - I1[1])
        baseline_vec_right = (I1[0] - I2[0], I1[1] - I2[1])

        angles = []
        for i, pt in enumerate([I1, I2]):
            px, py = pt
            tx, ty = px*sc+ox, py*sc+oy
            
            # Label I1, I2 (Below Blue Line): I1 left, I2 right
            if i == 0:  # I1 (left)
                create_inverted_canvas_text(self.cv_res, tx+20, ty+25, text=f"I{i+1}", fill="yellow", outline="black", font=("Arial",12,"bold"), tags="ov_ca")
            else:  # I2 (right)
                create_inverted_canvas_text(self.cv_res, tx-20, ty+25, text=f"I{i+1}", fill="yellow", outline="black", font=("Arial",12,"bold"), tags="ov_ca")
            self.cv_res.create_oval(tx-4,ty-4,tx+4,ty+4, fill="yellow", outline="black", tags="ov_ca")
            
            if fit_kind == "Ellipse":
                tvec = self._ellipse_tangent_vector(self.fit_params[1], px, py)
                vx, vy = tvec
            else:
                dists = np.sum((poly - [px,py])**2, axis=1)
                idx = np.argmin(dists)
                p_prev = poly[max(0, idx-2)]; p_next = poly[min(len(poly)-1, idx+2)]
                vx = p_next[0] - p_prev[0]; vy = p_next[1] - p_prev[1]
            vx, vy = self._normalize_vec(vx, vy)

            # Choose tangent direction that points into liquid (towards drop center)
            to_center = (drop_center[0] - px, drop_center[1] - py)
            if vx * to_center[0] + vy * to_center[1] < 0:
                vx, vy = -vx, -vy

            base_vec = baseline_vec_left if i == 0 else baseline_vec_right
            deg = self._angle_between_vectors_0_180(base_vec, (vx, vy))
            angles.append(deg)
            
            # Visual Tangent (Thick Purple)
            l=120
            dx = vx*l; dy = vy*l
            self.cv_res.create_line(tx, ty, tx+dx, ty+dy, fill=THEME["line_tan"], width=3, arrow=tk.LAST, arrowshape=(16,20,8), tags="tangent")

        L, R = angles
        Avg = (L+R)/2
        self.export_data_ca = {"L":f"{L:.2f}", "R":f"{R:.2f}", "Avg":f"{Avg:.2f}"}
        
        w_can = self.cv_res.winfo_width(); start_y=20; gap=25
        self.cv_res.create_text(w_can-10, start_y, text=f"CA(L): {L:.1f}°", anchor="e", fill="blue", font=("Arial",14,"bold"), tags="ov_ca")
        self.cv_res.create_text(w_can-10, start_y+gap, text=f"CA(R): {R:.1f}°", anchor="e", fill="blue", font=("Arial",14,"bold"), tags="ov_ca")
        self.cv_res.create_text(w_can-10, start_y+2*gap, text=f"CA(av): {Avg:.1f}°", anchor="e", fill=THEME["line_tan"], font=("Arial",14,"bold"), tags="ov_ca")

    # --- EXPORT ---
    def copy_results(self):
        txt = ""
        if self.last_mode_calc == "ST" and self.export_data_st:
            d = self.export_data_st
            txt = f"Scale (px/mm)\tDs (mm)\tDe (mm)\tSurface Tension (mN/m)\n{d['Scale']}\t{d['Ds']}\t{d['De']}\t{d['ST']}"
        elif self.last_mode_calc == "CA" and self.export_data_ca:
            d = self.export_data_ca
            txt = f"Contact angle (L)\tContact angle (R)\tContact angle (av)\n{d['L']}\t{d['R']}\t{d['Avg']}"
        
        if txt:
            self.root.clipboard_clear(); self.root.clipboard_append(txt)
            messagebox.showinfo("Success", "Copied to clipboard.")
        else: messagebox.showwarning("Warning", "No results.")

    def copy_image_clip(self):
        try:
            self.root.update()
            x = self.cv_res.winfo_rootx(); y = self.cv_res.winfo_rooty()
            w = self.cv_res.winfo_width(); h = self.cv_res.winfo_height()
            img = ImageGrab.grab(bbox=(x, y, x+w, y+h))
            output = io.BytesIO()
            img.convert("RGB").save(output, "BMP")
            data = output.getvalue()[14:]
            output.close()
            import win32clipboard
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
            win32clipboard.CloseClipboard()
            messagebox.showinfo("Success", "Image copied.")
        except Exception as e: messagebox.showerror("Error", f"Copy failed: {e}")

    def save_png(self):
        f = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG","*.png")])
        if f:
            self.root.update()
            x = self.cv_res.winfo_rootx(); y = self.cv_res.winfo_rooty()
            w = self.cv_res.winfo_width(); h = self.cv_res.winfo_height()
            ImageGrab.grab(bbox=(x, y, x+w, y+h)).save(f)

    def __del__(self):
        if self.temp_file and os.path.exists(self.temp_file):
            try: os.remove(self.temp_file)
            except: pass

if __name__ == "__main__":
    root = tk.Tk()
    app = CastaApp(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        try:
            root.destroy()
        except:
            pass