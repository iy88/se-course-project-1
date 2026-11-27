package io.github.iy88.project1.maintenance;

import java.util.List;

/** Coherent demo business catalog. Content is fictional and uses the current UI's data shapes. */
final class DemoCatalog {
    private DemoCatalog() {
    }

    record Account(String key, String displayName, String role) {
    }

    record Product(String key, String seller, String title, String description, long priceCents,
                   String state, String asset, String category, double daysAgo, String review,
                   String reason, boolean claimed, List<String> extraCategories, boolean restricted) {
    }

    record Message(String sender, String body) {
    }

    record Trade(String key, String product, String buyer, String status, double daysAgo,
                 Double acceptedDaysAgo, Double finishedDaysAgo, boolean agreement,
                 String confirmation, boolean frozen, String freezeReason, Integer rating, String review,
                 String cancelReason, List<Message> messages) {
    }

    record Chat(String key, String left, String right, double daysAgo, List<Message> messages) {
    }

    record Comment(String product, String author, String body, double daysAgo, String replyTo,
                   boolean deleted) {
    }

    static final List<Account> ACCOUNTS = List.of(
            new Account("seller", "计科23级·陈子航", "user"),
            new Account("seller2", "建筑20级·罗文博", "user"),
            new Account("seller3", "生物23级·吴桐", "user"),
            new Account("buyer", "汉语言22级·林晓雨", "user"),
            new Account("buyer2", "机械21级·赵一鸣", "user"),
            new Account("buyer3", "新闻22级·孙可", "user"),
            new Account("outsider", "视觉传达23级·何佳", "user"),
            new Account("frozen_seller", "电子22级·郑博", "user"),
            new Account("frozen_buyer", "数学23级·许安", "user"));

