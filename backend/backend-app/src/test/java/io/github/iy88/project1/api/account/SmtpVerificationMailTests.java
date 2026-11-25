package io.github.iy88.project1.api.account;

import io.github.iy88.project1.infrastructure.SmtpDelivery;
import java.util.Map;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.support.StaticListableBeanFactory;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class SmtpVerificationMailTests {
    @ParameterizedTest
    @CsvSource({
            "email_change_old,当前邮箱验证码,这个地址是账号当前绑定的邮箱,新邮箱验证码",
            "email_change_new,新邮箱验证码,这个地址是本次申请绑定的新邮箱,当前邮箱验证码"
    })
    void distinguishesTheMailboxRoles(String purpose, String field, String role, String otherField) {
        var delivery = mock(SmtpDelivery.class);
        var beans = new StaticListableBeanFactory(Map.of("smtpDelivery", delivery));
        var mail = new SmtpVerificationMail(beans.getBeanProvider(SmtpDelivery.class));
        var body = ArgumentCaptor.forClass(String.class);

        mail.sendCode("receiver@example.test", purpose, "123456", 600);

        verify(delivery).send(eq("receiver@example.test"), eq("校园二手交易 | 更换登录邮箱：" + field), body.capture());
        assertThat(body.getValue())
                .contains(role, "「" + field + "」栏", "123456", "10 分钟", "请忽略此邮件", "请勿向他人透露验证码")
                .doesNotContain(otherField);
    }
}
