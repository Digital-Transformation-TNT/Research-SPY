<#
  Research-SPY — dựng server trên VPS Windows.

  Chạy TRÊN VPS (qua RDP), trong PowerShell "Run as Administrator":
      cd C:\ResearchSpy\deploy
      Set-ExecutionPolicy -Scope Process Bypass -Force
      .\vps-setup.ps1

  Việc script làm, theo thứ tự:
    1. Dò Python + Node trên máy.
    2. Cài thư viện backend (+ playwright chromium) và frontend, rồi `next build` (bản production).
    3. Mở cổng 3000 trên tường lửa Windows.
    4. Tải nssm, tạo 2 Windows Service tự bật khi máy khởi động:
         ResearchSpyBackend   -> uvicorn 127.0.0.1:8000  (kín trong máy)
         ResearchSpyFrontend  -> next start 0.0.0.0:3000  (mở ra ngoài)

  Chạy lại nhiều lần được: service cũ bị gỡ rồi tạo lại, không nhân đôi.
#>

param(
  # Thư mục gốc project trên VPS (chứa backend\ và frontend\).
  [string]$Root = "C:\ResearchSpy",
  # Cổng công khai cho frontend.
  [int]$Port = 3000
)

$ErrorActionPreference = "Stop"
function Info($m){ Write-Host "  $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "  OK  $m" -ForegroundColor Green }
function Die($m){ Write-Host "  LỖI $m" -ForegroundColor Red; exit 1 }

# --- Quyền admin (cần cho firewall + tạo service) ---------------------------
$admin = ([Security.Principal.WindowsPrincipal] `
  [Security.Principal.WindowsIdentity]::GetCurrent()
  ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Die "Hãy mở PowerShell bằng 'Run as Administrator' rồi chạy lại." }

$backend  = Join-Path $Root "backend"
$frontend = Join-Path $Root "frontend"
if (-not (Test-Path $backend))  { Die "Không thấy $backend — sửa -Root cho đúng nơi bạn giải nén code." }
if (-not (Test-Path $frontend)) { Die "Không thấy $frontend." }

# --- Dò Python + Node -------------------------------------------------------
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { Die "Chưa cài Python (nhớ tick 'Add python.exe to PATH' lúc cài)." }
Ok "Python: $py"

$node = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $node) { Die "Chưa cài Node.js." }
$npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npm) { $npm = (Get-Command npm -ErrorAction SilentlyContinue).Source }
Ok "Node: $node"

# --- 1) Backend deps --------------------------------------------------------
Info "Cài thư viện backend..."
Push-Location $backend
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Pop-Location; Die "pip install thất bại." }
& $py -m playwright install chromium
Pop-Location
Ok "Backend sẵn sàng."

# --- 2) Frontend build (production) ----------------------------------------
Info "Cài & build frontend (production)..."
Push-Location $frontend
& $npm install
if ($LASTEXITCODE -ne 0) { Pop-Location; Die "npm install thất bại." }
& $npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; Die "next build thất bại — xem log phía trên." }
Pop-Location
Ok "Frontend build xong."

# --- 3) Firewall ------------------------------------------------------------
Info "Mở cổng $Port trên tường lửa Windows..."
$ruleName = "ResearchSpy $Port"
Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
Ok "Đã mở cổng $Port. (Nhớ kiểm tra firewall ở panel vpssieutoc nữa!)"

# --- 4) nssm ----------------------------------------------------------------
$nssm = (Get-Command nssm -ErrorAction SilentlyContinue).Source
if (-not $nssm) { $nssm = Join-Path $PSScriptRoot "nssm.exe" }
if (-not (Test-Path $nssm)) {
  Info "Tải nssm..."
  $zip = Join-Path $env:TEMP "nssm.zip"
  $dst = Join-Path $env:TEMP "nssm-extract"
  Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $zip
  if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
  Expand-Archive $zip $dst -Force
  $arch = if ([Environment]::Is64BitOperatingSystem) { "win64" } else { "win32" }
  Copy-Item (Join-Path $dst "nssm-2.24\$arch\nssm.exe") $nssm -Force
}
Ok "nssm: $nssm"

function Reinstall-Service($name, $app, $args, $dir) {
  & $nssm stop    $name 2>$null | Out-Null
  & $nssm remove  $name confirm 2>$null | Out-Null
  & $nssm install $name $app $args
  & $nssm set $name AppDirectory $dir
  & $nssm set $name Start SERVICE_AUTO_START
  & $nssm set $name AppStdout (Join-Path $dir "service.out.log")
  & $nssm set $name AppStderr (Join-Path $dir "service.err.log")
}

Info "Tạo service backend (uvicorn 127.0.0.1:8000)..."
# KHÔNG dùng --reload/--workers: trên Windows nó làm chết Playwright (Google Trends + Quảng cáo).
Reinstall-Service "ResearchSpyBackend" $py "-m uvicorn app.main:app --host 127.0.0.1 --port 8000" $backend

Info "Tạo service frontend (next start 0.0.0.0:$Port)..."
$nextBin = Join-Path $frontend "node_modules\next\dist\bin\next"
Reinstall-Service "ResearchSpyFrontend" $node "`"$nextBin`" start -H 0.0.0.0 -p $Port" $frontend

& $nssm start ResearchSpyBackend
Start-Sleep -Seconds 2
& $nssm start ResearchSpyFrontend

Write-Host ""
Ok "XONG. Hai service đang chạy và sẽ tự bật lại khi VPS khởi động."
Write-Host "  Truy cập:  http://157.66.101.73:$Port" -ForegroundColor Yellow
Write-Host "  Log:       $backend\service.err.log  và  $frontend\service.err.log"
Write-Host "  Quản lý:   nssm restart ResearchSpyFrontend  |  Get-Service ResearchSpy*"
