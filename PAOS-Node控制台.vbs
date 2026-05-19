Dim scriptDir
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

Dim args
args = "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File """ & scriptDir & "\scripts\paos-node-control.ps1"""

CreateObject("Shell.Application").ShellExecute "powershell.exe", args, "", "runas", 0