    static final List<Product> PRODUCTS = List.of(
            new Product("lamp_pending", "seller", "宿舍护眼台灯 三档调光",
                    "大二买的护眼台灯，用了两年，灯罩边缘有一处约一厘米的磕碰，三档亮度和触控都正常；附原装电源线和说明书。标价 45 元，毕业前想出掉，周三、周五傍晚可在东区 3 号宿舍楼下自取，价格可小刀。",
                    4500, "pending_review", "product_lamp_pending_demo.jpg", "生活家居", 2, "pending", null, false,
                    List.of(), false),
            new Product("keyboard_pending", "seller", "87 键红轴机械键盘 带备用键帽",
                    "自用 87 键机械键盘，红轴，2024 年 9 月购入，键帽有轻微打油，按键和灯效全部正常；附拔键器、备用键帽和 Type-C 线。168 元，最近换了静音键盘所以出，周末下午可在图书馆南门当面验货。",
                    16800, "pending_review", "product_mechanical_keyboard.jpg", "数码电子", 1.5, "pending", null, true,
                    List.of(), false),
            new Product("camera_rejected", "seller2", "富士胶片相机 带原装背带",
                    "富士胶片相机，2019 年购入，快门外壳有划痕，镜头内有少量灰尘但不影响成像，测光去年保养过；附原装背带和相机包。520 元，想换微单故出，可在西区食堂门口试机。",
                    52000, "review_rejected", "product_camera.jpg", "数码电子", 10, "rejected",
                    "图片未展示镜头内部情况，请补充近照并说明快门与测光是否正常", true, List.of(), false),
            new Product("shelf_withdrawn", "seller3", "四层简易书架 可拆搬",
                    "宿舍用四层简易书架，2023 年双十一购入，左边一根横杆有轻微变形，不影响放书；可拆成两块搬走。原价 129，现 60 元出，不含其他配件，需自提，周六上午在 7 号宿舍楼下。",
                    6000, "off_shelf", "product_four_tier_bookshelf.jpg", "生活家居", 14, "withdrawn", null, false,
                    List.of(), false),
            new Product("monitor_pending", "seller2", "27 寸 2K 显示器 带 HDMI 线",
                    "27 寸 2K 显示器，2023 年 3 月购入，屏幕无坏点，底座有正常使用痕迹；附 HDMI 线和电源适配器。420 元，因换 4K 屏出，可约周三晚在 7 号宿舍楼大厅试机亮屏。",
                    42000, "pending_review", "product_monitor.jpg", "数码电子", 9, "pending", null, false,
                    List.of(), false),
            new Product("textbook", "seller", "《数据结构（C 语言版）》第 2 版",
                    "《数据结构（C 语言版）》第 2 版，2024 年秋季学期用过一学期，扉页姓名已涂掉，内页有少量铅笔笔记，无缺页；附课程实验指导册。15 元，周三中午在第三教学楼门口交付。",
                    1500, "public", "product_textbook.jpg", "教材书籍", 26, "passed", null, false, List.of(), false),
            new Product("folding_bike", "seller3", "20 寸折叠自行车 带车锁",
                    "20 寸折叠自行车，2023 年购入，通勤用约一年半，链条上月刚上油，后刹车皮磨损需更换（已如实说明）；附车锁和打气筒。折叠后可进电梯，320 元，周末白天可在南门车棚看车。",
                    32000, "public", "product_folding_bike.jpg", "骑行装备", 20, "passed", null, false, List.of(), false),
            new Product("racket", "seller", "尤尼克斯羽毛球拍 4U",
                    "尤尼克斯羽毛球拍，4U 规格，2024 年 5 月购入，拍框有一处掉漆，拉线 24 磅仍可用；附拍套和手胶。因为改打网球出，120 元，周二傍晚在体育馆门口试拍。",
                    12000, "public", "product_badminton_racket.jpg", "运动户外", 18, "passed", null, false, List.of(), false),
            new Product("organizer", "seller", "桌面三层收纳架 带抽屉",
                    "桌面收纳架，2024 年 3 月购入，三层结构，右侧抽屉滑轨有点涩但能正常开合；附安装螺丝。25 元，周一下午在图书馆门口交付。",
                    2500, "public", "product_desk_organizer.jpg", "生活家居", 12, "passed", null, false, List.of(), false),
            new Product("mountain_bike", "seller", "捷安特山地车 后胎新换",
                    "捷安特山地车，2022 年购入，骑了约三年，车架右后侧有掉漆，变速和刹车正常，后胎上月新换；附车锁、尾灯。因毕业出，560 元，可约周三 18:30 在图书馆门口看车。",
                    56000, "public", "product_mountain_bike.jpg", "骑行装备", 16, "passed", null, false, List.of(), false),
            new Product("kindle", "seller2", "Kindle Paperwhite 4 带保护套",
                    "Kindle Paperwhite 4，2021 年购入，屏幕无划痕，电池续航约一周；附原装保护套和充电线。320 元，周四晚在西门快递点附近交付。",
                    32000, "public", "product_kindle_demo.jpg", "数码电子", 15, "passed", null, false, List.of(), false),
            new Product("rice_cooker", "seller", "美的 3L 电饭煲 带蒸笼",
                    "美的 3L 电饭煲，2022 年购入，内胆有使用划痕但不粘涂层完好，附量杯和蒸笼。已换新锅，70 元，周六中午在 5 号宿舍楼下自提。",
                    7000, "off_shelf", "product_rice_cooker_demo.jpg", "生活家居", 45, "passed", null, false, List.of(), false),
            new Product("powerbank", "seller2", "20000mAh 充电宝 带收纳袋",
                    "20000mAh 充电宝，2023 年购入，外壳有轻微鼓包，仍能充电；附收纳袋。90 元，周三下午可在 5 号宿舍楼下自提，因换了新充电宝出。",
                    9000, "public", "product_swollen_powerbank.jpg", "数码电子", 30, "passed", null, false, List.of(), true),
            new Product("projector", "seller3", "极米投影仪 带遥控器",
                    "极米投影仪，2022 年购入，灯泡亮度有衰减，白天需拉窗帘；附遥控器和 HDMI 线。480 元，周日下午可在 7 号宿舍楼大厅试投。",
                    48000, "public", "product_projector_demo.jpg", "数码电子", 22, "passed", null, false, List.of(), false),
            new Product("headphones", "seller", "索尼降噪耳机 带收纳盒",
                    "索尼降噪耳机，2023 年购入，耳罩有轻微掉皮，降噪和蓝牙正常；附收纳盒和音频线。220 元，周三下午在图书馆门口交付。",
                    22000, "public", "product_headphones.jpg", "数码电子", 9, "passed", null, false, List.of(), false),
            new Product("blender", "seller", "九阳榨汁机 带两个随行杯",
                    "九阳榨汁机，2022 年购入，杯体有使用痕迹，刀头可拆洗；附两个随行杯。55 元，周末在宿舍楼下自提。",
                    5500, "public", "product_blender_demo.jpg", "生活家居", 13, "passed", null, false, List.of(), false),
            new Product("speaker", "seller2", "JBL 蓝牙音箱 带充电线",
                    "JBL 蓝牙音箱，2023 年购入，网罩有一处小凹，连接和续航正常；附充电线。130 元，周五傍晚在操场看台交付。",
                    13000, "public", "product_speaker_demo.jpg", "数码电子", 11, "passed", null, false, List.of(), false),
            new Product("chair", "seller", "人体工学椅 带腰靠",
                    "人体工学椅，2023 年购入，坐垫有正常使用痕迹，气压杆上月更换；附头枕和腰靠。350 元，需自提，周日下午在 3 号宿舍楼下。",
                    35000, "off_shelf", "product_chair_demo.jpg", "生活家居", 18, "passed", null, false, List.of(), false),
            new Product("tripod", "frozen_seller", "曼富图三脚架 带收纳袋",
                    "曼富图三脚架，2022 年购入，云台有轻微磨损，脚管锁紧正常；附收纳袋。140 元，周日下午在操场交付。",
                    14000, "in_trade", "product_tripod_demo.jpg", "数码电子", 20, "passed", null, false, List.of(), false),
            new Product("stand", "seller2", "显示器气弹簧支架 带垫片",
                    "显示器支架，2023 年购入，气弹簧正常，夹桌垫片齐全；附内六角扳手。85 元，周六下午在宿舍楼下交付。",
                    8500, "in_trade", "product_stand_demo.jpg", "数码电子", 21, "passed", null, false, List.of(), false),
            new Product("air_fryer", "seller3", "空气炸锅 3L 带烤架",
                    "空气炸锅 3L，2023 年购入，内胆有使用划痕，加热正常；附烤架。210 元，周六中午在 7 号宿舍楼下自提。",
                    21000, "in_trade", "product_air_fryer_demo.jpg", "生活家居", 19, "passed", null, false, List.of(), false),
            new Product("kettle", "seller3", "电热水壶 1.5L",
                    "电热水壶 1.5L，2023 年购入，烧水正常，壶身有轻微水垢；附底座。45 元，周二下午在宿舍楼下交付。",
                    4500, "in_trade", "product_kettle_demo.jpg", "生活家居", 10, "passed", null, false, List.of(), false),
            new Product("usb_hub", "seller3", "七合一 Type-C 扩展坞",
                    "七合一 Type-C 扩展坞，2023 年购入，接口正常，外壳有轻微划痕；附收纳袋。75 元，周四中午在图书馆门口交付。",
                    7500, "in_trade", "product_usb_hub_demo.jpg", "数码电子", 14, "passed", null, false, List.of(), false),
            new Product("bookshelf_recovered", "seller3", "实木两层小书架 可自提",
                    "实木两层小书架，2022 年购入，边角有磕碰，结构稳固；无其他配件，需自提。55 元，周日下午在 7 号宿舍楼下。",
                    5500, "in_trade", "product_bookshelf_recovered_demo.jpg", "生活家居", 24, "passed", null, false,
                    List.of(), false));

