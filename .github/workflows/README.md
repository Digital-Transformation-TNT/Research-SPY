# CI/CD — Research-SPY

Hai workflow, tách bạch: **CI** kiểm mọi push/PR; **CD** deploy vào VPS khi bạn bấm.

## `ci.yml` — chạy tự động, KHÔNG cần cấu hình gì

Chạy trên mỗi push (`Titus`, `main`) và mọi pull request. Bốn job song song:

| Job | Làm gì | Chặn merge? |
|---|---|---|
| **backend** | `pip install` → `compileall` → `import app.main` (bắt lỗi cú pháp + import-graph) | ✅ có |
| **frontend** | `npm ci` → `typecheck` → `next build` | ✅ có |
| **extension** | `node extension/tabs.test.js` (chrome API giả, không cần Chrome) | ✅ có |
| **security-audit** | `npm audit` + `pip-audit` | ❌ tư vấn |

Cố ý **không** chạy `scripts/smoke/*` trong CI: chúng cần Chrome thật + đăng nhập Google/sàn
+ mạng ngoài, nên sẽ đỏ vì môi trường chứ không phải vì code. Smoke vẫn chạy tay khi cần
(`python scripts/smoke/ads.py`, …). Nguyên tắc: **mỗi lần CI đỏ là một lỗi thật.**

Muốn bắt buộc CI xanh mới merge được: **Settings → Branches → Add rule** cho `main` (và
`Titus` nếu muốn), tick *Require status checks* rồi chọn `backend`, `frontend`, `extension`.

## `deploy.yml` — deploy vào VPS, BẤM TAY

Deploy vào VPS production (Windows) là việc hướng-ra-ngoài, khó lùi, nên **không** auto theo
push. Chạy: **Actions → Deploy to VPS → Run workflow** (chọn nhánh/SHA nếu muốn).

Job chạy `deploy/redeploy.ps1` NGAY TRÊN VPS qua một **self-hosted runner**, làm: `git fetch`
→ `reset --hard` → cài lại phụ thuộc *nếu* `requirements.txt`/`package-lock.json` đổi → `next
build` *nếu* frontend đổi → `Restart-Service` đúng service cần → kiểm `/api/health`.

### Cài một lần trên VPS

1. **Biến `C:\ResearchSpy` thành bản clone git** (nếu đang là thư mục giải nén .zip):
   ```powershell
   # sao lưu .env.local, models/ trước nếu cần
   git clone https://github.com/Digital-Transformation-TNT/Research-SPY.git C:\ResearchSpy
   cd C:\ResearchSpy\deploy; .\vps-setup.ps1     # dựng service lần đầu
   ```
2. **Đăng ký self-hosted runner** (GitHub → Settings → Actions → Runners → New self-hosted
   runner → Windows). Chạy các lệnh nó đưa, rồi cài runner như một service để tự chạy nền:
   ```powershell
   ./config.cmd --url https://github.com/Digital-Transformation-TNT/Research-SPY --token <TOKEN> --labels self-hosted,windows
   ./svc.cmd install ; ./svc.cmd start
   ```
   Runner **phải chạy bằng tài khoản có quyền `Restart-Service`** cho 2 service (Administrator).

Không cần SSH key hay secret nào: job chạy ngay trên máy đích.

### Muốn bật auto-deploy (không khuyến nghị vội)

Thêm vào đầu `deploy.yml`:
```yaml
on:
  workflow_dispatch: { }
  workflow_run:
    workflows: [CI]
    types: [completed]
    branches: [Titus]
```
và ở job thêm điều kiện `if: github.event.workflow_run.conclusion == 'success'`. Nên bật
kèm **Environment `production` + Required reviewers** (Settings → Environments) để mỗi lần
deploy vẫn có một người bấm duyệt.
