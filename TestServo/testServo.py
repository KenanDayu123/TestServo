#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox
import serial, serial.tools.list_ports
import threading, queue, math

BAUD = 115200
NUM_SERVOS = 7

# ---------- Scrollable Frame ----------
class ScrollFrame(ttk.Frame):
    def __init__(self, master, *a, **k):
        super().__init__(master, *a, **k)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0,0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._on_cfg)
        self.canvas.bind("<Configure>", self._on_canvas_cfg)
        self._bind_wheel(self.canvas)

    def _on_cfg(self, _=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_cfg(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)

    def _bind_wheel(self, w):
        w.bind_all("<MouseWheel>", self._on_wheel, add="+")   # Win/macOS
        w.bind_all("<Button-4>", self._on_wheel_linux, add="+")  # Linux
        w.bind_all("<Button-5>", self._on_wheel_linux, add="+")

    def _on_wheel(self, e):
        self.canvas.yview_scroll(int(-1*(e.delta/120)), "units")

    def _on_wheel_linux(self, e):
        self.canvas.yview_scroll(-1 if e.num==4 else 1, "units")


class ServoTester(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Servo Tester 7CH — Grid Layout")
        self.geometry("980x680")
        self.minsize(820, 520)

        # Serial
        self.ser = None
        self.reader_thread = None
        self.stop_reader = threading.Event()
        self.log_queue = queue.Queue()

        # UI state
        self.rows = []        # (slider, entry_angle, entry_pin)
        self.pin_vars = []    # pin textvars
        self.sel_vars = []    # BooleanVar per-servo (dipilih/tidak)
        self.gauges  = []     # dict gauge per-servo

        self._build_ui()
        self._refresh_ports()
        self.after(50, self._drain_log_queue)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- UI ----------
    def _build_ui(self):
        top = ttk.Frame(self, padding=10); top.pack(fill="x")
        ttk.Label(top, text="Port:").pack(side="left")
        self.port_cb = ttk.Combobox(top, width=32, state="readonly"); self.port_cb.pack(side="left", padx=6)
        ttk.Button(top, text="Refresh", command=self._refresh_ports).pack(side="left", padx=4)
        self.btn_connect = ttk.Button(top, text="Connect", command=self.toggle_connect)
        self.btn_connect.pack(side="left", padx=10)
        ttk.Button(top, text="HOME ALL", command=self.home_all).pack(side="left", padx=6)

        # Group controls
        group = ttk.Frame(self, padding=(10,6)); group.pack(fill="x")
        ttk.Label(group, text="Group Controls:").pack(side="left", padx=(0,8))
        ttk.Label(group, text="Angle").pack(side="left")
        self.group_angle_var = tk.StringVar(value="90")
        ttk.Entry(group, width=5, textvariable=self.group_angle_var).pack(side="left", padx=4)
        ttk.Button(group, text="Send Angle → Selected", command=self._group_send_angle).pack(side="left", padx=6)
        ttk.Button(group, text="Push UI → Selected", command=self._group_push_ui).pack(side="left", padx=6)
        ttk.Button(group, text="HOME Selected", command=self._group_home).pack(side="left", padx=6)
        ttk.Button(group, text="Select All", command=self._select_all).pack(side="left", padx=(16,4))
        ttk.Button(group, text="Clear", command=self._clear_selection).pack(side="left", padx=4)

        # Pins bar
        pinbar = ttk.Frame(self, padding=(10,0)); pinbar.pack(fill="x")
        ttk.Button(pinbar, text="Apply Pins", command=self.apply_pins).pack(side="left", padx=4, pady=8)
        ttk.Button(pinbar, text="Read Pins", command=self.read_pins).pack(side="left", padx=4, pady=8)

        sc = ScrollFrame(self); sc.pack(fill="both", expand=True, padx=10, pady=(0,10))
        grid = sc.content
        for c in range(2): grid.grid_columnconfigure(c, weight=1)

        for i in range(NUM_SERVOS):
            lf = ttk.LabelFrame(grid, text=f"Servo {i+1}", padding=10)
            lf.grid(row=i//2, column=i%2, padx=8, pady=8, sticky="nsew")

            header = ttk.Frame(lf); header.pack(fill="x")
            sv = tk.BooleanVar(value=False)
            self.sel_vars.append(sv)
            ttk.Checkbutton(header, text="Select", variable=sv).pack(side="left")

            # Gauge 180° (kiri=0, atas=90, kanan=180)
            gframe = ttk.Frame(lf); gframe.pack(fill="x", pady=(6,0))
            canv = tk.Canvas(gframe, width=220, height=170)
            canv.pack(side="left", padx=(0,8))
            gauge = self._init_gauge(canv)
            self.gauges.append(gauge)

            # Kontrol kanan
            right = ttk.Frame(gframe); right.pack(side="left", fill="x", expand=True)

            # Pin (default 22..28)
            prow = ttk.Frame(right); prow.pack(fill="x")
            ttk.Label(prow, text="Pin:").pack(side="left")
            pvar = tk.StringVar(value=str(22+i)); self.pin_vars.append(pvar)
            pentry = ttk.Entry(prow, textvariable=pvar, width=6); pentry.pack(side="left", padx=6)

            # Slider 0..180
            s = tk.Scale(right, from_=0, to=180, orient="horizontal", length=420, resolution=1)
            s.set(90); s.pack(anchor="w", pady=(6,0))

            # Angle entry + Send
            row2 = ttk.Frame(right); row2.pack(fill="x", pady=(6,0))
            ttk.Label(row2, text="Angle:").pack(side="left")
            e = ttk.Entry(row2, width=6); e.insert(0, "90"); e.pack(side="left", padx=4)

            def bind_slider(sl=s, en=e, idx=i):
                def on_slide(val):
                    en.delete(0, tk.END); en.insert(0, str(int(float(val))))
                    self._update_gauge(idx, int(float(val)))
                sl.config(command=on_slide)
            bind_slider()

            def send_angle(idx=i, sl=s, en=e):
                try:
                    ang = int(en.get())
                except ValueError:
                    messagebox.showerror("Error", "Angle harus angka 0..180"); return
                ang = max(0, min(180, ang))
                self._set_angle_local(idx, ang)
                self.send_cmd(f"S{idx+1}:{ang}")
            ttk.Button(row2, text="Send", command=send_angle).pack(side="left", padx=6)

            # =========================================================
            # MODIFIKASI: Quick Buttons dengan Grid (3 tombol/baris)
            # =========================================================
            row3 = ttk.Frame(right)
            row3.pack(fill="x", pady=6)

            # Saya tambahkan 45° dan 135° agar grid terlihat lebih penuh & rapi
            presets = (("0°", 0), ("45°", 45), ("90°", 90), ("135°", 135), ("180°", 180))
            
            MAX_COLS = 3 # Tentukan jumlah tombol per baris di sini

            for j, (label, val) in enumerate(presets):
                # Hitung posisi Grid otomatis
                r, c = divmod(j, MAX_COLS) 

                def mk(v=val, idx=i):
                    return lambda: (self._set_angle_local(idx, v), self.send_cmd(f"S{idx+1}:{v}"))
                
                # Gunakan .grid() dan sticky="ew" (expand width)
                btn = ttk.Button(row3, text=label, command=mk())
                btn.grid(row=r, column=c, sticky="ew", padx=2, pady=2)
            
            # Konfigurasi kolom agar lebarnya terbagi rata
            for col in range(MAX_COLS):
                row3.columnconfigure(col, weight=1)
            # =========================================================

            ttk.Button(right, text=f"HOME {i+1}",
                       command=lambda idx=i: self.home_one(idx+1)).pack(anchor="w", pady=(2,0))

            self.rows.append((s, e, pentry))

        # Log
        logf = ttk.Frame(self, padding=(10,0,10,10)); logf.pack(fill="both", expand=False)
        ttk.Label(logf, text="Log:").pack(anchor="w")
        self.log = tk.Text(logf, height=7); self.log.pack(fill="both", expand=True)

    # ---------- Gauge ----------
    def _init_gauge(self, c: tk.Canvas):
        w, h = 220, 170
        c.config(width=w, height=h)
        cx, cy = w//2, h-16
        r = 74
        c.create_arc(cx-r, cy-r, cx+r, cy+r, start=0, extent=180, style="arc", width=3)
        for ang, lab in zip([0, 90, 180], ["0", "90", "180"]):
            x1, y1 = self._polar_gauge(cx, cy, r-10, ang)
            x2, y2 = self._polar_gauge(cx, cy, r,    ang)
            c.create_line(x1, y1, x2, y2, width=2)
            tx, ty = self._polar_gauge(cx, cy, r+12, ang)
            c.create_text(tx, ty, text=lab, font=("", 9))
        nx, ny = self._polar_gauge(cx, cy, r-6, 90)
        needle = c.create_line(cx, cy, nx, ny, width=4)
        c.create_text(cx, cy+10, text="°", anchor="n")
        return {"canvas": c, "cx": cx, "cy": cy, "r": r, "needle": needle}

    def _polar_gauge(self, cx, cy, r, angle_0_left):
        theta = math.radians(180 - angle_0_left)
        x = cx + r * math.cos(theta)
        y = cy - r * math.sin(theta)
        return (x, y)

    def _update_gauge(self, idx, angle_0_left):
        angle_0_left = max(0, min(180, int(angle_0_left)))
        g = self.gauges[idx]
        cx, cy, r = g["cx"], g["cy"], g["r"]
        nx, ny = self._polar_gauge(cx, cy, r-6, angle_0_left)
        g["canvas"].coords(g["needle"], cx, cy, nx, ny)

    def _set_angle_local(self, idx, angle_0_left):
        a = max(0, min(180, int(angle_0_left)))
        s, e, _ = self.rows[idx]
        s.set(a)
        e.delete(0, tk.END); e.insert(0, str(a))
        self._update_gauge(idx, a)

    # ---------- Helpers (group) ----------
    def _selected_indices(self):
        return [i for i, v in enumerate(self.sel_vars) if v.get()]

    def _group_send_angle(self):
        sel = self._selected_indices()
        if not sel:
            messagebox.showinfo("Group", "Tidak ada servo yang dipilih."); return
        try:
            ang = int(self.group_angle_var.get())
        except ValueError:
            messagebox.showerror("Group", "Angle harus angka 0..180"); return
        ang = max(0, min(180, ang))
        for idx in sel:
            self._set_angle_local(idx, ang)
            self.send_cmd(f"S{idx+1}:{ang}")

    def _group_push_ui(self):
        sel = self._selected_indices()
        if not sel:
            messagebox.showinfo("Group", "Tidak ada servo yang dipilih."); return
        for idx in sel:
            s, e, _ = self.rows[idx]
            ang = int(s.get())
            self._set_angle_local(idx, ang)
            self.send_cmd(f"S{idx+1}:{ang}")

    def _group_home(self):
        sel = self._selected_indices()
        if not sel:
            messagebox.showinfo("Group", "Tidak ada servo yang dipilih."); return
        for idx in sel:
            self._set_angle_local(idx, 90)
            self.send_cmd(f"HOME{idx+1}")

    def _select_all(self):
        for v in self.sel_vars: v.set(True)

    def _clear_selection(self):
        for v in self.sel_vars: v.set(False)

    # ---------- HOME ----------
    def home_all(self):
        for i in range(NUM_SERVOS):
            self._set_angle_local(i, 90)
        self.send_cmd("HOMEALL")

    def home_one(self, idx1):
        if 1 <= idx1 <= NUM_SERVOS:
            self._set_angle_local(idx1-1, 90)
            self.send_cmd(f"HOME{idx1}")

    # ---------- Pins ----------
    def apply_pins(self):
        try:
            pins = [int(v.get()) for v in self.pin_vars]
        except ValueError:
            messagebox.showerror("Pins", "Semua Pin harus angka."); return
        if len(set(pins)) != len(pins):
            messagebox.showerror("Pins", "Pin tidak boleh duplikat."); return

        # Validasi Arduino Mega: 2–13 atau 22–53
        def valid_mega(p): return (2 <= p <= 13) or (22 <= p <= 53)
        invalid = [p for p in pins if not valid_mega(p)]
        if invalid:
            messagebox.showerror("Pins", f"Pin tidak valid untuk MEGA: {invalid}\nGunakan 2–13 atau 22–53.")
            return

        self.send_cmd("PINMAP:" + ",".join(str(p) for p in pins))

    def read_pins(self):
        self.send_cmd("GETPINMAP")

    # ---------- Ports ----------
    def _refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        items = [f"{p.device} — {p.description}" for p in ports]
        self.port_cb["values"] = items
        if items: self.port_cb.current(0)

    def _selected_device(self):
        v = self.port_cb.get()
        return v.split(" — ")[0] if v else ""

    # ---------- Serial ----------
    def toggle_connect(self):
        if self.ser and self.ser.is_open:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        dev = self._selected_device()
        if not dev:
            messagebox.showwarning("Port", "Pilih port terlebih dahulu"); return
        try:
            self.ser = serial.Serial(dev, BAUD, timeout=0.1)
            self.btn_connect.config(text="Disconnect")
            self._log(f"Connected to {dev} @ {BAUD}")
            self.stop_reader.clear()
            self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.reader_thread.start()
            self.read_pins()  # minta firmware echo PINMAP
        except Exception as e:
            messagebox.showerror("Connect Error", str(e)); self.ser = None

    def _disconnect(self):
        self.stop_reader.set()
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=0.8)
        if self.ser:
            try: self.ser.close()
            except: pass
        self.ser = None
        self.btn_connect.config(text="Connect")
        self._log("Disconnected.")

    def send_cmd(self, cmd: str):
        if not (self.ser and self.ser.is_open):
            self._log("! Not connected"); return
        try:
            self.ser.write((cmd + "\n").encode("utf-8"))
            self._log(f"> {cmd}")
        except Exception as e:
            self._log(f"! Send error: {e}")

    def _reader_loop(self):
        try:
            while not self.stop_reader.is_set():
                if self.ser and self.ser.in_waiting:
                    line = self.ser.readline().decode(errors="ignore").strip()
                    if line:
                        self.log_queue.put(line)
        except Exception as e:
            self.log_queue.put(f"! Read error: {e}")

    def _drain_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg.startswith("PINMAP:"):
                    parts = msg.split(":",1)[1].split(",")
                    if len(parts) == NUM_SERVOS:
                        for i,p in enumerate(parts): self.pin_vars[i].set(p.strip())
                self._log(msg)
        except queue.Empty:
            pass
        self.after(50, self._drain_log_queue)

    # ---------- Utils ----------
    def _log(self, msg: str):
        self.log.insert("end", msg + "\n"); self.log.see("end")

    def on_close(self):
        self._disconnect(); self.destroy()


if __name__ == "__main__":
    app = ServoTester()
    app.mainloop()