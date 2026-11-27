package io.github.iy88.project1.maintenance;

import io.github.iy88.project1.storage.FilePurpose;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Base64;
import java.util.List;
import java.util.Random;

/** Deterministic content, asset and JSON helpers shared by the load and demo seeds. */
final class SeedSupport {
    private static final List<String> SURNAMES = List.of(
            "陈", "林", "罗", "吴", "赵", "孙", "何", "郑", "许", "马", "唐", "严", "高", "沈", "郭", "秦",
            "叶", "周", "李", "王", "刘", "黄", "徐", "胡", "朱", "杨", "宋", "韩", "邓", "曹");
    private static final List<String> GIVEN = List.of(
            "子航", "晓雨", "一鸣", "可", "佳", "博", "安", "骁", "雨桐", "远", "清", "宁", "川", "青",
            "文博", "桐", "明远", "岚", "思源", "嘉禾", "若溪", "知远", "沐晨", "星野", "书宁", "云帆",
            "亦安", "梓涵", "令仪", "修远", "望舒", "庭安");
    private static final List<String> CONDITIONS = List.of(
            "正常使用痕迹，功能完好", "边角有轻微磕碰，不影响使用", "八成新，配件齐全", "自用一年，已清洁",
            "外观有划痕，按键和接口正常", "闲置较久，功能已测试", "毕业清宿舍，说明书和原包装还在",
            "有正常使用痕迹，已如实拍照");
    private static final List<String> ACCESSORIES = List.of(
            "附原装电源线和说明书", "附收纳袋和备用配件", "附数据线和保护套", "附安装螺丝和工具",
            "无其他配件，需自提", "附原包装和购买记录截图");
    private static final List<String> PLACES = List.of(
            "东区 3 号宿舍楼下", "图书馆南门", "第三教学楼门口", "体育馆门口", "西区食堂门口", "南门车棚");

    static final List<SeedAsset> LOAD_IMAGES = List.of(
            new SeedAsset("product_textbook.jpg", FilePurpose.PRODUCT_IMAGE),
            new SeedAsset("product_headphones.jpg", FilePurpose.PRODUCT_IMAGE),
            new SeedAsset("product_badminton_racket.jpg", FilePurpose.PRODUCT_IMAGE),
            new SeedAsset("product_kettle_demo.jpg", FilePurpose.PRODUCT_IMAGE),
            new SeedAsset("product_lamp_pending_demo.jpg", FilePurpose.PRODUCT_IMAGE),
            new SeedAsset("product_folding_bike.jpg", FilePurpose.PRODUCT_IMAGE),
            new SeedAsset("product_desk_organizer.jpg", FilePurpose.PRODUCT_IMAGE),
            new SeedAsset("product_swollen_powerbank.jpg", FilePurpose.PRODUCT_IMAGE));

    static final List<SeedAsset> DEMO_EVIDENCE = List.of(
            new SeedAsset("evidence_powerbank_swelling.jpg", FilePurpose.CASE_EVIDENCE));

    static final List<String> SEARCH_TERMS = List.of(
            "台灯", "自行车", "教材", "耳机", "球拍", "收纳", "键盘", "显示器", "水壶", "音箱");

    private SeedSupport() {
    }

    static String sha256Hex(String value) {
        return sha256Hex(value.getBytes(StandardCharsets.UTF_8));
    }

    static String sha256Hex(byte[] value) {
        try {
            return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 is unavailable", impossible);
        }
    }

    static String base64(byte[] value) {
        return Base64.getEncoder().encodeToString(value);
    }

    static long mix(long seed, String... values) {
        long result = seed;
        for (String value : values) {
            for (byte part : value.getBytes(StandardCharsets.UTF_8)) {
                result = result * 1_000_003L + part;
            }
        }
        return result;
    }

    static Random random(SeedContext context, String stream) {
        return new Random(mix(context.seed(), context.mode(), context.tag(), stream));
    }

    static String displayName(Random random) {
        return SURNAMES.get(random.nextInt(SURNAMES.size()))
                + GIVEN.get(random.nextInt(GIVEN.size()));
    }

    static String loadTitle(String term, int index) {
        List<String> templates = List.of(
                "校园二手 %s 自用出", "毕业清宿舍 %s 可小刀", "九成新 %s 当面验货", "%s 闲置转让",
                "宿舍自提 %s 配件齐", "%s 低价出 可预约看货");
        return templates.get(index % templates.size()).formatted(term) + " " + (1000 + index);
    }

    static String loadDescription(Random random, String term, int index) {
        return "%s，%s；%s。%s 元，%s可自提或当面交付。商品编号 %d，供联调与容量测试使用。"
                .formatted(term, CONDITIONS.get(random.nextInt(CONDITIONS.size())),
                        ACCESSORIES.get(random.nextInt(ACCESSORIES.size())),
                        10 + random.nextInt(590),
                        PLACES.get(random.nextInt(PLACES.size())), index);
    }

    static byte[] readAsset(String name) {
        if (name == null || !name.matches("[A-Za-z0-9._-]+\\.(jpg|jpeg|png)")) {
            throw new IllegalArgumentException("Invalid seed asset name");
        }
        try (InputStream input = SeedSupport.class.getResourceAsStream("/seed-assets/" + name)) {
            if (input == null) {
                throw new IllegalStateException("Missing packaged seed asset: " + name);
            }
            return input.readAllBytes();
        } catch (IOException failure) {
            throw new IllegalStateException("Unable to read packaged seed asset: " + name, failure);
        }
    }

    static String jsonString(String value) {
        if (value == null) {
            return "null";
        }
        StringBuilder out = new StringBuilder(value.length() + 2).append('"');
        for (int index = 0; index < value.length(); index++) {
            char part = value.charAt(index);
            switch (part) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\b' -> out.append("\\b");
                case '\f' -> out.append("\\f");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (part < 0x20) {
                        out.append("\\u%04x".formatted((int) part));
                    } else {
                        out.append(part);
                    }
                }
            }
        }
        return out.append('"').toString();
    }

    record SeedAsset(String name, FilePurpose purpose, byte[] generatedBytes) {
        SeedAsset(String name, FilePurpose purpose) {
            this(name, purpose, null);
        }

        byte[] bytes() {
            return generatedBytes == null ? readAsset(name) : generatedBytes;
        }

        String contentType() {
            return name.endsWith(".png") ? "image/png" : "image/jpeg";
        }
    }
}
