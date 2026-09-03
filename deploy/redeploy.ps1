<#
  Research-SPY — cập nhật lại server đã dựng (KHÔNG provision lại).

  Khác với vps-setup.ps1 (dựng máy lần đầu: cài Chrome/nssm, mở firewall, tạo service),
  script này chỉ CẬP NHẬT một máy đã chạy: kéo code mới, cài phụ thuộc NẾU đổi, build lại
  frontend NẾU đổi, rồi restart đúng service cần restart.

  Được GitHub Actions gọi (.github/workflows/deploy.yml) trên self-hosted runner Windows,
  nhưng chạy tay cũng được — qua RDP, PowerShell "Run as Administrator":

      cd C:\ResearchSpy\deploy
      .\redeploy.ps1 -Branch Titus

  ĐIỀU KIỆN: C:\ResearchSpy phải là một BẢN CLONE GIT (không phải thư mục giải nén .zip).
  Lần đầu: `git clone <repo> C:\ResearchSpy` rồi chạy vps-setup.ps1 một lần.
#>

param(
  [string]$Root   = "C:\ResearchSpy",
  [string]$Branch = "Titus",
  # SHA cụ thể để deploy (Actions truyền vào). Trống = đỉnh nhánh $Branch.
  [string]$Ref    = "",
  [string]$BackendService  = "ResearchSpyBackend",
  [string]$FrontendService = "ResearchSpyFrontend",
  [int]$FrontendPort = 3000
)

$ErrorActionPreference = "Stop"
function Info($m){ Write-Host "  $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "  OK  $m" -ForegroundColor Green }
function Warn($m){ Write-Host "  !   $m" -ForegroundColor Yellow }
function Die($m){ Write-Host "  LỖI $m" -ForegroundColor Red; exit 1 }

$backend  = Join-Path $Root "backend"
$frontend = Join-Path $Root "frontend"
if (-not (Test-Path (Join-Path $Root ".git"))) { Die "$Root không phải bản clone git. Xem ghi chú đầu file." }
if (-not (Test-Path $backend))  { Die "Không thấy $backend." }
if (-not (Test-Path $frontend)) { Die "Không thấy $frontend." }

Push-Location $Root
try {
  # --- 1) Kéo code mới -------------------------------------------------------
  $oldSha = (git rev-parse HEAD).Trim()
  Info "Đang ở $oldSha — fetch origin…"
  git fetch --prune origin
  if ($LASTEXITCODE -ne 0) { Die "git fetch thất bại." }

  if ([string]::IsNullOrWhiteSpace($Ref)) { $target = "origin/$Branch" } else { $target = $Ref }
  # reset --hard: máy deploy KHÔNG được có sửa đổi cục bộ; đồng bộ đúng bằng remote.
  git reset --hard $target
  if ($LASTEXITCODE -ne 0) { Die "git reset --hard $target thất bại." }
  $newSha = (git rev-parse HEAD).Trim()

  if ($oldSha -eq $newSha) { Ok "Đã ở đúng $newSha — không có gì mới. Vẫn restart cho chắc." }
  else { Ok "Cập nhật $oldSha -> $newSha" }

  # --- 2) Chỉ làm việc nặng khi phần liên quan thực sự đổi -------------------
  if ($oldSha -eq $newSha) {
    $changed = @()
  } else {
    $changed = (git diff --name-only $oldSha $newSha) -split "`n" | Where-Object { $_ }
  }
  $beChanged = $changed | Where-Object { $_ -like "backend/*" }
  $feChanged = $changed | Where-Object { $_ -like "frontend/*" }
  $reqChanged = $changed | Where-Object { $_ -eq "backend/requirements.txt" }
  $lockChanged = $changed | Where-Object { $_ -eq "frontend/package-lock.json" }

  # --- 3) Backend: cài lại phụ thuộc chỉ khi requirements đổi ---------------
  if ($reqChanged) {
    Info "requirements.txt đổi — pip install…"
    python -m pip install -r (Join-Path $backend "requirements.txt")
    if ($LASTEXITCODE -ne 0) { Die "pip install thất bại." }
    Ok "Backend deps xong."
  } else { Info "requirements.txt không đổi — bỏ qua pip." }

  # --- 4) Frontend: build lại chỉ khi có file frontend đổi ------------------
  if ($feChanged -or $oldSha -eq $newSha) {
    Push-Location $frontend
    try {
      if ($lockChanged) { Info "package-lock đổi — npm ci…"; npm ci }
      else { Info "lock không đổi — npm install (nhanh)…"; npm install --no-audit --no-fund }
      if ($LASTEXITCODE -ne 0) { Die "npm cài phụ thuộc thất bại." }
      Info "next build…"
      npm run build
      if ($LASTEXITCODE -ne 0) { Die "next build thất bại — KHÔNG restart để giữ bản đang chạy." }
      Ok "Frontend build xong."
    } finally { Pop-Location }
  } else { Info "Không có file frontend đổi — bỏ qua build." }

  # --- 5) Restart service ----------------------------------------------------
  # Backend giữ trạng thái trong RAM (cache + phiên trình duyệt) nên restart là cách nạp code
  # mới đúng đắn. Chỉ restart cái nào có phần đổi; nếu không rõ thì restart cả hai.
  function Restart-Svc($name) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $svc) { Warn "Không thấy service '$name' — bỏ qua (đã chạy vps-setup.ps1 chưa?)"; return }
    Info "Restart $name…"
    Restart-Service -Name $name -Force
    Ok "$name đã restart."
  }
  if ($beChanged -or $oldSha -eq $newSha) { Restart-Svc $BackendService }  else { Info "Backend không đổi — không restart." }
  if ($feChanged -or $oldSha -eq $newSha) { Restart-Svc $FrontendService } else { Info "Frontend không đổi — không restart." }

  # --- 6) Kiểm tra sống ------------------------------------------------------
  Start-Sleep -Seconds 4
  try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 15
    if ($h.ok) { Ok "Backend /api/health: ok" } else { Warn "Backend trả lời nhưng ok=$($h.ok)" }
  } catch { Die "Backend không phản hồi /api/health sau restart: $($_.Exception.Message)" }
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$FrontendPort/" -TimeoutSec 20 -UseBasicParsing
    Ok "Frontend HTTP $($r.StatusCode)"
  } catch { Warn "Frontend chưa phản hồi (có thể còn đang khởi động): $($_.Exception.Message)" }

  Ok "Deploy xong: $newSha"
} finally {
  Pop-Location
}
