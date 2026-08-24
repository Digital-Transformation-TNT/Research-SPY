@echo off
chcp 65001 >nul
setlocal

rem ---------------------------------------------------------------------------
rem  Research SPY — mở cả công cụ bằng một cú nhấp đúp.
rem
rem  Bật backend (cổng 8000) và frontend (cổng 3000) trong HAI cửa sổ riêng, rồi
rem  mở trình duyệt. Hai cửa sổ tách rời là cố ý: log của mỗi bên đọc riêng, và
rem  Ctrl+C tắt được đúng một bên mà không giết bên kia.
rem
rem  KHÔNG thêm --reload cho uvicorn. Trên Windows cờ đó đổi event loop sang
rem  WindowsSelectorEventLoopPolicy, loop không sinh được tiến trình con nên
rem  Playwright chết ngay khi khởi động — mất Google Trends và toàn bộ mục
rem  Quảng cáo. Sửa backend thì đóng cửa sổ đó rồi chạy lại file này.
rem  (--workers dính đúng lỗi này, và còn nhân số request ra ngoài lên.)
rem ---------------------------------------------------------------------------

cd /d "%~dp0"

echo.
echo   Research SPY
echo   ------------

rem --- Cổng đang bận nghĩa là công cụ đã chạy rồi. Bật chồng lên chỉ tạo ra một
rem --- tiến trình chết yểu và một thông báo lỗi khó hiểu, nên dừng ở đây.
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo   Cổng 8000 đang bận — backend chạy rồi.
    echo   Muốn khởi động lại thì đóng cửa sổ backend cũ trước.
    echo.
    start "" http://localhost:3000
    timeout /t 5 >nul
    exit /b 0
)

rem --- Lần đầu clone về thì chưa có node_modules. Cài luôn thay vì để npm báo lỗi.
if not exist "frontend\node_modules" (
    echo   Chưa có node_modules — đang cài, lần đầu mất vài phút...
    pushd frontend
    call npm install
    popd
    echo.
)

echo   [1/2] Backend  → http://127.0.0.1:8000
start "Research SPY - Backend" /D "%~dp0backend" cmd /k python -m uvicorn app.main:app --port 8000

echo   [2/2] Frontend → http://localhost:3000
start "Research SPY - Frontend" /D "%~dp0frontend" cmd /k npm run dev

rem --- Next.js mất khoảng 10s để sẵn sàng. Mở trình duyệt sớm hơn thì ra trang lỗi
rem --- kết nối, người dùng tưởng hỏng.
echo.
echo   Đang chờ frontend khởi động...
timeout /t 14 /nobreak >nul
start "" http://localhost:3000

echo.
echo   Xong. Công cụ đang chạy trong hai cửa sổ vừa mở.
echo   Tắt: đóng cả hai cửa sổ đó, hoặc Ctrl+C trong từng cửa sổ.
echo.
timeout /t 6 >nul
