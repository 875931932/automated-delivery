Option Explicit
Dim shell, files, root, interpreter, candidates, candidate, environment
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
Set environment = shell.Environment("PROCESS")
root = files.GetParentFolderName(WScript.ScriptFullName)

candidates = Array( _
    environment("AUTODELIVER_PYTHONW"), _
    root & "\.venv\Scripts\pythonw.exe", _
    "D:\ProgramData\miniconda3\envs\autodeliver\pythonw.exe", _
    environment("USERPROFILE") & "\miniconda3\envs\autodeliver\pythonw.exe" _
)
interpreter = ""
For Each candidate In candidates
    If Len(candidate) > 0 Then
        If files.FileExists(candidate) Then
            interpreter = candidate
            Exit For
        End If
    End If
Next
If Len(interpreter) = 0 Then
    MsgBox "Python environment not found. Set AUTODELIVER_PYTHONW to the project's pythonw.exe.", 16, "AutoDeliver"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
shell.Run Chr(34) & interpreter & Chr(34) & " " & Chr(34) & root & "\launch_panel.pyw" & Chr(34), 1, False
