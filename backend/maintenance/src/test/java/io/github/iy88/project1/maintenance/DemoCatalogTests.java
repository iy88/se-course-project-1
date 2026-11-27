package io.github.iy88.project1.maintenance;

import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;
import javax.imageio.ImageIO;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class DemoCatalogTests {

    @Test
    void fixtureReferencesAndPackagedAssetsAreCoherent() throws Exception {
        Set<String> accounts = DemoCatalog.ACCOUNTS.stream()
                .map(DemoCatalog.Account::key)
                .collect(Collectors.toSet());
        assertThat(accounts).hasSize(DemoCatalog.ACCOUNTS.size());

        Map<String, DemoCatalog.Product> products = DemoCatalog.PRODUCTS.stream()
                .collect(Collectors.toMap(DemoCatalog.Product::key, Function.identity()));
        assertThat(products).hasSize(DemoCatalog.PRODUCTS.size()).hasSize(24);
        Set<String> assets = new HashSet<>();
        for (var product : DemoCatalog.PRODUCTS) {
            assertThat(accounts).contains(product.seller());
            assertThat(product.category()).isNotBlank();
            assertThat(assets.add(product.asset())).as(product.asset()).isTrue();
            assertThat(ImageIO.read(new ByteArrayInputStream(SeedSupport.readAsset(product.asset()))))
                    .as(product.asset()).isNotNull();
        }
        assertThat(ImageIO.read(new ByteArrayInputStream(
                SeedSupport.readAsset(SeedSupport.DEMO_EVIDENCE.getFirst().name())))).isNotNull();

        for (var trade : DemoCatalog.TRADES) {
            assertThat(products).containsKey(trade.product());
            assertThat(accounts).contains(trade.buyer());
            for (var message : trade.messages()) {
                if (message.sender() != null) {
                    assertThat(accounts).contains(message.sender());
                }
            }
        }
        for (var chat : DemoCatalog.CHATS) {
            assertThat(accounts).contains(chat.left(), chat.right());
            for (var message : chat.messages()) {
                assertThat(accounts).contains(message.sender());
            }
        }
        assertThat(DemoCatalog.COMMENTS).filteredOn(DemoCatalog.Comment::deleted).hasSize(1);
    }

    @Test
    void rendersTheChatEvidenceAsARealPng() throws Exception {
        byte[] png = DemoChatEvidence.render(DemoCatalog.POWERBANK_CHAT, DemoCatalog.ACCOUNTS);
        BufferedImage image = ImageIO.read(new ByteArrayInputStream(png));

        assertThat(image).isNotNull();
        assertThat(image.getWidth()).isEqualTo(840);
        assertThat(image.getHeight()).isEqualTo(370);
        assertThat(png).startsWith(0x89, 0x50, 0x4e, 0x47);
    }
}
