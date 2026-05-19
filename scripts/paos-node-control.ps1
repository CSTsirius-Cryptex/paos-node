Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$TaskName  = "PAOS-Node"
$VbsPath   = Join-Path $PSScriptRoot "start-node.vbs"
$WorkDir   = Split-Path -Parent $PSScriptRoot
$HealthUrl = "http://localhost:3100/health"
$LogFile   = "$WorkDir\logs\node.log"

$cBg     = [System.Drawing.Color]::FromArgb(24,  24,  27)
$cPanel  = [System.Drawing.Color]::FromArgb(39,  39,  42)
$cLog    = [System.Drawing.Color]::FromArgb(9,   9,   11)
$cText   = [System.Drawing.Color]::FromArgb(228, 228, 231)
$cMuted  = [System.Drawing.Color]::FromArgb(113, 113, 122)
$cGreen  = [System.Drawing.Color]::FromArgb(34,  197, 94)
$cRed    = [System.Drawing.Color]::FromArgb(239, 68,  68)
$cBlue   = [System.Drawing.Color]::FromArgb(59,  130, 246)
$cYellow = [System.Drawing.Color]::FromArgb(234, 179, 8)
$cDark   = [System.Drawing.Color]::FromArgb(63,  63,  70)

# Tray Icon
$bmp   = New-Object System.Drawing.Bitmap(16, 16)
$g     = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$brush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(99, 102, 241))
$g.FillEllipse($brush, 1, 1, 13, 13)
$brush.Dispose(); $g.Dispose()
$trayIcon = [System.Drawing.Icon]::FromHandle($bmp.GetHicon())

$script:notify = New-Object System.Windows.Forms.NotifyIcon
$script:notify.Icon    = $trayIcon
$script:notify.Text    = "PAOS Node"
$script:notify.Visible = $true

$trayMenu    = New-Object System.Windows.Forms.ContextMenuStrip
$menuOpen    = $trayMenu.Items.Add("開啟控制台")
$trayMenu.Items.Add("-") | Out-Null
$menuStart   = $trayMenu.Items.Add("啟動 Node")
$menuRestart = $trayMenu.Items.Add("重啟 Node")
$trayMenu.Items.Add("-") | Out-Null
$menuExit    = $trayMenu.Items.Add("結束程式")
$script:notify.ContextMenuStrip = $trayMenu

# Form
$form = New-Object System.Windows.Forms.Form
$form.Text            = "PAOS Node 控制台"
$form.Size            = New-Object System.Drawing.Size(580, 520)
$form.StartPosition   = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedSingle
$form.MaximizeBox     = $false
$form.BackColor       = $cBg
$form.ForeColor       = $cText
$form.Font            = New-Object System.Drawing.Font("Segoe UI", 10)
$form.ShowInTaskbar   = $false

$lblTitle = New-Object System.Windows.Forms.Label
$lblTitle.Text      = "PAOS Node"
$lblTitle.Font      = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$lblTitle.Location  = New-Object System.Drawing.Point(20, 18)
$lblTitle.Size      = New-Object System.Drawing.Size(300, 32)
$lblTitle.ForeColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
$form.Controls.Add($lblTitle)

$lblSub = New-Object System.Windows.Forms.Label
$lblSub.Text      = "個人記憶節點"
$lblSub.Location  = New-Object System.Drawing.Point(20, 50)
$lblSub.Size      = New-Object System.Drawing.Size(200, 20)
$lblSub.ForeColor = $cMuted
$form.Controls.Add($lblSub)

$panelStatus = New-Object System.Windows.Forms.Panel
$panelStatus.Location  = New-Object System.Drawing.Point(20, 80)
$panelStatus.Size      = New-Object System.Drawing.Size(525, 120)
$panelStatus.BackColor = $cPanel
$form.Controls.Add($panelStatus)

function Add-StatusRow($label, $y) {  # label, y-offset
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text      = $label
    $lbl.Location  = New-Object System.Drawing.Point(15, $y)
    $lbl.Size      = New-Object System.Drawing.Size(130, 26)
    $lbl.ForeColor = $cMuted
    $panelStatus.Controls.Add($lbl)
    $val = New-Object System.Windows.Forms.Label
    $val.Text      = "checking..."
    $val.Location  = New-Object System.Drawing.Point(150, $y)
    $val.Size      = New-Object System.Drawing.Size(360, 26)
    $val.ForeColor = $cMuted
    $panelStatus.Controls.Add($val)
    return $val
}

