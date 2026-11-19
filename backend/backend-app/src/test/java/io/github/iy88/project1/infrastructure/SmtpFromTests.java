package io.github.iy88.project1.infrastructure;

import jakarta.mail.internet.InternetAddress;
import org.junit.jupiter.api.Test;
import org.springframework.mail.javamail.JavaMailSenderImpl;
import org.springframework.mail.javamail.MimeMailMessage;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SmtpFromTests {

    @Test
    void preservesDisplayNameInTheMimeFromHeader() throws Exception {
        var settings = smtp("CampusMarket-V2 Dev <example@example.com>");
        var message = new MimeMailMessage(new JavaMailSenderImpl().createMimeMessage());
        message.setFrom(settings.from());

        assertThat(message.getMimeMessage().getFrom()).singleElement()
                .isInstanceOfSatisfying(InternetAddress.class, address -> {
                    assertThat(address.getAddress()).isEqualTo("example@example.com");
                    assertThat(address.getPersonal()).isEqualTo("CampusMarket-V2 Dev");
                });
    }

    @Test
    void rejectsMultipleMailboxesAndGroups() {
        assertThatThrownBy(() -> smtp("one@example.com, two@example.com"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> smtp("Dev: example@example.com;"))
                .isInstanceOf(IllegalArgumentException.class);
    }

    private static ExternalProbeProperties.Smtp smtp(String from) {
        return new ExternalProbeProperties.Smtp("smtp.example.com", 587,
                ExternalProbeProperties.TlsMode.STARTTLS, "example@example.com", "placeholder", from);
    }
}
