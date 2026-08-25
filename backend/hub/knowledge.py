"""Knowledge base nghiệp vụ Printway — nhét vào system prompt của Copilot & Report.

Nguồn: tài liệu tri thức chính thức Printway (printway-agent-knowledge.md).
Giúp Copilot/Report trả lời "có nghề", đúng ngôn ngữ R&D của Printway.
"""

PRINTWAY_CONTEXT = """# BỐI CẢNH PRINTWAY (POD fulfillment toàn cầu)
- 7+ năm, 300+ nhân sự tại 6 quốc gia; 1.000+ dòng sản phẩm; công suất 150.000 sp/ngày.
- Nhà xưởng: Mỹ, Việt Nam, Châu Âu, Châu Úc, Trung Quốc, Canada.
- Kết nối sàn: Etsy, Amazon, Shopify, Walmart, WooCommerce, TikTok Shop.
- Thế mạnh cốt lõi: HOME DECOR (phân khúc tăng trưởng nhanh nhất ~24.5% CAGR).

# THỊ TRƯỜNG POD
- Quy mô ~ $10.8B (2025) → $13.1B (2026) → $57.5B (2033), CAGR ~23.6%.
- Bắc Mỹ ~36% doanh thu. Apparel ~39.5% (lớn nhất), Home Decor tăng nhanh nhất.

# VÒNG ĐỜI SẢN PHẨM POD (5 giai đoạn) — quyết định hành động
1. Conception: bắt tín hiệu sớm (Pinterest/TikTok/Threads/IG), test ý tưởng.
2. Launch: tạo listing, chạy test đo phản hồi.
3. Growth: xác định SP "Win", scale doanh thu, siết fulfillment.
4. Saturation: cạnh tranh gay gắt, đối thủ copy — chỉ vào nếu có edge khác biệt.
5. Decline: growth âm — clearance, không mở mới.

# BỘ 9 CHỈ SỐ CHẤM ĐIỂM (3 nhóm)
- Nhóm I Năng lực sản xuất: Production Fit, Production Time, Seasonality Fit, Personalization.
- Nhóm II Tài chính: Revenue Potential, Profit Margin (= Giá bán − (COGS + Shipping + Phí sàn)).
- Nhóm III Thị trường & cạnh tranh: Market Demand, Growth Rate, Competition Level.
- LUẬT BẮT BUỘC: doanh số lớn nhưng GROWTH ÂM ⇒ chấm điểm THẤP (đã bão hòa/suy thoái).

# ONTOLOGY (phân loại — không được nhầm lẫn)
- Niche: ngách theo sở thích/nghề/sự kiện (Cat Lover, Nurse, Teacher, Memorial...).
- Seasonality: dịp lễ có nhu cầu đột biến (Christmas, Mother's Day, Wedding...).
- Category: ngành hàng phân cấp (Home Living → Outdoor & Gardening / Kitchen & Dining).
- Product Type: đơn vị sản phẩm vật lý theo chất liệu + quy trình (Acrylic Plaque, Wooden Sign...).
- SKU: mã biến thể (nhà cung cấp PW + loại + chất liệu + số lớp + kích thước).

# 3 PAIN POINTS cần giải
1. Hỗn loạn tên gọi (seller đặt tên SEO ≠ tên kỹ thuật Printway) → phải chuẩn hóa về Product Type.
2. Công cụ phân mảnh (Helium10/Amazon, Alura/Etsy) → cần view hợp nhất.
3. Việc thủ công (thu thập, lập report) → tự động hóa.
"""
