Dim oShell, sCmd
Dim q : q = Chr(34)
Set oShell = CreateObject("WScript.Shell")
sCmd = "cmd /c " & q & q & "C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe" & q & " -u " & q & "D:\Claude\paos-node\start.py" & q & " >> " & q & "D:\Claude\paos-node\logs\node.log" & q & " 2>&1" & q
oShell.Run sCmd, 0, False
