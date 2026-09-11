#!/usr/bin/env bash
# Đợi vòng cào Shopee VN xong rồi mới chạy PH. KHÔNG chạy chồng: một máy-thợ, một tab Shopee,
# hai vòng cào cùng lúc sẽ giành nhau tab và cả hai đều hỏng.
cd /c/AI-TNT-Research-SPY/backend
while true; do
  # ĐẾM RIÊNG `ok`, KHÔNG đếm tổng số dòng nhật ký. Đếm tổng là cái bẫy đã sập một lần:
  # máy-thợ rớt thì 190 ngành vào nhật ký với status='error' trong 17 giây, tổng chạm 206, và
  # điều kiện "đủ 206" đọc thành "VN xong" rồi bắn PH ngay giữa lúc VN chưa cào được gì.
  n=$(PYTHONIOENCODING=utf-8 python -c "
import sqlite3
c=sqlite3.connect('hub_data.db')
print(c.execute(\"select coalesce(sum(status='ok'),0) from crawl_log where day=date('now') and market_code='vn' and source='shopee'\").fetchone()[0])
" 2>/dev/null || echo 0)
  # 200 chứ không phải 206: vài ngành hỏng thật là chuyện bình thường, và bắt PH đợi một con
  # số hoàn hảo nghĩa là nó không bao giờ chạy.
  if [ "$n" -ge 200 ] 2>/dev/null; then break; fi
  sleep 180
done
echo "VN xong ($n/206) — bat dau PH luc $(date -u +%H:%M:%S)"
curl -s -m 30000 -X POST http://127.0.0.1:8000/api/hub/signal/snapshot-categories \
  -H "Content-Type: application/json" -d '{"market":"ph"}' \
  -o /c/AI-TNT-Research-SPY/backend/.ph_result.json -w "PH: HTTP %{http_code} sau %{time_total}s\n"
