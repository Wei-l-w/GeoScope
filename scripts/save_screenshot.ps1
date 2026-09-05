# 把剪贴板里的截图保存为固定路径的文件，方便在 CLI 里发给 AI
# 用法: Win+Shift+S 截图后，运行本脚本，然后在对话里说"看截图"
param(
    # 默认存到项目根目录（本脚本的上一级），避免硬编码本机路径
    [string]$OutPath = (Join-Path (Split-Path $PSScriptRoot -Parent) "screenshot.png")
)

Add-Type -AssemblyName System.Windows.Forms

$getImage = {
    [System.Windows.Forms.Clipboard]::GetImage()
}

# Clipboard 需要 STA 线程
if ([System.Threading.Thread]::CurrentThread.GetApartmentState() -eq 'STA') {
    $img = & $getImage
} else {
    $ps = [PowerShell]::Create()
    $ps.AddScript('Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::GetImage()') | Out-Null
    $runspace = [RunspaceFactory]::CreateRunspace()
    $runspace.ApartmentState = 'STA'
    $runspace.Open()
    $ps.Runspace = $runspace
    $img = $ps.Invoke() | Select-Object -First 1
    $runspace.Close()
}

if ($null -eq $img) {
    Write-Host "剪贴板里没有图片。请先用 Win+Shift+S 截图，再运行本脚本。" -ForegroundColor Yellow
    exit 1
}

$img.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
Write-Host "已保存: $OutPath" -ForegroundColor Green
Set-Clipboard -Value $OutPath
Write-Host "路径已复制到剪贴板，可直接粘贴到对话里。"
