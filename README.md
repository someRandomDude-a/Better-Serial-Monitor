# Serial Monitor

**Features:**
1) Dropdown Menu to select port and baud rate
2) NL and CR options to send messages
3) Reconnect button to restart the Serial monitor thread
4) Pause/Resume button to allow easy programing, especially for arduino and such
5) Clear button to clear the output box
6) Copy button to copy the entire output
7) Auto Scroll toggle
8) Setting menu, Allows changing between two default themes,
9) dark and light + allows setup of a custom theme. This is saved in the settings.json file
10) Allows Addition of custom baud rates. This is NOT saved between instances


 **You Must Whitelist The executable in antivrus software**
 
 This Project does seem to get flagged constantly by antivirus software,
 This Project DOES NOT have maleware, you can check the source-code yourself
 and build it locally.

 # To Build this project yourself,
 **Prerequisites:**
1) Have Python installed
2) Have "pyserial and "pyperclip" installed (included in requirements.txt)
3) Package using your preffered software (I use pyinstaller)

 **Example Commands:** 
1. "pip install pyinstaller"
2. "cd path/to/your/local/install/Serial_Monitor.py"
3. "pip install -r requirements.txt"
4. "pyinstaller --onefile Serial_Monitor.py"
