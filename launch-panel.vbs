Dim oShell, pythonw, nodeDir, q
Set oShell = WScript.CreateObject("WScript.Shell")

pythonw = "C:\Users\User\AppData\Local\Programs\Python\Python312\pythonw.exe"
nodeDir = "D:\Claude\paos-node"
q       = Chr(34)

' Step 1: Check if Node is already running on port 3100
Dim nodeRunning, oExec, sOut
nodeRunning = False
On Error Resume Next
Set oExec = oShell.Exec("cmd /c netstat -ano | findstr :3100")
If Err.Number = 0 Then
    sOut = oExec.StdOut.ReadAll()
    If InStr(sOut, "LISTENING") > 0 Or InStr(sOut, "127.0.0.1:3100") > 0 Then
        nodeRunning = True
    End If
End If
On Error GoTo 0

' Step 2: Start Node if not running (direct pythonw, bypasses schtasks PATH issue)
If Not nodeRunning Then
    oShell.CurrentDirectory = nodeDir
    oShell.Run q & pythonw & q & " " & q & nodeDir & "\start.py" & q, 0, False
End If

' Step 3: Launch panel (single-instance + waits up to 90s for Node)
oShell.Run q & pythonw & q & " " & q & nodeDir & "\panel_app.py" & q, 0, False
