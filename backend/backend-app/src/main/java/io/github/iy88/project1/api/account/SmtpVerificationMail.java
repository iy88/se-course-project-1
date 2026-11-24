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
    public void sendCode(String recipient, String code, long ttlSeconds) {
        SmtpDelivery smtp = delivery.getIfAvailable();
        if (smtp == null) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "邮件服务暂不可用");
        }
        smtp.send(recipient, "Project1 验证码",
                "你的验证码是 " + code + "，" + Math.max(1, ttlSeconds / 60) + " 分钟内有效。");
    }
}
