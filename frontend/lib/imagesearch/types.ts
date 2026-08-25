/**
 * Từ vựng của MỤC TÌM BẰNG ẢNH, phía giao diện.
 * Nguồn sự thật: `backend/lib/imagesearch/types.py`.
 */

/** Mô hình đọc được gì từ tấm ảnh. Luôn có, kể cả khi phần tìm hàng tương tự bị treo. */
export type ImageIdentity = {
  product: string
  /** Rỗng khi không đọc được nhãn trên ảnh — cố ý không đoán. */
  brand?: string
  /**
   * Mã model đọc được TRÊN ẢNH ("G304", "PH1627"). Đây là mã HÃNG, và theo phép đo
   * 2026-08-19 nó là loại mã DUY NHẤT tra ngược ra hàng ở sàn Việt Nam — mã lấy từ tiêu đề
   * 1688 là mã xưởng và trả về không có gì. Xem `types.py::ImageIdentity.model`.
   */
  model?: string
  /** `vi` là từ gốc mang sang tab Từ khoá; `zh` là đường tra tay khi tìm bằng ảnh trượt. */
  terms?: Record<string, string[]>
}

export type ImageMatch = {
  source: string
  title: string
  link: string
  thumbnail?: string
  /** Giá nguyên văn như Google hiện ("989.000 đ") — không phải số, vì đơn vị đổi theo nước. */
  price?: string
  /**
   * `price` rút về số, CHỈ để sắp xếp. Đơn vị là đơn vị của chính dòng đó, không quy đổi —
   * nên chỉ so được trong cùng một bảng, và đó đúng là cách giao diện dùng nó (mỗi bảng một
   * nút sắp xếp riêng). Vắng mặt khi nguồn không cho giá; dòng như vậy xếp xuống cuối chứ
   * không bị loại. Giá dạng khoảng ("¥1.20-3.50") rút về cận dưới.
   */
  priceValue?: number
  rating?: number
  reviews?: number
  inStock?: boolean
  marketplace?: boolean
  /** Sàn của dòng này: `shopee` | `lazada` | `tiktok` | `other`. Backend tính từ `link`. */
  platform?: string

  // --- các trường dưới chỉ có ở nguồn nhập hàng (1688, Alibaba.com) ---
  /** Tên công ty cung cấp. Google Lens không có khái niệm này. */
  supplier?: string
  /** Tỉnh + thành phố của xưởng — với người đi nhập thì đây là cước và thời gian giao. */
  location?: string
  /** Số lượng đã bán. Là số để so sánh được giữa các nhà cung cấp. */
  sold?: number
  /**
   * Số lượng đặt tối thiểu, nguyên văn ("Min. order: 500 pieces"). Chỉ Alibaba.com có.
   * Giữ nguyên chữ vì đơn vị đổi theo mặt hàng — "500" trần trụi thì không đặt hàng được.
   */
  moq?: string
  /** Con số bán hàng mà nguồn chỉ cho dưới dạng chữ — Taobao trả "300+人付款". */
  note?: string
}

/**
 * Một chip lọc trên bảng "Nơi đang bán".
 *
 * `count` được phép bằng không và chip vẫn phải hiện: "TikTok 0" nói rằng ảnh này không tìm
 * thấy hàng trên TikTok, khác hẳn với việc không có chip TikTok — thứ người ta đọc thành
 * "công cụ không tra TikTok".
 */
export type PlatformCount = {
  id: string
  label: string
  count: number
}

export type ImageSearchResult = {
  country: string
  identity?: ImageIdentity
  /** Ai đang BÁN LẺ ở thị trường đích, theo Google Lens. */
  matches?: ImageMatch[]
  /**
   * Số đếm mỗi sàn cho dãy chip lọc trên `matches`. Lọc là việc CỦA GIAO DIỆN, không gọi lại
   * server: một lượt Lens đã lấy về đủ mọi sàn, nên bấm đổi chip không tốn thêm suất hạn mức.
   */
  platforms?: PlatformCount[]
  /** NHẬP ở đâu, theo 1688. Tách khỏi `matches` vì giá sỉ ¥ và giá lẻ đ không so được với nhau. */
  sourcing?: ImageMatch[]
  /** Bán buôn XUẤT KHẨU theo Alibaba.com — giá đã là ₫ và kèm `moq`. Mua được mà không cần
   *  người gom hàng trong nước Trung Quốc, nên nó là một câu hỏi khác với `sourcing`. */
  globalSourcing?: ImageMatch[]
  /** Bán lẻ ở chợ gốc, theo Taobao. Rỗng khi phiên đăng nhập Taobao hết hạn. */
  chinaRetail?: ImageMatch[]
  /** Bán lẻ quốc tế theo AliExpress — ship lẻ về VN. Đây là TRẦN GIÁ: khách của người dùng tự
   *  đặt được ở mức này, nên bán cao hơn là khó. Rỗng khi AliExpress đang chặn theo tần suất. */
  globalRetail?: ImageMatch[]
  /** Thường là "Lens đang bận" — không phải lỗi, và khi đó `identity` vẫn còn nguyên. */
  message?: string
  tookMs?: number
  cached?: boolean
}
