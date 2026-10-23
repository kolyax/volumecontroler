while 1:
    try:
        import argparse
        import json
        import logging
        import os
        import sys
        import threading
        import time
        import tkinter as tk
        from tkinter import messagebox, ttk

        # --- НАСТРОЙКА ЛОГЕРА ---
        logging.basicConfig(
            filename="macro_debug.log",
            level=logging.INFO,
            format="[%(asctime)s] [%(levelname)s] %(message)s",
            encoding="utf-8",
        )
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
        )
        logging.getLogger().addHandler(console_handler)


        def map_value(v, r1s, r1e, r2s, r2e):
          return r2s + (v - r1s) * (r2e - r2s) / (r1e - r1s)


        try:
          import mido

          logging.info("Библиотека mido успешно импортирована.")
        except Exception as e:
          logging.critical(f"Ошибка импорта mido: {e}")

        try:
          from pynput import keyboard

          logging.info("Библиотека pynput успешно импортирована.")
        except Exception as e:
          logging.critical(f"Ошибка импорта pynput: {e}")

        CONFIG_FILE = "config.json"

        DEFAULT_CONFIG = {
            "port_name": "loopMIDI Port 1",
            "cc_channel": 0,
            "step": 1,
            "key_turn_left": "Key.media_previous",
            "key_turn_right": "Key.media_next",
            "key_press": "Key.media_play_pause",
            "knobs": [
                {
                    "name": "Основная громкость",
                    "cc_control": 7,
                    "initial_value": 64,
                    "step": 1,
                    "map_in_min": 0,
                    "map_in_max": 127,
                    "map_out_min": 0,
                    "map_out_max": 100,
                },
                {
                    "name": "Микрофон",
                    "cc_control": 9,
                    "initial_value": 64,
                    "step": 1,
                    "map_in_min": 0,
                    "map_in_max": 127,
                    "map_out_min": 0,
                    "map_out_max": 100,
                },
            ],
            "switches": [
                {
                    "name": "Колонки Вкл/Выкл",
                    "cc_control": 8,
                    "state": True,
                    "val_on": 127,
                    "val_off": 0,
                },
                {
                    "name": "Звук на микрофон",
                    "cc_control": 10,
                    "state": False,
                    "val_on": 127,
                    "val_off": 0,
                },
            ],
        }


        def load_config():
          if os.path.exists(CONFIG_FILE):
            try:
              with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                logging.info("Конфигурация успешно загружена из файла.")
                return cfg
            except Exception as e:
              logging.error(f"Ошибка чтения config.json: {e}. Используем дефолтный.")
          else:
            logging.info("Файл конфигурации не найден. Используем дефолтный.")
          return DEFAULT_CONFIG


        def save_config(config):
          try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
              json.dump(config, f, ensure_ascii=False, indent=4)
            logging.info("Конфигурация успешно сохранена.")
          except Exception as e:
            logging.error(f"Ошибка сохранения config.json: {e}")


        # Глобальные переменные рантайма
        config = load_config()
        midi_out = None
        is_pressed = False
        active_knob_index = 0
        knob_values = [k.get("initial_value", 64) for k in config.get("knobs", [])]
        switch_states = [s.get("state", False) for s in config.get("switches", [])]

        root_ui = None
        label_title = None
        label_val = None
        listener_instance = None
        hide_timer = None

        press_start_time = 0
        LONG_PRESS_THRESHOLD = 0.3

        # Переменные для отслеживания двойного клика физической кнопки
        last_press_time = 0
        DOUBLE_CLICK_THRESHOLD = 0.35
        single_click_timer = None
        dashboard_instance = None  # Ссылка на активное полноэкранное окно


        # --- Логика MIDI ---
        def init_midi():
          global midi_out
          port_name = config.get("port_name", "loopMIDI Port 1")
          try:
            midi_out = mido.open_output(port_name)
            logging.info(f"MIDI порт '{port_name}' успешно открыт.")
          except Exception as e:
            logging.error(f"Ошибка открытия MIDI порт '{port_name}': {e}.")


        def send_midi(cc, val):
          if midi_out:
            try:
              msg = mido.Message(
                  "control_change",
                  channel=config.get("cc_channel", 0),
                  control=cc,
                  value=int(val),
              )
              midi_out.send(msg)
              logging.info(f"MIDI отправлено: CC {cc}, Value {val}")
            except Exception as e:
              logging.fatal(f"Ошибка отправки MIDI: {e}")
              sys.exit(0)
          else:
            logging.warning(
                f"ПРЕДУПРЕЖДЕНИЕ: MIDI порт не открыт! Сообщение CC {cc} не отправлено."
            )


        def handle_turn(direction):
          global active_knob_index, knob_values
          knobs = config.get("knobs", [])
          if not knobs:
            return

          idx = active_knob_index
          knob = knobs[idx]
          step = knob.get("step", 1)

          min_val = knob.get("map_in_min", 0)
          max_val = knob.get("map_in_max", 127)

          if is_pressed:
            if direction == "right":
              active_knob_index = (active_knob_index + 1) % len(knobs)
            else:
              active_knob_index = (active_knob_index - 1) % len(knobs)
            logging.info(
                f"Переключено на крутилку: {knobs[active_knob_index]['name']}"
            )
            update_floating_ui()
            show_floating_menu()
            schedule_hide_timer()
          else:
            val = knob_values[idx]
            if direction == "right":
              val = min(max_val, val + step)
            else:
              val = max(min_val, val - step)

            knob_values[idx] = val
            send_midi(knob["cc_control"], val)
            logging.info(
                f"[{knob['name']}] CC {knob['cc_control']} -> Внутреннее значение: {val}"
            )
            update_floating_ui()
            show_floating_menu()
            schedule_hide_timer()


        def schedule_hide_timer():
          global hide_timer
          if hide_timer is not None and root_ui is not None:
            try:
              root_ui.after_cancel(hide_timer)
            except Exception:
              pass

          if root_ui is not None:
            try:
              hide_timer = root_ui.after(1200, hide_floating_menu_auto)
            except Exception as e:
              logging.error(f"Ошибка планирования таймера скрытия: {e}")


        def hide_floating_menu_auto():
          if not is_pressed:
            hide_floating_menu()


        # --- Открытие/Закрытие полноэкранной панели ---
        def open_fullscreen_dashboard():
          global dashboard_instance,dashboard_old_instance

          # Если окно уже открыто — закрываем его
          if dashboard_instance is not None:
              try:
                  dashboard_old_instance = dashboard_instance
                  # Передаем через лямбду, чтобы destroy() вызвался именно через 100мс
                  dashboard_instance.after(
                      100, lambda: dashboard_old_instance.destroy()
                  )
                  dashboard_instance = None
              except Exception as e:
                  print(e)

              logging.info("Закрываем FullScreenDashboard по двойному клику")
              return

          def run_dashboard():
            global dashboard_instance
            dash_root = tk.Tk()

            dashboard_instance = dash_root
            FullScreenDashboard(dash_root)
            dash_root.mainloop()
            dashboard_instance = None

          logging.info("Открываем FullScreenDashboard по двойному клику")
          threading.Thread(target=run_dashboard, daemon=True).start()


        # --- Плавающее окно ---
        def create_floating_window():
          global root_ui, label_title, label_val
          try:
            root_ui = tk.Tk()
            root_ui.overrideredirect(True)
            root_ui.attributes("-topmost", True)
            root_ui.attributes("-alpha", 0.85)

            frame = tk.Frame(root_ui, bg="#1e1e1e", padx=12, pady=8)
            frame.pack(fill=tk.BOTH, expand=True)

            label_title = tk.Label(
                frame, text="", fg="#ffffff", bg="#1e1e1e", font=("Arial", 10, "bold")
            )
            label_title.pack(anchor="w")

            label_val = tk.Label(
                frame, text="", fg="#00ffcc", bg="#1e1e1e", font=("Arial", 12)
            )
            label_val.pack(anchor="w")

            for widget in (frame, label_title, label_val):
              widget.bind("<Double-Button-1>", lambda e: open_fullscreen_dashboard())

            update_floating_ui()

            root_ui.update_idletasks()
            w = root_ui.winfo_width()
            h = root_ui.winfo_height()
            screen_w = root_ui.winfo_screenwidth()
            screen_h = root_ui.winfo_screenheight()
            x = screen_w - w - 200
            y = screen_h - h - 60
            root_ui.geometry(f"+{x}+{y}")

            root_ui.withdraw()
            logging.info("Плавающее окно успешно создано.")
            root_ui.mainloop()
          except Exception as e:
            logging.critical(f"Критическая ошибка в плавающем окне: {e}")


        def update_floating_ui():
          if label_title and label_val and root_ui:
            try:
              root_ui.after(0, _update_ui_safe)
            except Exception as e:
              logging.error(f"Ошибка вызова UI апдейта: {e}")


        def _update_ui_safe():
          if label_title and label_val:
            knobs = config.get("knobs", [])
            if knobs:
              knob = knobs[active_knob_index]
              current_val = knob_values[active_knob_index]

              in_min = knob.get("map_in_min", 0)
              in_max = knob.get("map_in_max", 127)
              out_min = knob.get("map_out_min", 0)
              out_max = knob.get("map_out_max", 100)

              mapped_val = int(map_value(current_val, in_min, in_max, out_min, out_max))

              label_title.config(
                  text=f"⚙ {knob['name']} (Двойной клик — полный экран / закрыть)"
              )
              label_val.config(text=f"Значение: {mapped_val}  ({current_val})")


        def show_floating_menu():
          if root_ui:
            try:
              root_ui.after(0, root_ui.deiconify)
            except Exception as e:
              logging.error(f"Ошибка показа окна: {e}")


        def hide_floating_menu():
          if root_ui:
            try:
              root_ui.after(0, root_ui.withdraw)
            except Exception as e:
              logging.error(f"Ошибка скрытия окна: {e}")


        # --- Слушатель клавиатуры ---
        def key_to_string(key):
          try:
            return key.char if hasattr(key, "char") and key.char else str(key)
          except Exception as e:
            logging.error(f"Ошибка конвертации клавиши: {e}")
            return str(key)


        def on_press(key):
          global is_pressed, press_start_time
          key_str = key_to_string(key)
          logging.debug(f"Нажата клавиша: {key_str}")

          k_left = config.get("key_turn_left", "")
          k_right = config.get("key_turn_right", "")
          k_press = config.get("key_press", "")

          if key_str == k_left:
            handle_turn("left")
          elif key_str == k_right:
            handle_turn("right")
          elif key_str == k_press:
            if not is_pressed:
              is_pressed = True
              press_start_time = time.time()
              show_floating_menu()


        def execute_media_play_pause():
          try:
            logging.info("Короткое нажатие: Play/Pause")
            hide_floating_menu()
            kb_controller = keyboard.Controller()
            kb_controller.press(keyboard.Key.media_play_pause)
            kb_controller.release(keyboard.Key.media_play_pause)
          except Exception as e:
            logging.error(f"Ошибка эмуляции мультимедиа: {e}")


        def on_release(key):
          global is_pressed, last_press_time, single_click_timer
          key_str = key_to_string(key)
          logging.debug(f"Отпущена клавиша: {key_str}")
          k_press = config.get("key_press", "")

          if key_str == k_press:
            if is_pressed:
              press_duration = time.time() - press_start_time
              current_time = time.time()

              if (current_time - last_press_time) < DOUBLE_CLICK_THRESHOLD:
                if single_click_timer is not None and root_ui is not None:
                  try:
                    root_ui.after_cancel(single_click_timer)
                  except Exception:
                    pass
                logging.info("Двойной клик физической кнопки: переключаем FullScreenDashboard")
                hide_floating_menu()
                open_fullscreen_dashboard()
                last_press_time = 0
              else:
                last_press_time = current_time
                if press_duration < LONG_PRESS_THRESHOLD:
                  if root_ui is not None:
                    try:
                      single_click_timer = root_ui.after(
                          int(DOUBLE_CLICK_THRESHOLD * 1000) + 20,
                          execute_media_play_pause,
                      )
                    except Exception:
                      execute_media_play_pause()
                  else:
                    execute_media_play_pause()
                else:
                  logging.info("Длинное нажатие отпущено.")
                  hide_floating_menu()

              is_pressed = False


        def start_listener():
          global listener_instance
          logging.info("Запуск слушателя клавиатуры pynput...")
          try:
            with keyboard.Listener(
                on_press=on_press, on_release=on_release
            ) as listener:
              listener_instance = listener
              listener.join()
          except Exception as e:
            logging.critical(f"Критическая ошибка в слушателе pynput: {e}")


        # --- Полноэкранная панель ---
        class FullScreenDashboard:
          def DESTROY(self):
              self.master.destroy()
          def __init__(self, master):
            self.master = master
            self.master.title("MacroPad — Полноэкранная панель управления")

            self.master.attributes("-fullscreen", True)
            self.master.configure(bg="#121212")
            self.master.bind("<Escape>", lambda e: self.master.destroy())
            self.master.bind("<FocusOut>", lambda e: self.master.destroy())

            self.master.deiconify()
            self.master.lift()
            self.master.focus_force()
            self.create_widgets()

          def create_widgets(self):
            main_frame = tk.Frame(self.master, bg="#121212", padx=30, pady=20)
            main_frame.pack(fill=tk.BOTH, expand=True)

            header_frame = tk.Frame(main_frame, bg="#121212")
            header_frame.pack(fill=tk.X, pady=(0, 15))

            lbl_title = tk.Label(
                header_frame,
                text="🎛 ПАНЕЛЬ УПРАВЛЕНИЯ MACROPAD",
                font=("Arial", 20, "bold"),
                fg="#00ffcc",
                bg="#121212",
            )
            lbl_title.pack(side=tk.LEFT)

            btn_close = tk.Button(
                header_frame,
                text="Закрыть [ESC]",
                font=("Arial", 12, "bold"),
                bg="#ff4d4d",
                fg="#ffffff",
                bd=0,
                padx=15,
                pady=8,
                command=self.master.destroy,
            )
            btn_close.pack(side=tk.RIGHT)

            sep = tk.Frame(main_frame, height=2, bg="#333333")
            sep.pack(fill=tk.X, pady=(0, 15))

            canvas = tk.Canvas(main_frame, bg="#121212", highlightthickness=0)
            scrollbar = ttk.Scrollbar(
                main_frame, orient="vertical", command=canvas.yview
            )
            scrollable_frame = tk.Frame(canvas, bg="#121212")

            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
            )
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)

            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            # --- СЕКЦИЯ 1: МИДИ-КРУТИЛКИ ---
            lbl_sec1 = tk.Label(
                scrollable_frame,
                text="⚙ МИДИ-КРУТИЛКИ",
                font=("Arial", 14, "bold"),
                fg="#ffffff",
                bg="#121212",
            )
            lbl_sec1.pack(anchor="w", pady=(5, 10))

            knobs_container = tk.Frame(scrollable_frame, bg="#121212")
            knobs_container.pack(fill=tk.X, pady=(0, 20))

            knobs = config.get("knobs", [])
            for index, knob in enumerate(knobs):
              row = index // 2
              col = index % 2

              card = tk.LabelFrame(
                  knobs_container,
                  text=(
                      f" Канал {knob.get('cc_control', 7)}:"
                      f" {knob.get('name', 'Крутилка')} "
                  ),
                  font=("Arial", 12, "bold"),
                  fg="#ffffff",
                  bg="#1e1e1e",
                  bd=2,
                  relief="groove",
                  padx=15,
                  pady=15,
              )
              card.grid(
                  row=row, column=col, sticky="nsew", padx=10, pady=10, ipadx=5, ipady=5
              )
              knobs_container.rowconfigure(row, weight=1)
              knobs_container.columnconfigure(col, weight=1)

              val_label = tk.Label(
                  card,
                  text=f"Значение: {knob.get('initial_value', 64)}",
                  font=("Arial", 12),
                  fg="#00ffcc",
                  bg="#1e1e1e",
              )
              val_label.pack(anchor="w", pady=(0, 5))

              min_in = knob.get("map_in_min", 0)
              max_in = knob.get("map_in_max", 127)

              scale = tk.Scale(
                  card,
                  from_=min_in,
                  to=max_in,
                  orient=tk.HORIZONTAL,
                  bg="#1e1e1e",
                  fg="#ffffff",
                  troughcolor="#333333",
                  highlightthickness=0,
              )
              scale.set(knob_values[index] if index < len(knob_values) else 64)
              scale.pack(fill=tk.X, pady=5)

              def make_scale_handler(idx, c_ctrl, lbl, k_name):
                return lambda val: self.on_scale_changed(
                    idx, c_ctrl, val, lbl, k_name
                )

              scale.config(
                  command=make_scale_handler(
                      index, knob.get("cc_control", 7), val_label, knob.get("name")
                  )
              )

            # --- СЕКЦИЯ 2: МИДИ-ТУМБЛЕРЫ ---
            lbl_sec2 = tk.Label(
                scrollable_frame,
                text="🔌 МИДИ-ТУМБЛЕРЫ",
                font=("Arial", 14, "bold"),
                fg="#ffffff",
                bg="#121212",
            )
            lbl_sec2.pack(anchor="w", pady=(10, 10))

            switches_container = tk.Frame(scrollable_frame, bg="#121212")
            switches_container.pack(fill=tk.X, pady=(0, 20))

            switches = config.get("switches", [])
            for index, sw in enumerate(switches):
              row = index // 2
              col = index % 2

              sw_card = tk.LabelFrame(
                  switches_container,
                  text=(
                      f" Канал CC {sw.get('cc_control', 0)}: {sw.get('name', 'Тумблер')} "
                  ),
                  font=("Arial", 12, "bold"),
                  fg="#ffffff",
                  bg="#1e1e1e",
                  bd=2,
                  relief="groove",
                  padx=15,
                  pady=15,
              )
              sw_card.grid(
                  row=row, column=col, sticky="nsew", padx=10, pady=10, ipadx=5, ipady=5
              )
              switches_container.rowconfigure(row, weight=1)
              switches_container.columnconfigure(col, weight=1)

              var_state = tk.BooleanVar(
                  value=switch_states[index] if index < len(switch_states) else False
              )

              is_active = var_state.get()
              btn_switch = tk.Button(
                  sw_card,
                  text="ВКЛЮЧЕНО" if is_active else "ВЫКЛЮЧЕНО",
                  font=("Arial", 11, "bold"),
                  bg="#00ffcc" if is_active else "#333333",
                  fg="#121212" if is_active else "#ffffff",
                  bd=0,
                  padx=10,
                  pady=8,
              )

              def make_switch_handler(idx, s_ctrl, s_var, s_btn, s_name, s_on, s_off):
                def toggle_action():
                  current = not s_var.get()
                  s_var.set(current)
                  s_btn.config(
                      text="ВКЛЮЧЕНО" if current else "ВЫКЛЮЧЕНО",
                      bg="#00ffcc" if current else "#333333",
                      fg="#121212" if current else "#ffffff",
                  )
                  self.on_switch_toggled(idx, s_ctrl, s_var, s_name, s_on, s_off)

                return toggle_action

              btn_switch.config(
                  command=make_switch_handler(
                      index,
                      sw.get("cc_control", 0),
                      var_state,
                      btn_switch,
                      sw.get("name"),
                      sw.get("val_on", 127),
                      sw.get("val_off", 0),
                  )
              )
              btn_switch.pack(anchor="w", pady=5, fill=tk.X)

          def on_scale_changed(self, idx, c_ctrl, val, lbl, k_name):
            v_int = int(float(val))
            knob_values[idx] = v_int
            send_midi(c_ctrl, v_int)
            lbl.config(text=f"Значение: {v_int}")
            logging.info(f"[Dashboard] Крутилка [{k_name}] CC {c_ctrl} -> {v_int}")
            update_floating_ui()

          def on_switch_toggled(
              self, idx, c_ctrl, var_state, sw_name, val_on, val_off
          ):
            is_active = var_state.get()
            switch_states[idx] = is_active
            config["switches"][idx]["state"] = is_active
            save_config(config)

            midi_val = int(val_on) if is_active else int(val_off)
            send_midi(c_ctrl, midi_val)

            logging.info(
                f"[Dashboard] Тумблер '{sw_name}' (CC {c_ctrl}) -> Состояние:"
                f" {is_active}, отправлено MIDI значение: {midi_val}"
            )
            update_floating_ui()


        # --- ВИЗУАЛЬНЫЙ РЕДАКТОР НАСТРОЕК ---
        class SettingsApp:

          def __init__(self, master):
            self.master = master
            self.master.title("Визуальный редактор конфигурации MacroPad")
            self.master.geometry("750x750")
            self.master.minsize(650, 600)

            self.knob_entries = []
            self.switch_entries = []

            self.create_widgets()
            self.load_to_form()

          def create_widgets(self):
            main_frame = ttk.Frame(self.master, padding=15)
            main_frame.pack(fill=tk.BOTH, expand=True)

            top_frame = ttk.LabelFrame(
                main_frame, text=" Основные параметры ", padding=10
            )
            top_frame.pack(fill=tk.X, pady=(0, 10))

            ttk.Label(top_frame, text="Имя MIDI порта:").grid(
                row=0, column=0, sticky="w", pady=2
            )
            self.ent_port = ttk.Entry(top_frame, width=25)
            self.ent_port.grid(row=0, column=1, sticky="ew", pady=2, padx=5)

            binds_lbl_frm = ttk.LabelFrame(
                main_frame, text=" Управление с клавиатуры / энкодера ", padding=10
            )
            binds_lbl_frm.pack(fill=tk.X, pady=(0, 10))

            ttk.Label(binds_lbl_frm, text="Поворот Влево:").grid(
                row=0, column=0, sticky="w", pady=3
            )
            self.ent_left = ttk.Entry(binds_lbl_frm, width=22)
            self.ent_left.grid(row=0, column=1, padx=5, pady=3)
            ttk.Button(
                binds_lbl_frm,
                text="Бинд",
                command=lambda: self.capture_key("left"),
                width=8,
            ).grid(row=0, column=2, pady=3)

            ttk.Label(binds_lbl_frm, text="Поворот Вправо:").grid(
                row=1, column=0, sticky="w", pady=3
            )
            self.ent_right = ttk.Entry(binds_lbl_frm, width=22)
            self.ent_right.grid(row=1, column=1, padx=5, pady=3)
            ttk.Button(
                binds_lbl_frm,
                text="Бинд",
                command=lambda: self.capture_key("right"),
                width=8,
            ).grid(row=1, column=2, pady=3)

            ttk.Label(binds_lbl_frm, text="Кнопка Нажатия:").grid(
                row=2, column=0, sticky="w", pady=3
            )
            self.ent_press = ttk.Entry(binds_lbl_frm, width=22)
            self.ent_press.grid(row=2, column=1, padx=5, pady=3)
            ttk.Button(
                binds_lbl_frm,
                text="Бинд",
                command=lambda: self.capture_key("press"),
                width=8,
            ).grid(row=2, column=2, pady=3)

            editor_notebook = ttk.Notebook(main_frame)
            editor_notebook.pack(fill=tk.BOTH, expand=True, pady=5)

            # Вкладка 1: Крутилки
            knobs_tab = ttk.Frame(editor_notebook, padding=10)
            editor_notebook.add(knobs_tab, text=" ⚙ Крутилки ")

            btn_add_knob = ttk.Button(
                knobs_tab, text="+ Добавить крутилку", command=self.add_knob_row
            )
            btn_add_knob.pack(anchor="w", pady=(0, 5))

            knobs_canvas_frame = ttk.Frame(knobs_tab)
            knobs_canvas_frame.pack(fill=tk.BOTH, expand=True)

            self.knobs_canvas = tk.Canvas(
                knobs_canvas_frame, bg="#f0f0f0", bd=0, highlightthickness=0
            )
            knobs_scrollbar = ttk.Scrollbar(
                knobs_canvas_frame, orient="vertical", command=self.knobs_canvas.yview
            )
            self.knobs_inner_frame = ttk.Frame(self.knobs_canvas)

            self.knobs_inner_frame.bind(
                "<Configure>",
                lambda e: self.knobs_canvas.configure(
                    scrollregion=self.knobs_canvas.bbox("all")
                ),
            )
            self.knobs_canvas.create_window(
                (0, 0), window=self.knobs_inner_frame, anchor="nw"
            )
            self.knobs_canvas.configure(yscrollcommand=knobs_scrollbar.set)

            self.knobs_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            knobs_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            # Вкладка 2: Тумблеры
            switches_tab = ttk.Frame(editor_notebook, padding=10)
            editor_notebook.add(switches_tab, text=" 🔌 Тумблеры ")

            btn_add_switch = ttk.Button(
                switches_tab, text="+ Добавить тумблер", command=self.add_switch_row
            )
            btn_add_switch.pack(anchor="w", pady=(0, 5))

            switches_canvas_frame = ttk.Frame(switches_tab)
            switches_canvas_frame.pack(fill=tk.BOTH, expand=True)

            self.switches_canvas = tk.Canvas(
                switches_canvas_frame, bg="#f0f0f0", bd=0, highlightthickness=0
            )
            switches_scrollbar = ttk.Scrollbar(
                switches_canvas_frame,
                orient="vertical",
                command=self.switches_canvas.yview,
            )
            self.switches_inner_frame = ttk.Frame(self.switches_canvas)

            self.switches_inner_frame.bind(
                "<Configure>",
                lambda e: self.switches_canvas.configure(
                    scrollregion=self.switches_canvas.bbox("all")
                ),
            )
            self.switches_canvas.create_window(
                (0, 0), window=self.switches_inner_frame, anchor="nw"
            )
            self.switches_canvas.configure(yscrollcommand=switches_scrollbar.set)

            self.switches_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            switches_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            btn_save = ttk.Button(
                main_frame,
                text="Сохранить и применить конфигурацию",
                command=self.save_and_run,
            )
            btn_save.pack(fill=tk.X, pady=(10, 0), ipady=5)

          def add_knob_row(self, data=None):
            row_frame = ttk.Frame(
                self.knobs_inner_frame, padding=5, relief="groove", borderwidth=1
            )
            row_frame.pack(fill=tk.X, expand=True, pady=3)

            ttk.Label(row_frame, text="Имя:").grid(row=0, column=0, sticky="w")
            ent_name = ttk.Entry(row_frame, width=15)
            ent_name.grid(row=0, column=1, padx=2)
            ent_name.insert(
                0, data.get("name", "Крутилка") if data else "Новая крутилка"
            )

            ttk.Label(row_frame, text="CC:").grid(row=0, column=2, sticky="w")
            ent_cc = ttk.Entry(row_frame, width=5)
            ent_cc.grid(row=0, column=3, padx=2)
            ent_cc.insert(0, str(data.get("cc_control", 7)) if data else "7")

            ttk.Label(row_frame, text="Нач:").grid(row=0, column=4, sticky="w")
            ent_init = ttk.Entry(row_frame, width=5)
            ent_init.grid(row=0, column=5, padx=2)
            ent_init.insert(0, str(data.get("initial_value", 64)) if data else "64")

            ttk.Label(row_frame, text="Шаг:").grid(row=0, column=6, sticky="w")
            ent_step = ttk.Entry(row_frame, width=4)
            ent_step.grid(row=0, column=7, padx=2)
            ent_step.insert(0, str(data.get("step", 1)) if data else "1")

            btn_del = ttk.Button(
                row_frame,
                text="X",
                width=3,
                command=lambda: self.remove_knob_row(row_frame, data_dict),
            )
            btn_del.grid(row=0, column=8, padx=5)

            data_dict = {
                "frame": row_frame,
                "name": ent_name,
                "cc": ent_cc,
                "init": ent_init,
                "step": ent_step,
            }
            self.knob_entries.append(data_dict)

          def remove_knob_row(self, frame, data_dict):
            frame.destroy()
            if data_dict in self.knob_entries:
              self.knob_entries.remove(data_dict)

          def add_switch_row(self, data=None):
            row_frame = ttk.Frame(
                self.switches_inner_frame, padding=5, relief="groove", borderwidth=1
            )
            row_frame.pack(fill=tk.X, expand=True, pady=3)

            ttk.Label(row_frame, text="Имя:").grid(row=0, column=0, sticky="w")
            ent_name = ttk.Entry(row_frame, width=15)
            ent_name.grid(row=0, column=1, padx=2)
            ent_name.insert(
                0, data.get("name", "Тумблер") if data else "Новый тумблер"
            )

            ttk.Label(row_frame, text="CC:").grid(row=0, column=2, sticky="w")
            ent_cc = ttk.Entry(row_frame, width=5)
            ent_cc.grid(row=0, column=3, padx=2)
            ent_cc.insert(0, str(data.get("cc_control", 8)) if data else "8")

            var_state = tk.BooleanVar(
                value=data.get("state", False) if data else False
            )
            chk = ttk.Checkbutton(row_frame, text="Вкл", variable=var_state)
            chk.grid(row=0, column=4, padx=5)

            ttk.Label(row_frame, text="ON val:").grid(row=0, column=5, sticky="w")
            ent_on = ttk.Entry(row_frame, width=5)
            ent_on.grid(row=0, column=6, padx=2)
            ent_on.insert(0, str(data.get("val_on", 127)) if data else "127")

            ttk.Label(row_frame, text="OFF val:").grid(row=0, column=7, sticky="w")
            ent_off = ttk.Entry(row_frame, width=5)
            ent_off.grid(row=0, column=8, padx=2)
            ent_off.insert(0, str(data.get("val_off", 0)) if data else "0")

            btn_del = ttk.Button(
                row_frame,
                text="X",
                width=3,
                command=lambda: self.remove_switch_row(row_frame, data_dict),
            )
            btn_del.grid(row=0, column=9, padx=5)

            data_dict = {
                "frame": row_frame,
                "name": ent_name,
                "cc": ent_cc,
                "state": var_state,
                "val_on": ent_on,
                "val_off": ent_off,
            }
            self.switch_entries.append(data_dict)

          def remove_switch_row(self, frame, data_dict):
            frame.destroy()
            if data_dict in self.switch_entries:
              self.switch_entries.remove(data_dict)

          def load_to_form(self):
            cfg = load_config()
            self.ent_port.delete(0, tk.END)
            self.ent_port.insert(0, cfg.get("port_name", "loopMIDI Port 1"))

            self.ent_left.delete(0, tk.END)
            self.ent_left.insert(0, str(cfg.get("key_turn_left", "")))

            self.ent_right.delete(0, tk.END)
            self.ent_right.insert(0, str(cfg.get("key_turn_right", "")))

            self.ent_press.delete(0, tk.END)
            self.ent_press.insert(0, str(cfg.get("key_press", "")))

            for item in self.knob_entries:
              item["frame"].destroy()
            self.knob_entries.clear()

            for item in self.switch_entries:
              item["frame"].destroy()
            self.switch_entries.clear()

            for knob in cfg.get("knobs", []):
              self.add_knob_row(knob)

            for sw in cfg.get("switches", []):
              self.add_switch_row(sw)

          def capture_key(self, target_field):
            capture_win = tk.Toplevel(self.master)
            capture_win.title("Сделать бинд")
            capture_win.geometry("320x130")
            capture_win.attributes("-topmost", True)

            ttk.Label(
                capture_win,
                text="Ожидание нажатия...\nПокрути энкодер или нажми клавишу.",
                font=("Arial", 10),
                justify="center",
            ).pack(pady=15)

            captured_val = [None]

            def on_capture(key):
              captured_val[0] = key_to_string(key)
              capture_win.destroy()
              return False

            capture_listener = keyboard.Listener(on_press=on_capture)
            capture_listener.start()
            capture_win.wait_window()
            capture_listener.stop()

            if captured_val[0] is not None:
              val = captured_val[0]
              target_entry = (
                  self.ent_left
                  if target_field == "left"
                  else (
                      self.ent_right
                      if target_field == "right"
                      else self.ent_press
                  )
              )
              target_entry.delete(0, tk.END)
              target_entry.insert(0, str(val))

          def save_and_run(self):
            try:
              port = self.ent_port.get().strip()
              k_left = self.ent_left.get().strip()
              k_right = self.ent_right.get().strip()
              k_press = self.ent_press.get().strip()

              parsed_knobs = []
              for k in self.knob_entries:
                name = k["name"].get().strip() or "Крутилка"
                cc = int(k["cc"].get()) if k["cc"].get().isdigit() else 7
                init_val = int(k["init"].get()) if k["init"].get().isdigit() else 64
                step = int(k["step"].get()) if k["step"].get().isdigit() else 1

                parsed_knobs.append({
                    "name": name,
                    "cc_control": cc,
                    "initial_value": init_val,
                    "step": step,
                    "map_in_min": 0,
                    "map_in_max": 127,
                    "map_out_min": 0,
                    "map_out_max": 100,
                })

              parsed_switches = []
              for s in self.switch_entries:
                name = s["name"].get().strip() or "Тумблер"
                cc = int(s["cc"].get()) if s["cc"].get().isdigit() else 8
                state = s["state"].get()
                val_on = int(s["val_on"].get()) if s["val_on"].get().isdigit() else 127
                val_off = (
                    int(s["val_off"].get()) if s["val_off"].get().isdigit() else 0
                )

                parsed_switches.append({
                    "name": name,
                    "cc_control": cc,
                    "state": state,
                    "val_on": val_on,
                    "val_off": val_off,
                })

              global config, knob_values, switch_states
              new_cfg = load_config()
              new_cfg["port_name"] = port
              new_cfg["key_turn_left"] = k_left
              new_cfg["key_turn_right"] = k_right
              new_cfg["key_press"] = k_press
              new_cfg["knobs"] = parsed_knobs
              new_cfg["switches"] = parsed_switches

              save_config(new_cfg)
              config = new_cfg
              knob_values = [k.get("initial_value", 64) for k in config.get("knobs", [])]
              switch_states = [s.get("state", False) for s in config.get("switches", [])]

              messagebox.showinfo("Успех", "Визуальная конфигурация успешно сохранена!")
              self.master.destroy()

            except Exception as e:
              logging.error(f"Ошибка при сохранении конфигурации: {e}")
              messagebox.showerror(
                  "Ошибка", f"Проверьте правильность введенных полей:\n{e}"
              )


        def run_background_services():
          global config, knob_values, switch_states
          config = load_config()
          knob_values = [k.get("initial_value", 64) for k in config.get("knobs", [])]
          switch_states = [s.get("state", False) for s in config.get("switches", [])]

          init_midi()

          threading.Thread(target=create_floating_window, daemon=True).start()

          logging.info("Фоновые сервисы запущены. Старт слушателя...")
          start_listener()


        if __name__ == "__main__":
          parser = argparse.ArgumentParser(
              description="MacroPad MIDI Controller Service"
          )
          parser.add_argument(
              "--no-ui",
              "-n",
              action="store_true",
              help="Запустить сразу в фоновом режиме без открытия редактора настроек",
          )
          args = parser.parse_args()

          try:
            logging.info("=== ПРИЛОЖЕНИЕ СТАРТОВАЛО ===")

            if args.no_ui:
              run_background_services()
            else:
              threading.Thread(target=run_background_services, daemon=True).start()

              root = tk.Tk()
              app = SettingsApp(root)
              root.mainloop()

          except Exception as e:
            logging.critical(f"Критическая ошибка в main: {e}")
    except:
        pass