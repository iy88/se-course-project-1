package io.github.iy88.project1.api;

import org.springframework.context.annotation.Configuration;
import org.springframework.http.MediaType;
import org.springframework.http.converter.HttpMessageConverters;
import org.springframework.web.servlet.config.annotation.ContentNegotiationConfigurer;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration(proxyBeanMethods = false)
class ApiWebConfiguration implements WebMvcConfigurer {

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
