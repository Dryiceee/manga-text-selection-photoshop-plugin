Option Explicit
Dim files, shell, root, python, launcher, command
Set files = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = files.GetParentFolderName(WScript.ScriptFullName)
python = files.BuildPath(root, ".venv\Scripts\pythonw.exe")
launcher = files.BuildPath(root, "launch.py")
If Not files.FileExists(python) Or Not files.FileExists(launcher) Then WScript.Quit 1
command = Chr(34) & python & Chr(34) & " " & Chr(34) & launcher & Chr(34) & " --no-browser --photoshop"
shell.Run command, 0, False
