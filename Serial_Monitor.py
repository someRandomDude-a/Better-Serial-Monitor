import tkinter as tk
from tkinter import ttk, messagebox, colorchooser
import serial
import serial.tools.list_ports
import threading
import pyperclip
import json
import os

class SerialMonitor:
    def __init__(self, root):
        self.root = root
        self.root.title("Serial Monitor")
        self.root.geometry("600x400")

        # Initialize custom color attributes
        self.custom_bg_color = 'black'
        self.custom_fg_color = 'cyan'
        self.custom_accent_color = 'teal'
        self.light_accent_color = '#00b3b3'  # Brighter shade of teal for light theme

        # Initialize selected theme
        self.selected_theme = tk.StringVar(value="dark")  # Set default to "dark"

        # Load settings
        self.load_settings()
        
        # Set the theme after loading settings
        self.set_theme(self.selected_theme.get())

        self.baud_rates = [110, 300, 600, 1200, 2400, 4800, 9600, 14400, 19200,
                           38400, 57600, 115200, 230400, 250000, 500000, 1000000,
                           1500000, 2000000]
        self.custom_baud_rates = []
        self.serial_connection = None
        self.read_thread = None
        self.is_reading = False
        self.lock = threading.Lock()  # Create a lock for thread safety

        self.create_widgets()
        self.populate_ports()
        self.settings_window = None

    def set_theme(self, mode):
        try:
            if mode == "dark":
                self.bg_color = 'black'
                self.fg_color = 'cyan'
                self.accent_color = 'teal'
            elif mode == "light":
                self.bg_color = 'white'
                self.fg_color = 'black'
                self.accent_color = self.light_accent_color
            elif mode == "custom":
                self.bg_color = self.custom_bg_color
                self.fg_color = self.custom_fg_color
                self.accent_color = self.custom_accent_color

            self.root.configure(bg=self.bg_color)
            self.update_widgets_color()

            # Update Combobox style
            style = ttk.Style()
            style.configure("TCombobox", background=self.bg_color, foreground=self.fg_color)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to set theme: {e}")

    def update_widgets_color(self):
        try:
            for widget in self.root.winfo_children():
                try:
                    widget.configure(bg=self.bg_color, fg=self.fg_color)
                except tk.TclError:
                    pass

            for widget in self.root.winfo_children():
                if isinstance(widget, tk.Button):
                    widget.configure(bg=self.accent_color)

            style = ttk.Style()
            style.configure("TCombobox", background=self.bg_color, foreground=self.fg_color)

            if hasattr(self, 'output_text'):
                self.output_text.config(bg=self.bg_color, fg=self.fg_color)
            if hasattr(self, 'nl_checkbox'):
                self.nl_checkbox.config(bg=self.bg_color, fg=self.fg_color, selectcolor=self.accent_color)
            if hasattr(self, 'cr_checkbox'):
                self.cr_checkbox.config(bg=self.bg_color, fg=self.fg_color, selectcolor=self.accent_color)
            if hasattr(self, 'autoscroll_checkbox'):
                self.autoscroll_checkbox.config(bg=self.bg_color, fg=self.fg_color, selectcolor=self.accent_color)
            if hasattr(self, 'port_label'):
                self.port_label.config(background=self.bg_color, foreground=self.fg_color)
            if hasattr(self, 'baud_label'):
                self.baud_label.config(background=self.bg_color, foreground=self.fg_color)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update widget colors: {e}")

    def create_widgets(self):
        try:
            self.menu_button = tk.Button(self.root, text='☰', command=self.show_menu, bg=self.accent_color, fg='white')
            self.menu_button.grid(row=0, column=4, padx=15, pady=15, sticky='e')

            self.port_label = ttk.Label(self.root, text="Select Port:", background=self.bg_color, foreground=self.fg_color)
            self.port_label.grid(row=0, column=0, padx=5, pady=15, sticky='w')

            self.port_combobox = ttk.Combobox(self.root, state="readonly")
            self.port_combobox.grid(row=0, column=1, padx=5, pady=15, sticky='w')
            self.port_combobox.bind("<<ComboboxSelected>>", self.on_selection_change)

            self.baud_label = ttk.Label(self.root, text="Select Baud Rate:", background=self.bg_color, foreground=self.fg_color)
            self.baud_label.grid(row=0, column=2, padx=5, pady=15, sticky='e')

            self.baud_combobox = ttk.Combobox(self.root, values=self.baud_rates + self.custom_baud_rates, state="readonly")
            self.baud_combobox.set(9600)
            self.baud_combobox.grid(row=0, column=3, padx=5, pady=15, sticky='e')
            self.baud_combobox.bind("<<ComboboxSelected>>", self.on_baud_rate_change)

            self.input_text = tk.Entry(self.root, bg='#3b3b3b', fg='white', width=30)
            self.input_text.grid(row=1, column=0, columnspan=4, padx=(10, 20), pady=15, sticky='ew')
            self.input_text.insert(0, "Type here to send...")
            self.input_text.bind("<FocusIn>", self.clear_placeholder)
            self.input_text.bind("<FocusOut>", self.set_placeholder)

            checkbox_frame = tk.Frame(self.root, bg=self.accent_color)
            checkbox_frame.grid(row=1, column=4, padx=(5, 15), pady=15, sticky='w')

            self.nl_var = tk.BooleanVar()
            self.nl_checkbox = tk.Checkbutton(checkbox_frame, text='NL', variable=self.nl_var,
                                               bg=self.accent_color, activebackground=self.accent_color,
                                               selectcolor=self.accent_color, fg=self.fg_color,
                                               indicatoron=0, padx=5, pady=5)
            self.nl_checkbox.pack(side=tk.LEFT)

            self.cr_var = tk.BooleanVar()
            self.cr_checkbox = tk.Checkbutton(checkbox_frame, text='CR', variable=self.cr_var,
                                               bg=self.accent_color, activebackground=self.accent_color,
                                               selectcolor=self.accent_color, fg=self.fg_color,
                                               indicatoron=0, padx=5, pady=5)
            self.cr_checkbox.pack(side=tk.LEFT)

            output_frame = tk.Frame(self.root)
            output_frame.grid(row=2, column=0, columnspan=6, sticky='nsew', padx=10, pady=15)
            self.root.grid_rowconfigure(2, weight=1)
            for i in range(6):
                self.root.grid_columnconfigure(i, weight=1)

            self.root.grid_columnconfigure(4, minsize=85)  # Set minimum width for column 4

            self.output_text = tk.Text(output_frame, wrap='word', bg=self.bg_color, fg=self.fg_color, width=50)
            self.output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.scrollbar = tk.Scrollbar(output_frame, command=self.output_text.yview)
            self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            self.output_text.config(yscrollcommand=self.scrollbar.set)

            button_width = 12

            self.reconnect_button = tk.Button(self.root, text="Reconnect", command=self.reconnect, bg=self.accent_color, fg='white', width=button_width)
            self.reconnect_button.grid(row=3, column=0, padx=5, pady=10)

            self.pause_button = tk.Button(self.root, text="Pause", command=self.pause, bg=self.accent_color, fg='white', width=button_width)
            self.pause_button.grid(row=3, column=1, padx=5, pady=10)

            self.clear_button = tk.Button(self.root, text="Clear", command=self.clear_output, bg=self.accent_color, fg='white', width=button_width)
            self.clear_button.grid(row=3, column=2, padx=5, pady=10)

            self.copy_button = tk.Button(self.root, text="Copy Output", command=self.copy_output, bg=self.accent_color, fg='white', width=button_width)
            self.copy_button.grid(row=3, column=3, padx=5, pady=10)

            self.autoscroll_var = tk.BooleanVar(value=True)
            self.autoscroll_checkbox = tk.Checkbutton(self.root, text='Auto Scroll', variable=self.autoscroll_var,
                                                       bg=self.accent_color, activebackground=self.accent_color,
                                                       selectcolor=self.accent_color, fg=self.fg_color,
                                                       indicatoron=0, padx=5, pady=5)
            self.autoscroll_checkbox.grid(row=3, column=4, padx=5, pady=10, sticky='w')
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create widgets: {e}")

    def show_menu(self):
        try:
            if self.settings_window is not None and self.settings_window.winfo_exists():
                self.settings_window.lift()
                return

            self.settings_window = tk.Toplevel(self.root)
            self.settings_window.title("Settings")
            self.settings_window.geometry("300x500")  # Increased height by 100px
            
            theme_frame = tk.Frame(self.settings_window, bg=self.bg_color)
            theme_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            theme_label = tk.Label(theme_frame, text="Select Theme:", bg=self.bg_color, fg=self.fg_color)
            theme_label.pack(pady=(10, 0))

            self.theme_options = ["dark", "light", "custom"]
            for option in self.theme_options:
                rb = tk.Radiobutton(theme_frame, text=option.capitalize(), variable=self.selected_theme,
                                    value=option, bg=self.bg_color, fg=self.fg_color,
                                    command=lambda: self.set_theme(self.selected_theme.get()))
                rb.pack(anchor=tk.W)

            custom_color_frame = tk.Frame(self.settings_window, bg=self.bg_color)
            custom_color_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            self.custom_bg_button = tk.Button(custom_color_frame, text="Select Background Color", command=self.select_bg_color,
                                               bg=self.accent_color, fg='white')
            self.custom_bg_button.pack(pady=5)

            self.custom_fg_button = tk.Button(custom_color_frame, text="Select Foreground Color", command=self.select_fg_color,
                                               bg=self.accent_color, fg='white')
            self.custom_fg_button.pack(pady=5)

            self.custom_accent_button = tk.Button(custom_color_frame, text="Select Accent Color", command=self.select_accent_color,
                                                   bg=self.accent_color, fg='white')
            self.custom_accent_button.pack(pady=5)

            # Custom baud rate section
            baud_frame = tk.Frame(self.settings_window, bg=self.bg_color)
            baud_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            self.custom_baud_entry = tk.Entry(baud_frame, width=15, bg=self.bg_color, fg=self.fg_color)
            self.custom_baud_entry.pack(side=tk.LEFT, padx=5)
            self.custom_baud_entry.insert(0, "Custom Baud")

            add_baud_button = tk.Button(baud_frame, text="Add Baud Rate", command=self.add_custom_baud_rate,
                                         bg=self.accent_color, fg='white')
            add_baud_button.pack(side=tk.LEFT, padx=5)

            save_button = tk.Button(self.settings_window, text="Save Settings", command=self.save_settings,
                                    bg=self.accent_color, fg='white')
            save_button.pack(pady=(20, 10))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to show settings menu: {e}")

    def add_custom_baud_rate(self):
        try:
            baud_rate = self.custom_baud_entry.get()
            if baud_rate.isnumeric():
                baud_rate_int = int(baud_rate)
                if baud_rate_int not in self.baud_rates and baud_rate_int not in self.custom_baud_rates:
                    self.custom_baud_rates.append(baud_rate_int)
                    self.baud_combobox['values'] = self.baud_rates + self.custom_baud_rates
                    messagebox.showinfo("Success", f"Custom baud rate {baud_rate_int} added.")
                else:
                    messagebox.showwarning("Warning", "This baud rate is already in the list.")
            else:
                messagebox.showerror("Error", "Please enter a valid number for baud rate.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to add custom baud rate: {e}")

    def select_bg_color(self):
        try:
            color = colorchooser.askcolor()[1]
            if color:
                self.custom_bg_color = color
                self.set_theme(self.selected_theme.get())
        except Exception as e:
            messagebox.showerror("Error", f"Failed to select background color: {e}")

    def select_fg_color(self):
        try:
            color = colorchooser.askcolor()[1]
            if color:
                self.custom_fg_color = color
                self.set_theme(self.selected_theme.get())
        except Exception as e:
            messagebox.showerror("Error", f"Failed to select foreground color: {e}")

    def select_accent_color(self):
        try:
            color = colorchooser.askcolor()[1]
            if color:
                self.custom_accent_color = color
                self.set_theme(self.selected_theme.get())
        except Exception as e:
            messagebox.showerror("Error", f"Failed to select accent color: {e}")

    def save_settings(self):
        try:
            settings = {
                'theme': self.selected_theme.get(),
                'custom_bg_color': self.custom_bg_color,
                'custom_fg_color': self.custom_fg_color,
                'custom_accent_color': self.custom_accent_color,
                'custom_baud_rates': self.custom_baud_rates  # Save custom baud rates
            }
            with open('settings.json', 'w') as f:
                json.dump(settings, f)
            messagebox.showinfo("Settings", "Settings saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {e}")

    def load_settings(self):
        try:
            if os.path.exists('settings.json'):
                with open('settings.json', 'r') as f:
                    settings = json.load(f)
                    self.selected_theme.set(settings.get('theme', 'dark'))
                    self.custom_bg_color = settings.get('custom_bg_color', 'black')
                    self.custom_fg_color = settings.get('custom_fg_color', 'cyan')
                    self.custom_accent_color = settings.get('custom_accent_color', 'teal')
                    self.custom_baud_rates = settings.get('custom_baud_rates', [])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load settings: {e}")

    def populate_ports(self):
        try:
            ports = serial.tools.list_ports.comports()
            self.port_combobox['values'] = [port.device for port in ports]
        except Exception as e:
            messagebox.showerror("Error", f"Failed to populate ports: {e}")

    def reconnect(self):
        try:
            if self.serial_connection and self.serial_connection.is_open:
                self.serial_connection.close()

            port = self.port_combobox.get()
            baud_rate = self.baud_combobox.get()

            if baud_rate.isnumeric():
                baud_rate = int(baud_rate)
            else:
                messagebox.showerror("Error", "Invalid baud rate selected.")
                return

            if port:
                try:
                    self.serial_connection = serial.Serial(port, baud_rate, timeout=1)
                    self.output_text.insert(tk.END, f"Connected to {port} at {baud_rate} baud.\n")
                    self.is_reading = True
                    self.start_reading()
                except serial.SerialException as e:
                    self.output_text.insert(tk.END, f"Failed to connect: {e}\n")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to reconnect: {e}")

    def start_reading(self):
        try:
            self.read_thread = threading.Thread(target=self.read_serial)
            self.read_thread.start()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start reading: {e}")

    def read_serial(self):
        try:
            while self.is_reading:
                if self.serial_connection.in_waiting:
                    line = self.serial_connection.readline().decode('utf-8', errors='replace')
                    with self.lock:  # Acquire the lock while updating the UI
                        self.output_text.insert(tk.END, line)
                        if self.autoscroll_var.get():
                            self.output_text.see(tk.END)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read from serial: {e}")

    def pause(self):
        try:
            self.is_reading = not self.is_reading
            if self.is_reading:
                self.start_reading()
                self.pause_button.config(text="Pause")
            else:
                self.pause_button.config(text="Resume")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to pause/resume reading: {e}")

    def clear_output(self):
        try:
            self.output_text.delete(1.0, tk.END)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to clear output: {e}")

    def copy_output(self):
        try:
            output = self.output_text.get(1.0, tk.END)
            pyperclip.copy(output)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy output: {e}")

    def clear_placeholder(self, event):
        try:
            if self.input_text.get() == "Type here to send...":
                self.input_text.delete(0, tk.END)
                self.input_text.config(fg='black')
        except Exception as e:
            messagebox.showerror("Error", f"Failed to clear placeholder: {e}")

    def set_placeholder(self, event):
        try:
            if self.input_text.get() == "":
                self.input_text.insert(0, "Type here to send...")
                self.input_text.config(fg='grey')
        except Exception as e:
            messagebox.showerror("Error", f"Failed to set placeholder: {e}")

    def on_selection_change(self, event):
        try:
            selected_port = self.port_combobox.get()
            self.baud_combobox.set(9600)  # Reset to default baud rate
            self.reconnect()  # Call reconnect whenever the port is changed
        except Exception as e:
            messagebox.showerror("Error", f"Failed to handle selection change: {e}")

    def on_baud_rate_change(self, event):
        try:
            self.reconnect()  # Call reconnect whenever the baud rate is changed
        except Exception as e:
            messagebox.showerror("Error", f"Failed to handle baud rate change: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = SerialMonitor(root)
    root.mainloop()
