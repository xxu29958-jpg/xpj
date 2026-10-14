package com.ticketbox.domain.model

/**
 * 支持记录和展示的币种。
 *
 * 多币种记账语义由后端权威返回的 `homeAmountCents`、`homeCurrency`、
 * `originalCurrencyCode`、`originalAmountMinor` 和冻结汇率字段承载。
 * 本枚举只定义支持的币种代码和本地格式化参数，不包含汇率或折算逻辑。
 */
enum class CurrencyCode(
    val storageKey: String,
    val displayName: String,
    val symbol: String,
    val localeTag: String,
    val minorUnitDigits: Int,
) {
    // BEGIN GENERATED CURRENCY CATALOG
    CNY("CNY", "人民币", "¥", "zh-CN", 2),
    USD("USD", "美元", "$", "en-US", 2),
    EUR("EUR", "欧元", "€", "de-DE", 2),
    GBP("GBP", "英镑", "£", "en-GB", 2),
    JPY("JPY", "日元", "¥", "ja-JP", 0),
    HKD("HKD", "港币", "HK$", "zh-HK", 2),
    KRW("KRW", "韩元", "₩", "ko-KR", 0),
    AED("AED", "阿联酋迪拉姆", "AED ", "zh-CN", 2),
    AFN("AFN", "阿富汗尼", "AFN ", "zh-CN", 2),
    ALL("ALL", "阿尔巴尼亚列克", "ALL ", "zh-CN", 2),
    AMD("AMD", "亚美尼亚德拉姆", "AMD ", "zh-CN", 2),
    AOA("AOA", "安哥拉宽扎", "AOA ", "zh-CN", 2),
    ARS("ARS", "阿根廷比索", "ARS ", "zh-CN", 2),
    AUD("AUD", "澳大利亚元", "AUD ", "zh-CN", 2),
    AWG("AWG", "阿鲁巴弗罗林", "AWG ", "zh-CN", 2),
    AZN("AZN", "阿塞拜疆马纳特", "AZN ", "zh-CN", 2),
    BAM("BAM", "波斯尼亚-黑塞哥维那可兑换马克", "BAM ", "zh-CN", 2),
    BBD("BBD", "巴巴多斯元", "BBD ", "zh-CN", 2),
    BDT("BDT", "孟加拉塔卡", "BDT ", "zh-CN", 2),
    BHD("BHD", "巴林第纳尔", "BHD ", "zh-CN", 3),
    BIF("BIF", "布隆迪法郎", "BIF ", "zh-CN", 0),
    BMD("BMD", "百慕大元", "BMD ", "zh-CN", 2),
    BND("BND", "文莱元", "BND ", "zh-CN", 2),
    BOB("BOB", "玻利维亚诺", "BOB ", "zh-CN", 2),
    BRL("BRL", "巴西雷亚尔", "BRL ", "zh-CN", 2),
    BSD("BSD", "巴哈马元", "BSD ", "zh-CN", 2),
    BTN("BTN", "不丹努尔特鲁姆", "BTN ", "zh-CN", 2),
    BWP("BWP", "博茨瓦纳普拉", "BWP ", "zh-CN", 2),
    BYN("BYN", "白俄罗斯卢布", "BYN ", "zh-CN", 2),
    BZD("BZD", "伯利兹元", "BZD ", "zh-CN", 2),
    CAD("CAD", "加拿大元", "CAD ", "zh-CN", 2),
    CDF("CDF", "刚果法郎", "CDF ", "zh-CN", 2),
    CHF("CHF", "瑞士法郎", "CHF ", "zh-CN", 2),
    CLP("CLP", "智利比索", "CLP ", "zh-CN", 0),
    COP("COP", "哥伦比亚比索", "COP ", "zh-CN", 2),
    CRC("CRC", "哥斯达黎加科朗", "CRC ", "zh-CN", 2),
    CUP("CUP", "古巴比索", "CUP ", "zh-CN", 2),
    CVE("CVE", "佛得角埃斯库多", "CVE ", "zh-CN", 2),
    CZK("CZK", "捷克克朗", "CZK ", "zh-CN", 2),
    DJF("DJF", "吉布提法郎", "DJF ", "zh-CN", 0),
    DKK("DKK", "丹麦克朗", "DKK ", "zh-CN", 2),
    DOP("DOP", "多米尼加比索", "DOP ", "zh-CN", 2),
    DZD("DZD", "阿尔及利亚第纳尔", "DZD ", "zh-CN", 2),
    EGP("EGP", "埃及镑", "EGP ", "zh-CN", 2),
    ERN("ERN", "厄立特里亚纳克法", "ERN ", "zh-CN", 2),
    ETB("ETB", "埃塞俄比亚比尔", "ETB ", "zh-CN", 2),
    FJD("FJD", "斐济元", "FJD ", "zh-CN", 2),
    FKP("FKP", "福克兰群岛镑", "FKP ", "zh-CN", 2),
    GEL("GEL", "格鲁吉亚拉里", "GEL ", "zh-CN", 2),
    GHS("GHS", "加纳塞地", "GHS ", "zh-CN", 2),
    GIP("GIP", "直布罗陀镑", "GIP ", "zh-CN", 2),
    GMD("GMD", "冈比亚达拉西", "GMD ", "zh-CN", 2),
    GNF("GNF", "几内亚法郎", "GNF ", "zh-CN", 0),
    GTQ("GTQ", "危地马拉格查尔", "GTQ ", "zh-CN", 2),
    GYD("GYD", "圭亚那元", "GYD ", "zh-CN", 2),
    HNL("HNL", "洪都拉斯伦皮拉", "HNL ", "zh-CN", 2),
    HTG("HTG", "海地古德", "HTG ", "zh-CN", 2),
    HUF("HUF", "匈牙利福林", "HUF ", "zh-CN", 2),
    IDR("IDR", "印度尼西亚卢比", "IDR ", "zh-CN", 2),
    ILS("ILS", "以色列新谢克尔", "ILS ", "zh-CN", 2),
    INR("INR", "印度卢比", "INR ", "zh-CN", 2),
    IQD("IQD", "伊拉克第纳尔", "IQD ", "zh-CN", 3),
    IRR("IRR", "伊朗里亚尔", "IRR ", "zh-CN", 2),
    ISK("ISK", "冰岛克朗", "ISK ", "zh-CN", 0),
    JMD("JMD", "牙买加元", "JMD ", "zh-CN", 2),
    JOD("JOD", "约旦第纳尔", "JOD ", "zh-CN", 3),
    KES("KES", "肯尼亚先令", "KES ", "zh-CN", 2),
    KGS("KGS", "吉尔吉斯斯坦索姆", "KGS ", "zh-CN", 2),
    KHR("KHR", "柬埔寨瑞尔", "KHR ", "zh-CN", 2),
    KMF("KMF", "科摩罗法郎", "KMF ", "zh-CN", 0),
    KPW("KPW", "朝鲜元", "KPW ", "zh-CN", 2),
    KWD("KWD", "科威特第纳尔", "KWD ", "zh-CN", 3),
    KYD("KYD", "开曼元", "KYD ", "zh-CN", 2),
    KZT("KZT", "哈萨克斯坦坚戈", "KZT ", "zh-CN", 2),
    LAK("LAK", "老挝基普", "LAK ", "zh-CN", 2),
    LBP("LBP", "黎巴嫩镑", "LBP ", "zh-CN", 2),
    LKR("LKR", "斯里兰卡卢比", "LKR ", "zh-CN", 2),
    LRD("LRD", "利比里亚元", "LRD ", "zh-CN", 2),
    LSL("LSL", "莱索托洛蒂", "LSL ", "zh-CN", 2),
    LYD("LYD", "利比亚第纳尔", "LYD ", "zh-CN", 3),
    MAD("MAD", "摩洛哥迪拉姆", "MAD ", "zh-CN", 2),
    MDL("MDL", "摩尔多瓦列伊", "MDL ", "zh-CN", 2),
    MGA("MGA", "马达加斯加阿里亚里", "MGA ", "zh-CN", 2),
    MKD("MKD", "马其顿第纳尔", "MKD ", "zh-CN", 2),
    MMK("MMK", "缅甸元", "MMK ", "zh-CN", 2),
    MNT("MNT", "蒙古图格里克", "MNT ", "zh-CN", 2),
    MOP("MOP", "澳门币", "MOP ", "zh-CN", 2),
    MRU("MRU", "毛里塔尼亚乌吉亚", "MRU ", "zh-CN", 2),
    MUR("MUR", "毛里求斯卢比", "MUR ", "zh-CN", 2),
    MVR("MVR", "马尔代夫卢菲亚", "MVR ", "zh-CN", 2),
    MWK("MWK", "马拉维克瓦查", "MWK ", "zh-CN", 2),
    MXN("MXN", "墨西哥比索", "MXN ", "zh-CN", 2),
    MYR("MYR", "马来西亚林吉特", "MYR ", "zh-CN", 2),
    MZN("MZN", "莫桑比克美提卡", "MZN ", "zh-CN", 2),
    NAD("NAD", "纳米比亚元", "NAD ", "zh-CN", 2),
    NGN("NGN", "尼日利亚奈拉", "NGN ", "zh-CN", 2),
    NIO("NIO", "尼加拉瓜科多巴", "NIO ", "zh-CN", 2),
    NOK("NOK", "挪威克朗", "NOK ", "zh-CN", 2),
    NPR("NPR", "尼泊尔卢比", "NPR ", "zh-CN", 2),
    NZD("NZD", "新西兰元", "NZD ", "zh-CN", 2),
    OMR("OMR", "阿曼里亚尔", "OMR ", "zh-CN", 3),
    PAB("PAB", "巴拿马巴波亚", "PAB ", "zh-CN", 2),
    PEN("PEN", "秘鲁索尔", "PEN ", "zh-CN", 2),
    PGK("PGK", "巴布亚新几内亚基那", "PGK ", "zh-CN", 2),
    PHP("PHP", "菲律宾比索", "PHP ", "zh-CN", 2),
    PKR("PKR", "巴基斯坦卢比", "PKR ", "zh-CN", 2),
    PLN("PLN", "波兰兹罗提", "PLN ", "zh-CN", 2),
    PYG("PYG", "巴拉圭瓜拉尼", "PYG ", "zh-CN", 0),
    QAR("QAR", "卡塔尔里亚尔", "QAR ", "zh-CN", 2),
    RON("RON", "罗马尼亚列伊", "RON ", "zh-CN", 2),
    RSD("RSD", "塞尔维亚第纳尔", "RSD ", "zh-CN", 2),
    RUB("RUB", "俄罗斯卢布", "RUB ", "zh-CN", 2),
    RWF("RWF", "卢旺达法郎", "RWF ", "zh-CN", 0),
    SAR("SAR", "沙特里亚尔", "SAR ", "zh-CN", 2),
    SBD("SBD", "所罗门群岛元", "SBD ", "zh-CN", 2),
    SCR("SCR", "塞舌尔卢比", "SCR ", "zh-CN", 2),
    SDG("SDG", "苏丹镑", "SDG ", "zh-CN", 2),
    SEK("SEK", "瑞典克朗", "SEK ", "zh-CN", 2),
    SGD("SGD", "新加坡元", "SGD ", "zh-CN", 2),
    SHP("SHP", "圣赫勒拿群岛磅", "SHP ", "zh-CN", 2),
    SLE("SLE", "塞拉利昂新利昂", "SLE ", "zh-CN", 2),
    SOS("SOS", "索马里先令", "SOS ", "zh-CN", 2),
    SRD("SRD", "苏里南元", "SRD ", "zh-CN", 2),
    SSP("SSP", "南苏丹镑", "SSP ", "zh-CN", 2),
    STN("STN", "圣多美和普林西比多布拉", "STN ", "zh-CN", 2),
    SYP("SYP", "叙利亚镑", "SYP ", "zh-CN", 2),
    SZL("SZL", "斯威士兰里兰吉尼", "SZL ", "zh-CN", 2),
    THB("THB", "泰铢", "THB ", "zh-CN", 2),
    TJS("TJS", "塔吉克斯坦索莫尼", "TJS ", "zh-CN", 2),
    TMT("TMT", "土库曼斯坦马纳特", "TMT ", "zh-CN", 2),
    TND("TND", "突尼斯第纳尔", "TND ", "zh-CN", 3),
    TOP("TOP", "汤加潘加", "TOP ", "zh-CN", 2),
    TRY("TRY", "土耳其里拉", "TRY ", "zh-CN", 2),
    TTD("TTD", "特立尼达和多巴哥元", "TTD ", "zh-CN", 2),
    TWD("TWD", "新台币", "TWD ", "zh-CN", 2),
    TZS("TZS", "坦桑尼亚先令", "TZS ", "zh-CN", 2),
    UAH("UAH", "乌克兰格里夫纳", "UAH ", "zh-CN", 2),
    UGX("UGX", "乌干达先令", "UGX ", "zh-CN", 0),
    UYU("UYU", "乌拉圭比索", "UYU ", "zh-CN", 2),
    UZS("UZS", "乌兹别克斯坦苏姆", "UZS ", "zh-CN", 2),
    VES("VES", "委内瑞拉玻利瓦尔", "VES ", "zh-CN", 2),
    VND("VND", "越南盾", "VND ", "zh-CN", 0),
    VUV("VUV", "瓦努阿图瓦图", "VUV ", "zh-CN", 0),
    WST("WST", "萨摩亚塔拉", "WST ", "zh-CN", 2),
    XAF("XAF", "中非法郎", "XAF ", "zh-CN", 0),
    XCD("XCD", "东加勒比元", "XCD ", "zh-CN", 2),
    XCG("XCG", "加勒比盾", "XCG ", "zh-CN", 2),
    XOF("XOF", "西非法郎", "XOF ", "zh-CN", 0),
    XPF("XPF", "太平洋法郎", "XPF ", "zh-CN", 0),
    YER("YER", "也门里亚尔", "YER ", "zh-CN", 2),
    ZAR("ZAR", "南非兰特", "ZAR ", "zh-CN", 2),
    ZMW("ZMW", "赞比亚克瓦查", "ZMW ", "zh-CN", 2),
    ZWG("ZWG", "津巴布韦金元", "ZWG ", "zh-CN", 2);
    // END GENERATED CURRENCY CATALOG

    val noFractionDigits: Boolean
        get() = minorUnitDigits == 0

    companion object {
        val Default: CurrencyCode = CNY

        fun fromStorageKey(value: String?): CurrencyCode {
            if (value.isNullOrBlank()) return Default
            val normalized = value.trim().uppercase()
            return entries.firstOrNull { it.storageKey == normalized } ?: Default
        }

        /**
         * 严格解析（PR#255 R7-2）：仅支持集内的 storageKey 得币种；null/blank/未知码归 null，
         * 不做 [fromStorageKey] 的静默 [Default] 回落。写路径（解析/校验/裁决）一律用本变体 ——
         * 未知 record 币种落 CNY 解析会把零小数币种的 "1200" 放大成 120000 minor（100×）。
         */
        fun fromStorageKeyOrNull(value: String?): CurrencyCode? {
            if (value.isNullOrBlank()) return null
            val normalized = value.trim().uppercase()
            return entries.firstOrNull { it.storageKey == normalized }
        }
    }
}
