package io.github.iy88.project1.api.trade;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.notification.application.NotificationApplication;
import io.github.iy88.project1.notification.application.NotificationIntent;
import io.github.iy88.project1.notification.application.NotificationSourcePort;
import io.github.iy88.project1.trade.application.TradeApplication;
import io.github.iy88.project1.trade.application.TradePorts;
import java.time.Clock;
import java.util.Map;
import java.util.Optional;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
class TradeNotificationConfiguration {
    @Bean
    TradePorts.Notifications tradeNotifications(NotificationApplication notifications, Clock clock) {
        return (transaction, eventId, eventType, tradeId, recipients) -> notifications.createNotifications(transaction,
                new NotificationIntent(recipients, eventId, eventType, new ResourceRef("trade", tradeId),
                        eventType + ":" + eventId, eventType, "1", Map.of("trade_id", Long.toString(tradeId)),
                        clock.instant()));
    }

    @Bean
    NotificationSourcePort tradeNotificationSource(TradeApplication trades) {
        return (context, facts) -> {
            if (!"trade".equals(facts.source().type()) || context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
                return Optional.empty();
            }
            long accountId = Long.parseLong(context.actorId());
            return trades.notificationContext(facts.source().id(), accountId).map(trade -> {
                var copy = TradeNotice.forEvent(facts.eventType());
                String body = copy.body();
                if ("trade.request_created".equals(facts.eventType())
                        && trade.requestNote() != null && !trade.requestNote().isBlank()) {
                    body += "\n\n买家留言\n" + trade.requestNote();
                }
                return new NotificationSourcePort.NotificationSourceView(copy.summary(), facts.source(),
                        trade.productTitle(), body);
            });
        };
    }

    private record TradeNotice(String summary, String body) {
        private static TradeNotice forEvent(String eventType) {
            return switch (eventType) {
                case "trade.request_created" -> new TradeNotice("收到购买请求",
                        "买家提交了购买请求。你可以前往交易详情查看请求及当前可用操作。");
                case "trade.request_accepted" -> new TradeNotice("购买请求已接受",
                        "卖家接受了你的购买请求。你可以前往交易详情查看交付约定及当前可用操作。");
                case "trade.request_rejected" -> new TradeNotice("购买请求被拒绝",
                        "卖家拒绝了这笔购买请求，该请求已结束。");
                case "trade.request_withdrawn" -> new TradeNotice("购买请求已撤回",
                        "买家撤回了购买请求，该请求已结束。");
                case "trade.request_closed" -> new TradeNotice("购买请求已关闭",
                        "系统关闭了这笔购买请求。你可以前往交易详情查看关闭记录。");
                case "trade.agreement_proposed" -> new TradeNotice("收到交易约定",
                        "对方提出了交易约定。前往交易详情可查看约定的时间、地点、交付和付款方式。");
                case "trade.agreement_change_proposed" -> new TradeNotice("收到约定修改",
                        "对方提出修改交易约定。新的约定需经确认后生效，具体变更可在交易详情查看。");
                case "trade.agreement_confirmed" -> new TradeNotice("交易约定已生效",
                        "对方接受了交易约定。交易详情保留了生效的时间、地点、交付和付款安排。");
                case "trade.agreement_rejected" -> new TradeNotice("交易约定被拒绝",
                        "对方拒绝了这次约定提议。你可以在交易会话继续沟通，在交易详情查看约定记录。");
                case "trade.agreement_withdrawn" -> new TradeNotice("交易约定已撤回",
                        "对方撤回了这次约定提议。你可以在交易详情查看已有约定和可用操作。");
                case "trade.completion_confirmed" -> new TradeNotice("对方已确认完成",
                        "对方已提交完成确认。如果你已完成交付或收货，可以前往交易详情查看并确认。");
                case "trade.completed" -> new TradeNotice("交易已完成",
                        "双方已确认完成这笔交易，关联商品已下架。你可以前往交易详情查看完成记录。");
                case "trade.cancellation_requested" -> new TradeNotice("收到取消申请",
                        "对方申请取消这笔交易。前往交易详情可查看申请内容和可用操作。");
                case "trade.cancellation_rejected" -> new TradeNotice("取消申请被拒绝",
                        "对方拒绝了取消交易的申请。你可以前往交易详情查看处理记录。");
                case "trade.cancellation_withdrawn" -> new TradeNotice("取消申请已撤回",
                        "对方撤回了取消交易的申请。你可以前往交易详情查看当前进度。");
                case "trade.terminated" -> new TradeNotice("交易已取消",
                        "这笔交易已取消，关联商品已下架。你可以前往交易详情查看结束记录。");
                case "trade.frozen" -> new TradeNotice("交易已冻结",
                        "这笔交易进入冻结处理。你可以前往交易详情查看冻结信息及当前可用操作。");
                case "trade.unfrozen" -> new TradeNotice("一项交易冻结已解除",
                        "这笔交易的冻结记录有一项已解除。你可以前往交易详情查看当前可用操作。");
                case "trade.adjusted" -> new TradeNotice("管理员已调整交易",
                        "管理员已作出处理决定并调整交易状态。你可以前往交易详情查看处理结果。");
                case "trade.restored" -> new TradeNotice("交易已恢复进行",
                        "管理员已将异常交易恢复为进行中。你可以前往交易详情继续跟进。");
                case "trade.dispute_resolved" -> new TradeNotice("交易争议已处理",
                        "管理员已解决这笔交易的争议。你可以前往交易详情查看处理后的交易安排。");
                case "trade.timeout" -> new TradeNotice("交易完成确认超时",
                        "一方提交完成确认后，另一方未在期限内确认，交易进入异常处理。");
                default -> new TradeNotice("交易状态有更新", "你可以前往交易详情查看状态和处理记录。");
            };
        }
    }
}
