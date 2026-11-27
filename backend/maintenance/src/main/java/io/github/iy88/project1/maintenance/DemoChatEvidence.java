package io.github.iy88.project1.maintenance;

import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import javax.imageio.ImageIO;

/** Renders the seeded transcript as a fictional case attachment using the conversation view's bubble styles. */
final class DemoChatEvidence {

    static final String NAME = "demo-powerbank-chat.png";

    private DemoChatEvidence() {
    }

    static byte[] render(DemoCatalog.Chat conversation, List<DemoCatalog.Account> accounts) {
        Map<String, String> names = accounts.stream()
                .collect(Collectors.toMap(DemoCatalog.Account::key, DemoCatalog.Account::displayName));
        int width = 840;
        int height = 118 + 84 * conversation.messages().size();
        var image = new BufferedImage(width, height, BufferedImage.TYPE_INT_RGB);
        Graphics2D graphics = image.createGraphics();
        try {
            graphics.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,
                    RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
            graphics.setRenderingHint(RenderingHints.KEY_ANTIALIASING,
                    RenderingHints.VALUE_ANTIALIAS_ON);
            graphics.setColor(Color.WHITE);
            graphics.fillRect(0, 0, width, height);
            graphics.setColor(Color.decode("#223329"));
            graphics.setFont(new Font(Font.SANS_SERIF, Font.BOLD, 23));
            graphics.drawString(names.get(conversation.right()), 30, 40);
            graphics.setFont(new Font(Font.SANS_SERIF, Font.PLAIN, 15));
            graphics.setColor(Color.decode("#50645a"));
            graphics.drawString("演示数据 · 私聊记录", 30, 65);
            graphics.setColor(Color.decode("#dce6de"));
            graphics.drawLine(0, 82, width, 82);
            int top = 102;
            for (var message : conversation.messages()) {
                drawMessage(graphics, width, top, names.get(message.sender()), message.body(),
                        conversation.left().equals(message.sender()));
                top += 84;
            }
        } finally {
            graphics.dispose();
        }
        try (var output = new ByteArrayOutputStream()) {
            if (!ImageIO.write(image, "png", output)) {
                throw new IllegalStateException("PNG writer is unavailable");
            }
            return output.toByteArray();
        } catch (IOException failure) {
            throw new IllegalStateException("Unable to render the demo chat evidence", failure);
        }
    }

    private static void drawMessage(Graphics2D graphics, int width, int top,
                                    String sender, String text, boolean mine) {
        var metadata = new Font(Font.SANS_SERIF, Font.BOLD, 15);
        var body = new Font(Font.SANS_SERIF, Font.PLAIN, 19);
        int bubbleWidth = 34 + Math.max(graphics.getFontMetrics(metadata).stringWidth(sender),
                graphics.getFontMetrics(body).stringWidth(text));
        int left = mine ? width - 30 - bubbleWidth : 30;
        graphics.setColor(Color.decode(mine ? "#e5f3e9" : "#f4f8f5"));
        graphics.fillRoundRect(left, top, bubbleWidth, 68, 12, 12);
        graphics.setColor(Color.decode(mine ? "#cbe3d4" : "#dce6de"));
        graphics.drawRoundRect(left, top, bubbleWidth, 68, 12, 12);
        graphics.setFont(metadata);
        graphics.setColor(Color.decode("#50645a"));
        graphics.drawString(sender, left + 16, top + 24);
        graphics.setFont(body);
        graphics.setColor(Color.decode("#223329"));
        graphics.drawString(text, left + 16, top + 51);
    }
}
