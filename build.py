
import subprocess  # Executes external commands and programs.
import sys  # Provides access to the current Python interpreter.
from pathlib import Path  # Handles file and directory paths.

# 1. Make sure your virtual environment is correctly configured in PyCharm.
#    If necessary, recreate .venv and configure the interpreter manually.

# 2. Install PyInstaller in your virtual environment:
#    pip install pyinstaller

# 3. Navigate to your project directory:
#    cd "C:\Your\Project\Directory"

# 4. Create a standalone executable with icon.
try:  # Start error handling.
    subprocess.run(  # Execute PyInstaller and wait until it finishes.
        [  # List of command arguments.
            sys.executable, "-m", "PyInstaller",  # Run PyInstaller using the current Python interpreter.
            "--onefile",  # Create a single executable (.exe).
            "--windowed",  # Hide the console window for GUI applications.
            "--name", "Structify",  # Set the executable name to Structify.exe.
            "--icon=..\\assets\\media\\icons\\icon.ico",  # Set the icon; \\ represents a Windows path separator.
            "--distpath", "publish",  # Save the executable in the publish folder.
            "--workpath", "publish\\build",  # Store temporary build files in publish/build.
            "--specpath", "publish",  # Save the PyInstaller .spec configuration file in publish.
            "main\\main.py",  # Entry point of the application.
        ],  # End of command arguments.
        cwd=Path(__file__).resolve().parent,  # Execute from the folder containing this script.
        check=True,  # Raise an exception if PyInstaller returns a nonzero exit code.
    )  # Wait for PyInstaller to finish.

    # 5. Remove unnecessary files and folders (keep only .exe files).
    publish = Path(__file__).resolve().parent / "publish"  # Absolute path to the publish folder.

    import shutil  # Provides functions for removing directories.

    for item in publish.iterdir():  # Iterate through each item in the publish folder.
        if item.is_file() and item.suffix.lower() == ".exe":  # Check whether the item is an .exe file.
            continue  # Keep the .exe file and move to the next item.

        if item.is_dir():  # Check whether the item is a directory.
            shutil.rmtree(item)  # Delete the directory and all its contents.
        else:  # Otherwise, the item is treated as a file.
            item.unlink()  # Delete the file.

    print("\nSUCCESS: Structify build and cleanup completed!")  # Display success message.

except Exception as e:  # Catch an error and store it in variable e.
    print(f"\nFAILED: {e}")  # Display the error message.
    sys.exit(1)  # Exit the script with error code 1.
