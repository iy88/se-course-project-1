package io.github.iy88.project1.api;

import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.MediaType;
import org.springframework.http.converter.HttpMessageConverters;
import org.springframework.web.servlet.config.annotation.ContentNegotiationConfigurer;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(CsrfGuard.Origins.class)
public class ApiWebConfiguration implements WebMvcConfigurer {
    private final CsrfGuard csrfGuard;

    public ApiWebConfiguration(CsrfGuard.Origins origins, ObjectProvider<CsrfGuard.Verifier> verifier) {
        this.csrfGuard = new CsrfGuard(origins, verifier);
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(csrfGuard).addPathPatterns("/api/v1/**");
    }

    @Override
    public void configureContentNegotiation(ContentNegotiationConfigurer configurer) {
        configurer.defaultContentType(MediaType.APPLICATION_JSON);
    }

    @Override
    public void configureMessageConverters(HttpMessageConverters.ServerBuilder builder) {
        // The OSS SDK needs XML on the classpath for its own protocol.
        builder.configureMessageConvertersList(converters -> converters.removeIf(converter ->
                converter.getSupportedMediaTypes().stream().anyMatch(mediaType -> {
                    String subtype = mediaType.getSubtype();
                    return subtype.equals("xml") || subtype.endsWith("+xml");
                })));
    }
}
