.venv/Scripts/activate
pyinstaller --noconsole --onefile --icon=icon.ico --hidden-import=rtmidi --hidden-import=mido.backends.rtmidi --hidden-import=pynput.keyboard._win32 main.py