package io.github.iy88.project1.product.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.ProductSettings;
import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.persistence.FileReferences;
import io.github.iy88.project1.storage.persistence.FileRegistry;
import io.github.iy88.project1.storage.persistence.UploadRegistration;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * Writes the image references owned by a product. Creation attaches the submitted images; an edit
 * releases the current references and attaches the replacement set. Both operations join the
 * caller's product write transaction, so a rejected file rolls the product change back.
 */
final class ProductImageReferences {
    private final FileReferences fileReferences;
    private final ProductSettings settings;

    ProductImageReferences(FileReferences fileReferences, ProductSettings settings) {
        this.fileReferences = fileReferences;
        this.settings = settings;
    }

    /** Attaches images submitted with a new product, keeping the submitted order. */
    void attachImages(long productId, long sellerId, List<String> values) {
        List<Long> ids = parseFileIds(values);
        if (ids.isEmpty()) {
            return;
        }
        if (ids.size() > settings.imageMaxCount()) {
            throw new BusinessError("INPUT_INVALID", 422, "图片数量超出限制");
        }
        try {
            fileReferences.attach(sellerId, new UploadRegistration.Target("product", productId),
                    FilePurpose.PRODUCT_IMAGE, ids, "image");
        } catch (FileRegistry.Rejected rejected) {
            throw fileError(rejected.getMessage());
        }
    }

    /** Replaces the current images and retains the released references as product history. */
    void replaceImages(long productId, long sellerId, List<String> values) {
        List<Long> ids = parseFileIds(values);
        if (ids.size() > settings.imageMaxCount()) {
            throw new BusinessError("INPUT_INVALID", 422, "图片数量超出限制");
        }
        var target = new UploadRegistration.Target("product", productId);
        var current = fileReferences.current(target, "image");
        if (!current.isEmpty()) {
            fileReferences.release(target,
                    current.stream().map(FileReferences.Reference::referenceId).toList(),
                    new FileReferences.RetentionBasis("product_image_replaced", Set.of("s2-v1"), null, Set.of()));
        }
        if (!ids.isEmpty()) {
            try {
                fileReferences.attach(sellerId, target, FilePurpose.PRODUCT_IMAGE, ids, "image");
            } catch (FileRegistry.Rejected rejected) {
                throw fileError(rejected.getMessage());
            }
        }
    }

    private static BusinessError fileError(String code) {
        return switch (code) {
            case "RESOURCE_NOT_VISIBLE" -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "文件不存在");
            case "FILE_PURPOSE_MISMATCH" -> new BusinessError("FILE_PURPOSE_MISMATCH", 422, "文件用途不符");
            case "FILE_NOT_REFERENCEABLE" -> new BusinessError("FILE_NOT_REFERENCEABLE", 409, "文件尚未核验");
            default -> new BusinessError("INPUT_INVALID", 422, "文件不可用");
        };
    }

    private static List<Long> parseFileIds(List<String> values) {
        if (values == null) {
            return List.of();
        }
        List<Long> ids = new ArrayList<>();
        for (String value : values) {
            try {
                long id = Long.parseLong(value);
                if (id <= 0) {
                    throw new NumberFormatException();
                }
                ids.add(id);
            } catch (NumberFormatException invalid) {
                throw new BusinessError("INPUT_INVALID", 422, "文件标识无效");
            }
        }
        return ids;
    }
}
