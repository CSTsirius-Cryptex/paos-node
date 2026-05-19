# PAOS Node 背景服務安裝腳本
# 以「系統管理員」身份執行 PowerShell，然後跑這個腳本

$TaskName   = "PAOS-Node"
$PythonExe  = "C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe"
$StartScript = "D:\Claude\paos-node\start.py"
$WorkDir    = "D:\Claude\paos-node"
$LogFile    = "D:\Claude\paos-node\logs\service.log"

# 建立 logs 資料夾
New-Item -ItemType Directory -Force -Path "$WorkDir\logs" | Out-Null

# 移除舊的同名工作（若存在）
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# 定義動作：執行 python start.py，輸出導到 log
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "-u `"$StartScript`" >> `"$LogFile`" 2>&1" `
    -WorkingDirectory $WorkDir

# 觸發器：登入時立即執行
$Trigger = New-ScheduledTaskTrigger -AtLogOn

# 設定：若失敗 1 分鐘後重試，最多重試 99 次；不因閒置停止
$Settings = New-ScheduledTaskSettingsSet `
    -RestartCount 99 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StopIfGoingOnBatteries $false `
    -DisallowStartIfOnBatteries $false

# 以目前登入使用者身份執行（有桌面存取權，適合 cloudflared）
$Principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "PAOS Node + cloudflared tunnel，開機自動啟動" | Out-Null

Write-Host "[OK] 工作排程已建立：$TaskName"
Write-Host "     立刻啟動..."

# 馬上啟動（不用等重開機）
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 5

$State = (Get-ScheduledTask -TaskName $TaskName).State
Write-Host "     目前狀態：$State"
Write-Host ""
Write-Host "管理指令："
Write-Host "  停止：Stop-ScheduledTask  -TaskName '$TaskName'"
Write-Host "  啟動：Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  移除：Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
Write-Host "  Log ：Get-Content '$LogFile' -Tail 50"
