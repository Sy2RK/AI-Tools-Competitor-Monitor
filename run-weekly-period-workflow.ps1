# PowerShell脚本：每周定时运行时间段工作流
# 用于Windows任务计划程序
# 功能：生成上周的竞品周报

# 切换到脚本所在目录
Set-Location $PSScriptRoot

# 设置 Python 路径，确保能找到项目根目录的模块（如 env_loader）
$env:PYTHONPATH = "$PSScriptRoot;$env:PYTHONPATH"

# 激活虚拟环境（如果使用虚拟环境）
# 如果使用虚拟环境，取消下面这行的注释并修改路径
# & .\.venv\Scripts\Activate.ps1

# 日志文件路径
$logDir = Join-Path $PSScriptRoot "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

# 计算上周的日期范围（周一到周日）
$today = Get-Date
$daysFromMonday = [int]$today.DayOfWeek
if ($daysFromMonday -eq 0) { $daysFromMonday = 7 }  # 周日转换为7

# 上周的结束日期（上周日）
$lastWeekEnd = $today.AddDays(-$daysFromMonday)
# 上周的开始日期（上周一）
$lastWeekStart = $lastWeekEnd.AddDays(-6)

# 格式化日期为 yyyy-MM-dd
$startDate = $lastWeekStart.ToString("yyyy-MM-dd")
$endDate = $lastWeekEnd.ToString("yyyy-MM-dd")

$logFile = Join-Path $logDir "weekly_period_workflow_$(Get-Date -Format 'yyyy-MM-dd').log"

# 记录开始时间
$startTime = Get-Date

Write-Output "========================================" | Tee-Object -FilePath $logFile -Append
Write-Output "开始执行每周时间段工作流任务" | Tee-Object -FilePath $logFile -Append
Write-Output "目标: 生成上周的竞品周报" | Tee-Object -FilePath $logFile -Append
Write-Output "时间段: $startDate 至 $endDate" | Tee-Object -FilePath $logFile -Append
Write-Output "时间: $startTime" | Tee-Object -FilePath $logFile -Append
Write-Output "========================================" | Tee-Object -FilePath $logFile -Append
Write-Output "" | Tee-Object -FilePath $logFile -Append

try {
    # 运行时间段工作流
    # 使用新的项目结构路径
    # --skip-send 参数可以取消注释，如果只想生成报告文件而不发送
    & python workflows/period_workflow.py --start-date $startDate --end-date $endDate 2>&1 | Tee-Object -FilePath $logFile -Append
    
    # 如果不想发送到飞书，只生成报告文件，使用下面的命令：
    # & python workflows/period_workflow.py --start-date $startDate --end-date $endDate --skip-send 2>&1 | Tee-Object -FilePath $logFile -Append
    
    $exitCode = $LASTEXITCODE
    
    $endTime = Get-Date
    $duration = $endTime - $startTime
    
    Write-Output "" | Tee-Object -FilePath $logFile -Append
    Write-Output "========================================" | Tee-Object -FilePath $logFile -Append
    if ($exitCode -eq 0) {
        Write-Output "✅ 周报生成任务执行成功" | Tee-Object -FilePath $logFile -Append
        Write-Output "📊 周报时间段: $startDate 至 $endDate" | Tee-Object -FilePath $logFile -Append
    } else {
        Write-Output "❌ 周报生成任务执行失败，错误码: $exitCode" | Tee-Object -FilePath $logFile -Append
    }
    Write-Output "执行时长: $($duration.TotalSeconds) 秒" | Tee-Object -FilePath $logFile -Append
    Write-Output "结束时间: $endTime" | Tee-Object -FilePath $logFile -Append
    Write-Output "========================================" | Tee-Object -FilePath $logFile -Append
    
    exit $exitCode
} catch {
    $errorMsg = $_.Exception.Message
    Write-Output "❌ 执行过程中发生异常: $errorMsg" | Tee-Object -FilePath $logFile -Append
    Write-Output "异常详情: $_" | Tee-Object -FilePath $logFile -Append
    exit 1
}
