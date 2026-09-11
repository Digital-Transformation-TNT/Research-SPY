"""
Ánh xạ ngành hàng Shopee VN → từ khoá tiếng Trung để tìm nguồn trên 1688.

    cd backend
    python -m hub.ingestion.map_1688            # nạp vào crawl_categories
    python -m hub.ingestion.map_1688 --dry-run  # chỉ in ra, không ghi

VÌ SAO LÀ TỪ KHOÁ CHỨ KHÔNG PHẢI MÃ NGÀNH. Menu của 1688 trỏ thẳng tới
`offer_search.htm?keywords=<tên>` — sàn này coi danh mục là một lượt tìm. Nên "ánh xạ ngành"
ở đây nghĩa là: với mỗi ngành Shopee, cụm tiếng Trung nào tìm ra đúng loại hàng đó trên 1688.

PHẢI LÀ TIẾNG TRUNG, và đây không phải chuyện thẩm mỹ. Tiêu đề sản phẩm trên 1688 toàn tiếng
Trung, nên ném "laptop backpack" vào ô tìm kiếm cho ra rất ít hàng — mà vẫn `SUCCESS`, vẫn có
kết quả, chỉ là nghèo. Kiểu hỏng không nhìn ra được nếu không biết trước.

NGÀNH "KHÁC"/"Others" CỐ Ý BỎ. Shopee dùng nó làm sọt chứa phần dư của ngành cha; dịch ra thì
được một cụm vô nghĩa như "其他", tìm trên 1688 ra đủ thứ không liên quan. Thà thiếu còn hơn
có một dòng dữ liệu trông dùng được mà thật ra là rác — cùng lý do với `None` ở bảng ánh xạ
Google Trends bên `trends_rank.py`.

MỘT CỤM TIẾNG TRUNG CÓ THỂ PHỤC VỤ NHIỀU NGÀNH SHOPEE. "Giày Thể Thao" của mục Thể thao và
"Sneakers" của mục Giày Dép Nữ đều về `运动鞋`; 1688 không tách theo giới ở mục này. Khoá chính
của `crawl_categories` là `(platform, market, code)` nên chúng gộp thành một dòng — một lượt
cào, một bộ dữ liệu.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from .. import db

#: `sub_id` của Shopee VN → cụm từ khoá tiếng Trung dùng để tìm trên 1688.
#:
#: Chọn cụm theo cách người mua sỉ Trung Quốc thật sự gõ, không dịch từng chữ: "Áo Ba Lỗ" là
#: `背心` chứ không phải `三孔衬衫`, "Đồ Bộ" là `套装` chứ không phải `整套衣服`.
MAP: dict[str, str] = {
    # ── Thể Thao & Du Lịch ──────────────────────────────────────────────────
    "11035479": "行李箱",          # Vali
    "11035487": "旅行包",          # Túi du lịch
    "11035492": "旅行配件",        # Phụ kiện du lịch
    "11035503": "户外运动器材",    # Dụng cụ thể thao & dã ngoại
    "11035531": "运动鞋",          # Giày thể thao
    "11035543": "运动服",          # Thời trang thể thao
    "11035553": "户外配件",        # Phụ kiện thể thao & dã ngoại
    # ── Thời Trang Nam ──────────────────────────────────────────────────────
    "11035578": "男士卫衣",        # Áo hoodie, áo len & áo nỉ
    "11035584": "男士西裤",        # Quần dài/quần âu
    "11035583": "男士牛仔裤",      # Quần jeans
    "11035590": "男士短裤",        # Quần short
    "11035592": "男士T恤",         # Áo
    "11035597": "男士背心",        # Áo ba lỗ
    "11035598": "男士内裤",        # Đồ lót
    "11035603": "男士睡衣",        # Đồ ngủ
    "11035604": "男士套装",        # Đồ bộ
    "11035605": "男士袜子",        # Vớ/tất
    "11035614": "男士首饰",        # Trang sức nam
    "11035620": "男士眼镜",        # Kính mắt nam
    "11035625": "男士皮带",        # Thắt lưng nam
    "11035626": "领带",            # Cà vạt & nơ cổ
    "11035627": "男士配饰",        # Phụ kiện nam
    # ── Thời Trang Nữ ───────────────────────────────────────────────────────
    "11035648": "女士裤子",        # Quần
    "11035652": "女士短裤",        # Quần đùi
    "11035656": "半身裙",          # Chân váy
    "11035657": "女士牛仔裤",      # Quần jeans
    "11035660": "连体裤",          # Đồ liền thân
    "11035672": "女士针织开衫",    # Áo len & cardigan
    "11035673": "女士卫衣",        # Hoodie và áo nỉ
    "11035677": "女士套装",        # Bộ
    "11035682": "女士内衣",        # Đồ lót
    "11035692": "女士睡衣",        # Đồ ngủ
    "11035640": "女士上衣",        # Áo
    "11035730": "女士运动服",      # Đồ tập
    "11035697": "孕妇装",          # Đồ bầu
    "11035713": "面料",            # Vải
    "11035726": "女士袜子",        # Vớ/tất
    # ── Balo & Túi Ví Nam ───────────────────────────────────────────────────
    "11035742": "男士双肩包",      # Ba lô nam
    "11035743": "电脑双肩包",      # Ba lô laptop nam
    "11035744": "电脑包",          # Túi & cặp đựng laptop
    "11035747": "笔记本内胆包",    # Túi chống sốc laptop
    "11035748": "男士托特包",      # Túi tote nam
    "11035749": "男士公文包",      # Cặp xách công sở
    "11035750": "男士手包",        # Ví cầm tay nam
    "11035751": "男士腰包",        # Túi đeo hông & ngực
    "11035752": "男士斜挎包",      # Túi đeo chéo nam
    "11035753": "男士钱包",        # Bóp/ví nam
    # ── Túi Ví Nữ ───────────────────────────────────────────────────────────
    "11035762": "女士双肩包",      # Ba lô nữ
    "11035763": "女士电脑包",      # Cặp laptop
    "11035768": "女士手拿包",      # Ví dự tiệc & ví cầm tay
    "11035769": "女士腰包",        # Túi đeo hông & ngực
    "11035770": "女士托特包",      # Túi tote
    "11035771": "女士手提包",      # Túi quai xách
    "11035772": "女士斜挎包",      # Túi đeo chéo & đeo vai
    "11035773": "女士钱包",        # Ví/bóp nữ
    "11035780": "包包配件",        # Phụ kiện túi
    # ── Đồng Hồ ─────────────────────────────────────────────────────────────
    "11035789": "男士手表",        # Đồng hồ nam
    "11035790": "女士手表",        # Đồng hồ nữ
    "11035791": "情侣手表",        # Bộ & đồng hồ cặp
    "11035792": "儿童手表",        # Đồng hồ trẻ em
    "11035793": "手表配件",        # Phụ kiện đồng hồ
    # ── Giày Dép Nam ────────────────────────────────────────────────────────
    "11035802": "男士靴子",        # Bốt
    "11035807": "男士运动鞋",      # Giày thể thao / sneakers
    "11035808": "男士拖鞋",        # Giày sục (slip-ons & mules)
    "11035809": "男士豆豆鞋",      # Giày tây lười (loafers)
    "11035810": "男士皮鞋",        # Oxfords & lace-ups
    "11035811": "男士凉鞋",        # Sandals & flip flops
    "11035817": "鞋子护理",        # Shoe care & accessories
    # ── Giày Dép Nữ ─────────────────────────────────────────────────────────
    "11035826": "女士靴子",        # Boots
    "11035830": "女士运动鞋",      # Sneakers
    "11035831": "女士平底鞋",      # Flats
    "11035837": "女士高跟鞋",      # Heels
    "11035838": "坡跟鞋",          # Wedges
    "11035839": "女士凉拖鞋",      # Flat sandals & flip flops
    "11035845": "鞋类配件",        # Shoe care & accessories
    # ── Phụ Kiện & Trang Sức Nữ ─────────────────────────────────────────────
    "11035854": "戒指",            # Rings
    "11035855": "耳环",            # Earrings
    "11035856": "围巾",            # Scarves & shawls
    "11035857": "手套",            # Gloves
    "11035858": "发饰",            # Hair accessories
    "11035865": "手链",            # Bracelets & bangles
    "11035866": "脚链",            # Anklets
    "11035867": "帽子",            # Hats & caps
    "11035868": "项链",            # Necklaces
    "11035869": "女士眼镜",        # Eyewear
    "11035880": "女士腰带",        # Belts
    "11035881": "女士领结",        # Neckties & bow ties
    "11035882": "女士配饰",        # Additional accessories
    "11035891": "首饰套装",        # Accessories sets
    "11035893": "女士丝袜",        # Socks & stockings
    "11035897": "雨伞",            # Umbrella
    # ── Điện Thoại & Phụ Kiện ───────────────────────────────────────────────
    "11036060": "手机壳",          # Cases, covers & skins
    "11036074": "手机支架",        # Phone holders
    "11036091": "手机配件",        # Other accessories
    # ── Thiết Bị Điện Tử ────────────────────────────────────────────────────
    "11036143": "耳机",            # Earphones
    # ── Mẹ & Bé ─────────────────────────────────────────────────────────────
    "11036195": "婴儿推车",        # Baby travel essentials
    "11036204": "婴儿奶瓶",        # Feeding essentials
    "11036213": "孕妇用品",        # Maternity accessories
    "11036217": "孕产妇保健",      # Maternity healthcare
    "11036222": "婴儿洗护",        # Bath & body care
    "11036233": "婴儿床",          # Nursery
    "11036240": "婴儿安全用品",    # Baby safety
    "11036253": "婴儿保健",        # Baby healthcare
    "11036266": "婴儿玩具",        # Toys
    "11036277": "婴儿礼盒",        # Gift sets
    # ── Sắc Đẹp ─────────────────────────────────────────────────────────────
    "11036328": "护肤品",          # Skincare
    "11036280": "沐浴身体护理",    # Bath & body care
    "11036314": "彩妆",            # Makeup
    "11036297": "洗发护发",        # Hair care
    "11036321": "美妆工具",        # Beauty tools
    "11111646": "口腔护理",        # Oral care
    "11036310": "香水",            # Perfumes
    "11036304": "男士护理",        # Men's care
    "11111647": "女性护理",        # Feminine care
    "11036343": "美妆套装",        # Beauty sets
    # ── Sức Khỏe ────────────────────────────────────────────────────────────
    "11036352": "医疗用品",        # Medical supplies
    "11036373": "驱蚊用品",        # Insect repellents
    "11036370": "成人纸尿裤",      # Adult diapers
    "11036348": "美容保健品",      # Beauty supplements
    "11036372": "按摩仪",          # Massage & therapy devices
    # ── Thời Trang Trẻ Em ───────────────────────────────────────────────────
    "11036418": "男童装",          # Boy clothes
    "11036438": "女童装",          # Girl clothes
    "11036461": "男童鞋",          # Boy shoes
    "11036469": "女童鞋",          # Girl shoes
    "11036383": "婴儿服装",        # Baby clothes
    "11036396": "婴儿鞋袜",        # Baby mittens & footwear
    "11036397": "儿童配饰",        # Baby & kids accessories
    # ── Chăm Sóc Thú Cưng ───────────────────────────────────────────────────
    "11036490": "宠物用品",        # Pet accessories
    "11036498": "猫砂",            # Litter & toilet
    "11036510": "宠物服装",        # Pet clothing
    "11036519": "宠物保健",        # Pet healthcare
    "11116223": "宠物美容",        # Pet grooming
    # ── Bách Hóa Online ─────────────────────────────────────────────────────
    "11036526": "方便食品",        # Convenience / ready-to-eat
    "11036544": "米面粮油",        # Food staples
    "11036552": "调味品",          # Cooking essentials
    "11036562": "烘焙原料",        # Baking needs
    "11036576": "饮料",            # Beverages
    "11036570": "早餐麦片",        # Breakfast cereals
    "11036622": "食品礼盒",        # Gift sets & hampers
    # ── Giặt Giũ & Chăm Sóc Nhà Cửa ─────────────────────────────────────────
    "11036625": "洗衣液",          # Laundry
    "11036634": "卫生纸",          # Toilet paper
    "11036639": "家用清洁剂",      # Household cleaning
    "11036647": "洗洁精",          # Dishwashing
    "11036649": "清洁工具",        # Cleaning tools
    "11036654": "空气清新剂",      # Air fresheners
    "11036660": "杀虫剂",          # Insect killer
    "11036664": "保鲜袋",          # Food preservation
    "11036668": "垃圾袋",          # Trash bags
    # ── Nhà Cửa & Đời Sống ──────────────────────────────────────────────────
    "11036717": "家居装饰",        # Home decoration
    "11036732": "五金工具",        # Tools and home improvement
    "11036748": "厨房用品",        # Kitchenware & food storage
    "11036760": "灯具",            # Lighting
    "11036776": "户外园艺",        # Outdoor & garden
    "11036671": "卫浴用品",        # Bathroom
    "11111670": "宗教用品",        # Religious & worship items
    "11111669": "派对用品",        # Party supplies
    "11111665": "家务用品",        # Housekeeping & laundry
    "11111668": "收纳用品",        # Home organizers
    "11111666": "水杯",            # Drinkware
    "11111664": "香薰",            # Home fragrance & aromatherapy
    "11111667": "餐具",            # Dinnerware
    # ── Ô Tô & Xe Máy & Xe Đạp ──────────────────────────────────────────────
    "11036817": "头盔",            # Helmets
    "11036824": "摩托车配件",      # Motorbike accessories
    "11036846": "自行车配件",      # Bicycle & e-bike accessories
    "11108984": "汽车内饰",        # Interior accessories
    "11108967": "机油",            # Automotive oils & lubes
    "11109015": "汽车配件",        # Auto parts & spares
    "11108953": "摩托车零件",      # Motorbike spare parts
    "11109002": "汽车外饰",        # Exterior accessories
    "11108974": "汽车护理",        # Automotive care
    # ── Nhà Sách Online ─────────────────────────────────────────────────────
    "11108576": "礼品包装",        # Gift & wrapping
    "11108584": "文具笔",          # Writing & correction
    "11108591": "办公文具",        # School & office supplies
    "11108635": "绘画用品",        # Coloring & arts
    "11108610": "笔记本",          # Notebooks & paper
    "11036914": "纪念品",          # Souvenirs
    "11108624": "乐器",            # Nhạc cụ & phụ kiện âm nhạc
    # ── Đồ Chơi ─────────────────────────────────────────────────────────────
    "11036933": "收藏玩具",        # Hobbies & collectibles
    "11036939": "游戏周边",        # Game zone
    "11036946": "益智玩具",        # Educational toys
    "11036954": "婴幼儿玩具",      # Baby & toddler toys
    "11036960": "户外玩具",        # Action & outdoor toys
    "11036966": "毛绒玩具",        # Dolls & stuffed toys
    # ── Thiết Bị Điện Gia Dụng ──────────────────────────────────────────────
    "11036972": "厨房电器",        # Kitchen appliances
    "11037016": "挂烫机",          # Garment care
    "11111623": "料理机",          # Blenders, mixers & grinders
    # ── Dụng cụ và thiết bị tiện ích ────────────────────────────────────────
    "11116487": "手动工具",        # Handtool
    "11116489": "电工电料",        # Electrical circuitry & parts
    "11116486": "五金配件",        # Accessories
}

#: Ngành Shopee CỐ Ý không ánh xạ. Chép ra đây thay vì để im lặng vắng mặt, vì "không có trong
#: MAP" và "đã xem xét rồi bỏ" là hai chuyện khác nhau với người đọc sau.
BO_QUA_VI = ("Ngành 'Khác'/'Others' là sọt chứa phần dư nên dịch ra không thành từ khoá; "
             "'Sách Tiếng Việt'/'Sách ngoại văn' và 'Dịch vụ cho xe' thì 1688 không có — nó là "
             "sàn bán sỉ HÀNG SẢN XUẤT, không phải nơi nhập sách tiếng Việt hay mua dịch vụ")

#: Sách nội/ngoại văn và Music & Media cũng bỏ: 1688 là sàn bán sỉ hàng sản xuất, không phải
#: nơi nhập sách tiếng Việt hay đĩa nhạc.
BO_QUA_THEM = {"11108503", "11108540"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build() -> list[dict]:
    """Ghép MAP với tên ngành Shopee. Trả một dòng cho mỗi cụm tiếng Trung KHÁC NHAU."""
    with db.connect() as c:
        nganh = {r["sub_id"]: dict(r) for r in c.execute(
            "SELECT sub_id, sub_name, main_name FROM shopee_categories"
            " WHERE market='vn' AND active=1")}

    gom: dict[str, dict] = {}
    for sub_id, cum in MAP.items():
        n = nganh.get(sub_id)
        if not n:
            continue                       # ngành đã bị gỡ khỏi sheet
        e = gom.setdefault(cum, {"code": cum, "shopee": [], "sub_ids": []})
        e["shopee"].append(f'{n["main_name"]} > {n["sub_name"]}')
        e["sub_ids"].append(sub_id)
    return list(gom.values())


def chua_anh_xa() -> list[str]:
    """Ngành Shopee VN chưa có cụm tiếng Trung — nói ra thay vì để lặng lẽ vắng."""
    with db.connect() as c:
        rows = c.execute(
            "SELECT sub_id, main_name, sub_name FROM shopee_categories"
            " WHERE market='vn' AND active=1").fetchall()
    return sorted(f'{r["main_name"]} > {r["sub_name"]}' for r in rows
                  if r["sub_id"] not in MAP)


def nap(dry_run: bool = False) -> dict:
    rows = build()
    if not dry_run:
        now = _now()
        with db.connect() as c:
            c.executemany(
                "INSERT INTO crawl_categories"
                " (platform, market, code, name, parent_code, active, imported_at)"
                " VALUES ('1688','cn',?,?,?,1,?)"
                " ON CONFLICT(platform, market, code) DO UPDATE SET"
                "   name=excluded.name, parent_code=excluded.parent_code,"
                "   active=1, imported_at=excluded.imported_at",
                [(r["code"], " · ".join(r["shopee"]), ",".join(r["sub_ids"]), now)
                 for r in rows])
    return {"cum_tieng_trung": len(rows), "nganh_shopee_da_anh_xa": len(MAP),
            "chua_anh_xa": chua_anh_xa(), "dry_run": dry_run}


def main() -> int:
    ap = argparse.ArgumentParser(description="Nạp ánh xạ ngành Shopee VN → từ khoá 1688")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db.init_db()
    r = nap(dry_run=args.dry_run)
    tag = " (dry-run)" if r["dry_run"] else ""
    print(f"{r['cum_tieng_trung']} cụm tiếng Trung từ {r['nganh_shopee_da_anh_xa']} "
          f"ngành Shopee{tag}")
    if r["chua_anh_xa"]:
        print(f"\nchưa ánh xạ ({len(r['chua_anh_xa'])} ngành) — {BO_QUA_VI}:")
        for x in r["chua_anh_xa"]:
            print(f"    {x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