    static final List<Trade> TRADES = List.of(
            new Trade("trade_completed", "chair", "buyer2", "completed", 26, 25.5, 20.0, true, "both", false, null,
                    5, "椅子很稳，卖家按约定时间搬下来，交易顺利。", null,
                    List.of(new Message("buyer2", "椅子还在吗？周日下午 3 号楼下可以吗？"),
                            new Message("seller", "在，周日 15:00，我带工具帮你拆。"),
                            new Message(null, "卖方已接受该购买请求，交易进入进行中。"),
                            new Message("seller", "按 350、周日 15:00 提约定。"),
                            new Message("buyer2", "周日 15:00 可以，我准时到。"),
                            new Message("buyer2", "已拿到椅子并付款，谢谢。"),
                            new Message("seller", "收到，交易完成。"))),
            new Trade("trade_tripod", "tripod", "frozen_buyer", "in_progress", 10, 9.5, null, true, "one", false,
                    null, null, null, null,
                    List.of(new Message("frozen_buyer", "三脚架还在吗？周日下午操场可以吗？"),
                            new Message("frozen_seller", "在，周日 16:00 操场东门。"),
                            new Message(null, "卖方已接受该购买请求，交易进入进行中。"),
                            new Message("frozen_seller", "按 140、周日 16:00 提约定。"),
                            new Message("frozen_buyer", "确认，我到了先付款。"))),
            new Trade("trade_stand_frozen", "stand", "buyer3", "in_progress", 8, 7.5, null, true, "one", true,
                    "买方反映商品与描述不符，管理员核查期间冻结交易", null, null, null,
                    List.of(new Message("buyer3", "支架还在吗？周六下午宿舍楼下可以吗？"),
                            new Message("seller2", "在，周六 15:00。"),
                            new Message(null, "卖方已接受该购买请求，交易进入进行中。"),
                            new Message("seller2", "按 85、周六 15:00 提约定。"),
                            new Message("buyer3", "底座有裂纹，和图片不一样。"),
                            new Message(null, "管理员已冻结本笔交易，双方操作暂停，等待核查。"))),
            new Trade("trade_airfryer", "air_fryer", "buyer", "in_progress", 6, 5.5, null, true, "none", false,
                    null, null, null, null,
                    List.of(new Message("buyer", "空气炸锅还在吗？周六中午自提。"),
                            new Message("seller3", "在，周六 12:00 7 号楼下。"),
                            new Message(null, "卖方已接受该购买请求，交易进入进行中。"),
                            new Message("seller3", "按 210、周六 12:00 提约定。"),
                            new Message("buyer", "周六 12:00 没问题，我准时到。"))),
            new Trade("trade_kettle", "kettle", "buyer", "in_progress", 4, 3.5, null, false, "none", false,
                    null, null, null, null,
                    List.of(new Message("buyer", "水壶还在吗？周二下午可以吗？"),
                            new Message("seller3", "在，周二 16:00。"),
                            new Message(null, "卖方已接受该购买请求，交易进入进行中。"),
                            new Message("buyer", "我还没想好时间，先不约定。"))),
            new Trade("trade_usbhub", "usb_hub", "buyer2", "in_progress", 5, 4.5, null, true, "one", false,
                    null, null, null, null,
                    List.of(new Message("buyer2", "扩展坞还在吗？周四中午图书馆门口可以吗？"),
                            new Message("seller3", "在，12:30。"),
                            new Message(null, "卖方已接受该购买请求，交易进入进行中。"),
                            new Message("seller3", "按 75、周四 12:30 提约定。"),
                            new Message("buyer2", "周四 12:30 图书馆门口，没问题。"))),
            new Trade("trade_bookshelf", "bookshelf_recovered", "buyer", "in_progress", 6, 5.5, null, true, "one",
                    false, null, null, null, null,
                    List.of(new Message("buyer", "书架还在吗？周日下午 7 号楼下。"),
                            new Message("seller3", "在，周日 16:00。"),
                            new Message(null, "卖方已接受该购买请求，交易进入进行中。"),
                            new Message("seller3", "按 55、周日 16:00 提约定。"),
                            new Message("buyer", "可以，我借个小推车。"))));

