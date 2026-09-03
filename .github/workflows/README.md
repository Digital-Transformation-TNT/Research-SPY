# CI/CD — Research-SPY

Hai workflow: **CI** kiểm mọi push/PR và **auto-deploy** vào VPS khi push Titus + CI xanh;
**deploy.yml** là đường deploy BẤM TAY (deploy một SHA cụ thể / deploy lại).

## `ci.yml` — chạy tự động, KHÔNG cần cấu hình gì

Chạy trên mỗi push (`Titus`, `main`) và mọi pull request. Bốn job song song:

| Job | Làm gì | Chặn merge? |
|---|---|---|
| **backend** | `pip install` → `compileall` → `import app.main` (bắt lỗi cú pháp + import-graph) | ✅ có |
| **frontend** | `npm ci` → `typecheck` → `next build` | ✅ có |
| **extension** | `node extension/tabs.test.js` (chrome API giả, không cần Chrome) | ✅ có |
| **security-audit** | `npm audit` + `pip-audit` | ❌ tư vấn |
| **deploy** | `deploy/redeploy.ps1` trên VPS — CHỈ chạy khi `push` nhánh Titus và 3 job trên xanh | — auto |

Job **deploy** dùng `needs: [backend, frontend, extension]` nên tự bị bỏ qua nếu CI đỏ →
code lỗi không bao giờ ra production. Nó chạy trên **self-hosted runner** cài trên chính VPS
(xem "Cài một lần trên VPS" bên dưới). `security-audit` (tư vấn) KHÔNG nằm trong `needs`.

> ⚠️ `ci.yml` đặt `cancel-in-progress: true`: push liên tiếp lên Titus sẽ hủy lượt cũ (kể cả
> deploy đang chạy) để nhường lượt mới. Tự-sửa vì lượt mới deploy code mới hơn, nhưng nếu bị
> cắt đúng lúc restart service thì service có thể tắt vài giây tới khi lượt sau chạy xong.

Cố ý **không** chạy `scripts/smoke/*` trong CI: chúng cần Chrome thật + đăng nhập Google/sàn
+ mạng ngoài, nên sẽ đỏ vì môi trường chứ không phải vì code. Smoke vẫn chạy tay khi cần
(`python scripts/smoke/ads.py`, …). Nguyên tắc: **mỗi lần CI đỏ là một lỗi thật.**

Muốn bắt buộc CI xanh mới merge được: **Settings → Branches → Add rule** cho `main` (và
`Titus` nếu muốn), tick *Require status checks* rồi chọn `backend`, `frontend`, `extension`.

## `deploy.yml` — deploy vào VPS, BẤM TAY (override)

Auto-deploy đã bật ở job `deploy` trong `ci.yml`. File này dành cho khi cần **deploy một
SHA/nhánh cụ thể** hoặc **deploy lại** mà không đổi code: **Actions → Deploy to VPS → Run
workflow** (chọn nhánh/SHA nếu muốn). Dùng chung concurrency `deploy-vps` với ci.yml.

Cả hai đều chạy `deploy/redeploy.ps1` NGAY TRÊN VPS qua một **self-hosted runner**, làm: `git fetch`
→ `reset --hard` → cài lại phụ thuộc *nếu* `requirements.txt`/`package-lock.json` đổi → `next
build` *nếu* frontend đổi → `Restart-Service` đúng service cần → kiểm `/api/health`.

### Cài một lần trên VPS

1. **Thư mục app phải là bản clone git** (nếu đang là thư mục giải nén .zip):
   VPS hiện tại đặt ở `C:\AI-TNT-Research-SPY` (2 service `ResearchSpyBackend`/`ResearchSpyFrontend`).
   Workflow đã truyền `-Root C:\AI-TNT-Research-SPY`; đổi máy/đường dẫn thì sửa `-Root` trong
   `ci.yml` (job deploy) và `deploy.yml`.
   ```powershell
   # sao lưu .env.local, models/ trước nếu cần
   git clone https://github.com/Digital-Transformation-TNT/Research-SPY.git C:\AI-TNT-Research-SPY
   cd C:\AI-TNT-Research-SPY\deploy; .\vps-setup.ps1     # dựng service lần đầu
   ```
2. **Đăng ký self-hosted runner** (GitHub → Settings → Actions → Runners → New self-hosted
   runner → Windows). Chạy các lệnh nó đưa, rồi cài runner như một service để tự chạy nền:
   ```powershell
   ./config.cmd --url https://github.com/Digital-Transformation-TNT/Research-SPY --token <TOKEN> --labels self-hosted,windows
   ./svc.cmd install ; ./svc.cmd start
   ```
   Runner **phải chạy bằng tài khoản có quyền `Restart-Service`** cho 2 service (Administrator).

Không cần SSH key hay secret nào: job chạy ngay trên máy đích.

### Auto-deploy đã bật — muốn thêm một người duyệt tay mỗi lần?

Job `deploy` đã khai `environment: production`. Vào **Settings → Environments → production →
Required reviewers** thêm người duyệt: mỗi lần auto-deploy sẽ DỪNG chờ một người bấm duyệt
mới chạy (vẫn tự pull, nhưng có chốt người). Bỏ chọn nếu muốn deploy hoàn toàn tự động.

Ghi chú vì sao KHÔNG dùng `workflow_run` (như bản README cũ gợi ý): trigger đó chỉ chạy khi
file workflow nằm trên **nhánh mặc định** — mà repo này để mặc định `main` (trống), còn code
sống ở `Titus`. Đặt job deploy thẳng trong `ci.yml` (trigger `push`) né được ràng buộc đó và
vẫn deploy đúng sau khi CI xanh.