$script:lblTask    = Add-StatusRow "背景工作排程：" 14
$script:lblServer  = Add-StatusRow "Node (port 3100)：" 50
$script:lblTunnel  = Add-StatusRow "Tunnel URL：" 86

function New-Btn($text, $x, $bg) {
    $b = New-Object System.Windows.Forms.Button
    $b.Text      = $text
    $b.Location  = New-Object System.Drawing.Point($x, 215)
    $b.Size      = New-Object System.Drawing.Size(105, 38)
    $b.BackColor = $bg
    $b.ForeColor = [System.Drawing.Color]::White
    $b.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $b.FlatAppearance.BorderSize = 0
    $b.Font      = New-Object System.Drawing.Font("Segoe UI", 10)
    $b.Cursor    = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($b)
    return $b
}

$btnRefresh = New-Btn "重新整理"  20  $cDark
$btnStart   = New-Btn "啟動"     135 $cGreen
$btnRestart = New-Btn "重啟"     250 $cBlue
$btnRepair  = New-Btn "修復"     365 $cYellow

$lblLog = New-Object System.Windows.Forms.Label
$lblLog.Text      = "執行記錄"
$lblLog.Location  = New-Object System.Drawing.Point(20, 265)
$lblLog.Size      = New-Object System.Drawing.Size(100, 20)
$lblLog.ForeColor = $cMuted
$form.Controls.Add($lblLog)

$script:logBox = New-Object System.Windows.Forms.RichTextBox
$script:logBox.Location    = New-Object System.Drawing.Point(20, 287)
$script:logBox.Size        = New-Object System.Drawing.Size(525, 160)
$script:logBox.BackColor   = $cLog
$script:logBox.ForeColor   = $cMuted
$script:logBox.Font        = New-Object System.Drawing.Font("Consolas", 9)
$script:logBox.ReadOnly    = $true
$script:logBox.ScrollBars  = [System.Windows.Forms.RichTextBoxScrollBars]::Vertical
$script:logBox.BorderStyle = [System.Windows.Forms.BorderStyle]::None
$form.Controls.Add($script:logBox)

function Write-Log($msg, $type = "Normal") {
    $time = Get-Date -Format "HH:mm:ss"
    $script:logBox.SelectionStart  = $script:logBox.TextLength
    $script:logBox.SelectionLength = 0
    $script:logBox.SelectionColor  = if ($type -eq "OK") { $cGreen } elseif ($type -eq "Error") { $cRed } elseif ($type -eq "Warn") { $cYellow } else { $cMuted }
    $script:logBox.AppendText("[$time] $msg`n")
    $script:logBox.ScrollToCaret()
    $form.Refresh()
}

function Get-TaskState {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $t) { return "NotFound" }
    return $t.State.ToString()
}

function Get-ServerHealth {
    try {
        $r = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { return "OK" }
    } catch {}
    return "Error"
}

function Get-TunnelUrl {
    if (-not (Test-Path $LogFile)) { return "" }
    $match = Get-Content $LogFile -Tail 200 | Select-String "trycloudflare\.com" | Select-Object -Last 1
    if ($match) {
        $m = [regex]::Match($match.Line, "https://[a-z0-9-]+\.trycloudflare\.com")
        if ($m.Success) { return $m.Value }
    }
    return ""
}

function Update-Status {
    $ts = Get-TaskState
    switch ($ts) {
        "NotFound" { $script:lblTask.Text = "● 不存在"; $script:lblTask.ForeColor = $cRed }
        "Ready"    { $script:lblTask.Text = "● 已停止"; $script:lblTask.ForeColor = $cYellow }
        "Running"  { $script:lblTask.Text = "● 執行中"; $script:lblTask.ForeColor = $cGreen }
        default    { $script:lblTask.Text = "● $ts"; $script:lblTask.ForeColor = $cMuted }
    }
    if ((Get-ServerHealth) -eq "OK") {
        $script:lblServer.Text = "● 正常運作"; $script:lblServer.ForeColor = $cGreen
    } else {
        $script:lblServer.Text = "● 無回應"; $script:lblServer.ForeColor = $cRed
    }
    $url = Get-TunnelUrl
    if ($url) {
        $script:lblTunnel.Text = $url; $script:lblTunnel.ForeColor = $cGreen
    } else {
        $script:lblTunnel.Text = "未偵測到"; $script:lblTunnel.ForeColor = $cMuted
    }
}

