/*
 * Registers the TypeScript resolve hook so `node --test` can execute the
 * application's `.test.ts` files with no additional dependency. Node strips types
 * natively; only module resolution needs help.
 */
import { register } from "node:module";

register("./ts-resolve.mjs", import.meta.url);
