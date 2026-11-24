package io.github.iy88.project1.api.account;

import io.github.iy88.project1.account.application.VerificationMail;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.infrastructure.SmtpDelivery;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

@Component
@Profile("infrastructure & !dependency-probe")
class SmtpVerificationMail implements VerificationMail {
    private final ObjectProvider<SmtpDelivery> delivery;

    SmtpVerificationMail(ObjectProvider<SmtpDelivery> delivery) {
        this.delivery = delivery;
    }

    @Override
    public void sendCode(String recipient, String purpose, String code, long ttlSeconds) {
        SmtpDelivery smtp = delivery.getIfAvailable();
        if (smtp == null) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "邮件服务暂不可用");
        }
        String action = switch (purpose) {
            case "email_change_old" -> "更换登录邮箱：当前邮箱验证码";
            case "email_change_new" -> "更换登录邮箱：新邮箱验证码";
            case "registration" -> "注册验证码";
            case "password_reset" -> "重置密码验证码";
            default -> "邮箱验证码";
        };
        String instruction = switch (purpose) {
            case "email_change_old" -> "这个地址是账号当前绑定的邮箱。请将下方验证码填入「当前邮箱验证码」栏。\n\n";
            case "email_change_new" -> "这个地址是本次申请绑定的新邮箱。请将下方验证码填入「新邮箱验证码」栏。\n\n";
            default -> "";
        };
        smtp.send(recipient, "校园二手交易 | " + action,
                instruction + "验证码：" + code + "，" + Math.max(1, ttlSeconds / 60) + " 分钟内有效。\n\n"
                        + "如果这不是您本人发起的操作，或此邮件与您无关，请忽略此邮件。请勿向他人透露验证码。");
    }
}