function Ensure-TaskExists {
    if ((Get-TaskState) -ne "NotFound") { return }
    Write-Log "Task not found, creating..." "Warn"
    $action   = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$VbsPath`"" -WorkingDirectory $WorkDir
    $trigger  = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Hours 0)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
    Write-Log "Task created" "OK"
}

function Kill-Port3100 {
    $pids = Get-NetTCPConnection -LocalPort 3100 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($p in $pids) {
        if ($p -gt 0) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue; Write-Log "Killed PID $p" }
    }
}

function Show-Form {
    $form.Show()
    $form.WindowState = [System.Windows.Forms.FormWindowState]::Normal
    $form.Activate()
}

$btnRefresh.Add_Click({
    Write-Log "更新狀態中..."
    Update-Status
    Write-Log "完成" "OK"
})

$btnStart.Add_Click({
    Write-Log "啟動 Node..."
    Ensure-TaskExists
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 5
    Update-Status
    if ((Get-ServerHealth) -eq "OK") { Write-Log "Node 啟動成功" "OK" } else { Write-Log "健康檢查失敗" "Error" }
})

$btnRestart.Add_Click({
    Write-Log "重啟 Node..."
    Ensure-TaskExists
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Kill-Port3100
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 5
    Update-Status
    if ((Get-ServerHealth) -eq "OK") { Write-Log "重啟完成" "OK" } else { Write-Log "重啟失敗" "Error" }
})

$btnRepair.Add_Click({
    Write-Log "=== 開始修復 ===" "Warn"
    Ensure-TaskExists
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Kill-Port3100
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 6
    Update-Status
    if ((Get-ServerHealth) -eq "OK") { Write-Log "=== 修復完成 ===" "OK" } else { Write-Log "修復失敗，請查看 logs\node.log" "Error" }
})

$menuOpen.Add_Click({ Show-Form })

$menuStart.Add_Click({
    Ensure-TaskExists
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 4
    if ((Get-ServerHealth) -eq "OK") {
        $script:notify.ShowBalloonTip(3000, "PAOS Node", "Node 啟動成功", [System.Windows.Forms.ToolTipIcon]::Info)
    } else {
        $script:notify.ShowBalloonTip(3000, "PAOS Node", "健康檢查失敗", [System.Windows.Forms.ToolTipIcon]::Warning)
    }
})

$menuRestart.Add_Click({
    Ensure-TaskExists
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Kill-Port3100
    Start-Sleep -Seconds 1
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 4
    if ((Get-ServerHealth) -eq "OK") {
        $script:notify.ShowBalloonTip(3000, "PAOS Node", "重啟完成", [System.Windows.Forms.ToolTipIcon]::Info)
    } else {
        $script:notify.ShowBalloonTip(3000, "PAOS Node", "重啟失敗", [System.Windows.Forms.ToolTipIcon]::Warning)
    }
})

$menuExit.Add_Click({
    $script:notify.Visible = $false
    $script:notify.Dispose()
    [System.Windows.Forms.Application]::Exit()
})

$script:notify.Add_DoubleClick({ Show-Form })

$form.Add_FormClosing({
    param($s, $e)
    if ($e.CloseReason -eq [System.Windows.Forms.CloseReason]::UserClosing) {
        $e.Cancel = $true
        $form.Hide()
        $script:notify.ShowBalloonTip(2000, "PAOS Node", "程式仍在背景執行，右鍵圖示可操作", [System.Windows.Forms.ToolTipIcon]::Info)
    }
})

$form.Add_Shown({
    Write-Log "PAOS Node 控制台啟動"
    Update-Status
    if (Test-Path $LogFile) {
        $lines = Get-Content $LogFile -Tail 20
        foreach ($line in $lines) { Write-Log $line }
    }
})

# 直接進 message loop，不顯示視窗（雙擊系統匣圖示才開）
$script:notify.ShowBalloonTip(2000, "PAOS Node", "節點控制台已在背景執行", [System.Windows.Forms.ToolTipIcon]::Info)
[System.Windows.Forms.Application]::Run()
