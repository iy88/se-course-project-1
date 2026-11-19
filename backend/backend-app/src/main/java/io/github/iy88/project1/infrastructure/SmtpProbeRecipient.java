package io.github.iy88.project1.infrastructure;

import jakarta.mail.internet.AddressException;
import jakarta.mail.internet.InternetAddress;
import org.springframework.boot.ApplicationArguments;

public record SmtpProbeRecipient(String address) {

    public static SmtpProbeRecipient from(ApplicationArguments arguments) {
        var values = arguments.getOptionValues("smtp-probe-to");
        if (values == null || values.size() != 1 || values.getFirst().isBlank()) {
            throw new IllegalArgumentException("Provide exactly one --smtp-probe-to=<email> for the dependency probe");
        }
        try {
            var address = new InternetAddress(values.getFirst(), true);
            address.validate();
            if (!address.isGroup()) {
                return new SmtpProbeRecipient(address.getAddress());
            }
        } catch (AddressException invalidAddress) {
            // Keep the supplied address out of the error message.
        }
        throw new IllegalArgumentException("--smtp-probe-to must contain one valid email address");
    }
}