    static final Chat POWERBANK_CHAT = new Chat("chat_powerbank", "outsider", "seller2", 9,
            List.of(new Message("outsider", "请问充电宝外壳鼓起来了吗？"),
                    new Message("seller2", "右侧有一点鼓包，充电功能还在。"),
                    new Message("outsider", "了解，我先不买了。")));

    static final List<Chat> CHATS = List.of(POWERBANK_CHAT,
            new Chat("chat_seller_buyer", "seller", "buyer", 3,
                    List.of(new Message("buyer", "台灯周三傍晚还能在东区 3 号楼下看吗？"),
                            new Message("seller", "可以，18:30 我下课回来，到了给你发消息。"),
                            new Message("buyer", "好，我带了现金，价格按 45。"))),
            new Chat("chat_seller2_buyer3", "seller2", "buyer3", 2,
                    List.of(new Message("buyer3", "Kindle 是 8G 还是 32G？"),
                            new Message("seller2", "8G 版本，背面型号 PQ94WIF，晚上补图。"))));

    static final List<Comment> COMMENTS = List.of(
            new Comment("mountain_bike", "buyer", "车架右后侧的掉漆面积大吗？周三 18:30 能在图书馆门口看车吗？", 4, null, false),
            new Comment("mountain_bike", "seller", "掉漆大概一枚硬币大小，不影响结构；周三 18:30 可以，我提前五分钟到。", 3.8, "mountain_bike#1", false),
            new Comment("mountain_bike", "buyer2", "后胎是什么牌子的？", 3, null, false),
            new Comment("kindle", "buyer3", "是 8G 还是 32G 版本？能拍一下背面的型号吗？", 5, null, false),
            new Comment("kindle", "seller2", "8G 版本，背面型号是 PQ94WIF，晚上回去补图。", 4.8, "kindle#1", false),
            new Comment("kindle", "buyer2", "这个价格不如去买新的，楼主自己留着吧。", 4.2, null, true));
}
