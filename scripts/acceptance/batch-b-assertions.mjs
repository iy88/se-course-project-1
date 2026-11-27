#!/usr/bin/env node
/**
 * Batch B supplementary assertions (API + PostgreSQL) for the catalogue,
 * interaction and conversation items: B01, B05, B08, B10, B13, B14, B17, B18.
 *
 * Reads no credentials from the repository. The API account password comes from
 * ACCEPTANCE_PASSWORD; PostgreSQL connects through the standard PG* variables.
 *
 * See scripts/acceptance/README.md for the required fixture state and an example
 * command. The script is repeatable: idempotency keys include a run suffix and
 * the fixtures it mutates (favourites, aliases, category links) settle to the
 * same observable state.
 */

import { appendFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

const BASE = process.env.ACCEPTANCE_API_BASE ?? "http://127.0.0.1:8080/api/v1";
const ORIGIN = process.env.ACCEPTANCE_WEB_ORIGIN ?? "http://127.0.0.1:3001";
const PASSWORD = process.env.ACCEPTANCE_PASSWORD;
const LOG = process.env.ACCEPTANCE_LOG ?? "";
const ACCOUNTS = {
  buyerA: process.env.ACCEPTANCE_BUYER_A ?? "acceptance-buyer-a@local.test",
  buyerB: process.env.ACCEPTANCE_BUYER_B ?? "acceptance-buyer-b@local.test",
  seller: process.env.ACCEPTANCE_SELLER ?? "acceptance-seller@local.test",
  manager: process.env.ACCEPTANCE_MANAGER ?? "acceptance-manager-a@local.test",
};

// Fixture identifiers from the report's "测试账户与基础数据" table.
const FX = {
  favoriteProduct: 4,
  multiCategoryProduct: 4,
  multiCategories: [4, 7],
  singleCategory: 6,
  correctionCase: 5,
  tradeCategoryProduct: 2,
  trade: 2,
  conflictCategory: 4,
  aliasCategory: 4,
  aliasName: "幂等别名",
  associatedCategory: 6,
  nonSellerProduct: 1,
  nonSellerComment: 1,
  deletedComment: 9,
  tradeConversation: 2,
};

if (!PASSWORD) {
  console.error("ACCEPTANCE_PASSWORD is required (test account password, not committed).");
  process.exit(2);
}

function sql(query) {
  let run = spawnSync("psql", ["-tAc", query], { encoding: "utf8" });
  if (run.error) {
    // Windows workstations usually run the acceptance database in Docker without a local psql.
    const container = process.env.ACCEPTANCE_PG_CONTAINER ?? "project1-pg";
    run = spawnSync("docker", ["exec", "-i",
      "-e", `PGPASSWORD=${process.env.PGPASSWORD ?? ""}`,
      container, "psql",
      "-U", process.env.PGUSER ?? "postgres",
      "-d", process.env.PGDATABASE ?? "project1_acceptance",
      "-tAc", query], { encoding: "utf8" });
    if (run.error) {
      console.error("psql (or docker with ACCEPTANCE_PG_CONTAINER) is required.");
      console.error(run.error.message);
      process.exit(2);
    }
  }
  if (run.status !== 0) throw new Error(run.stderr || "psql failed");
  return run.stdout.trim();
}

const RUN = Date.now();
const results = [];

function check(item, name, ok, detail = "") {
  results.push({ item, ok });
  const line = `${ok ? "PASS" : "FAIL"} | ${item} | ${name}${detail ? " | " + detail : ""}`;
  console.log(line);
  if (LOG) appendFileSync(LOG, line + "\n");
}

async function login(email) {
  const entryResponse = await fetch(`${BASE}/account/entry-context`);
  const entryCookies = entryResponse.headers.getSetCookie().map((cookie) => cookie.split(";")[0]);
  const entry = await entryResponse.json();
  const response = await fetch(`${BASE}/account/session`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": entry.csrf_token,
      Origin: ORIGIN,
      Cookie: entryCookies.join("; "),
    },
    body: JSON.stringify({ email, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed for ${email}: ${response.status}`);
  const cookies = response.headers.getSetCookie().map((cookie) => cookie.split(";")[0]);
  return {
    cookies: cookies.join("; "),
    csrf: cookies.find((cookie) => cookie.startsWith("__Host-se_csrf=")).split("=")[1],
  };
}

async function call(user, method, path, body, key) {
  const headers = { Cookie: user.cookies, Origin: ORIGIN, "X-CSRF-Token": user.csrf };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (key) headers["Idempotency-Key"] = `${key}-${RUN}`;
  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return { status: response.status, json: await response.json().catch(() => null) };
}

const hashOf = (table, idColumn, id) =>
  sql(`select md5(row_to_json(t)::text) from ${table} t where t.${idColumn} = ${id}`);

if (LOG) {
  appendFileSync(LOG, `# 自动化补充断言 ${new Date().toISOString()}（目标 build main@5bbe4f0e，库 ${process.env.PGDATABASE ?? "project1_acceptance"}）\n`);
}

const buyerA = await login(ACCOUNTS.buyerA);
const buyerB = await login(ACCOUNTS.buyerB);
const seller = await login(ACCOUNTS.seller);
const manager = await login(ACCOUNTS.manager);

// ---------------- B05 收藏 ----------------
const productBefore = hashOf("product", "product_id", FX.favoriteProduct);
const firstFavorite = await call(buyerA, "PUT", `/me/favorites/${FX.favoriteProduct}`, undefined, "ev-fav-1");
const duplicateFavorite = await call(buyerA, "PUT", `/me/favorites/${FX.favoriteProduct}`, undefined, "ev-fav-2");
check("B05", "重复收藏返回首次时间",
  firstFavorite.status === 200 && duplicateFavorite.status === 200
    && firstFavorite.json.favorited_at === duplicateFavorite.json.favorited_at,
  `${firstFavorite.json?.favorited_at} == ${duplicateFavorite.json?.favorited_at}`);
const favoriteRows = sql(
  `select count(*) from product_favorite where account_id = 4 and product_id = ${FX.favoriteProduct}`);
check("B05", "同一账户与商品只有一条收藏记录", favoriteRows === "1", `rows=${favoriteRows}`);
await call(buyerA, "DELETE", `/me/favorites/${FX.favoriteProduct}`, undefined, "ev-fav-cancel");
await call(buyerA, "PUT", `/me/favorites/${FX.favoriteProduct}`, undefined, "ev-fav-3");
const productAfter = hashOf("product", "product_id", FX.favoriteProduct);
check("B05", "取消后重新收藏仍一条且商品不变", favoriteRows === "1" && productBefore === productAfter,
  `product_hash_equal=${productBefore === productAfter}`);

// ---------------- B01 多分类 AND ----------------
const correction4 = await call(manager, "POST", `/admin/products/${FX.multiCategoryProduct}/category-correction`,
  { category_ids: FX.multiCategories.map(String), reason: "多分类组合验证",
    basis_ref: { type: "case", id: String(FX.correctionCase) } }, "ev-correction-1");
check("B01", "商品可挂多个分类（前置）", correction4.status === 200, `status=${correction4.status}`);
const bothCategories = await call(buyerA, "GET",
  `/products?category_ids=${FX.multiCategories[0]}&category_ids=${FX.multiCategories[1]}&page_size=50`);
const mismatchCategories = await call(buyerA, "GET",
  `/products?category_ids=${FX.multiCategories[0]}&category_ids=${FX.singleCategory}&page_size=50`);
check("B01", "同时选择两个分类只返回全部命中的商品", bothCategories.status === 200
  && (bothCategories.json.items ?? []).some((item) => item.id === String(FX.multiCategoryProduct)),
  `total=${bothCategories.json?.total}`);
check("B01", "只命中一个分类时不返回", mismatchCategories.status === 200
  && !(mismatchCategories.json.items ?? []).some((item) => item.id === String(FX.multiCategoryProduct)),
  `total=${mismatchCategories.json?.total}`);
const activeLinks = sql(
  `select count(*) from product_category where product_id = ${FX.multiCategoryProduct} and removed_at is null`);
check("B01", "数据库分类关联数量正确", activeLinks === String(FX.multiCategories.length), `links=${activeLinks}`);

// ---------------- B08 非卖方回复与删除保留 ----------------
const nonSellerReply = await call(buyerB, "POST",
  `/products/${FX.nonSellerProduct}/comments/${FX.nonSellerComment}/replies`, { body: "非卖方回复" }, "ev-reply-buyer-b");
check("B08", "非卖方回复被拒绝",
  nonSellerReply.status === 403 && nonSellerReply.json?.error?.code === "COMMENT_REPLY_NOT_ALLOWED",
  `status=${nonSellerReply.status} code=${nonSellerReply.json?.error?.code}`);
const deletedComment = sql(
  `select (deleted_at is not null)::text || '|' || body from product_comment where comment_id = ${FX.deletedComment}`);
check("B08", "作者删除后记录保留、不再公开", deletedComment === "true|8", deletedComment);

// ---------------- B10 发送推进本人已读 ----------------
const send = await call(seller, "POST", `/conversations/trade/${FX.tradeConversation}/messages`,
  { body: "已读进度验证" }, "ev-send-1");
const sellerBranches = await call(seller, "GET", "/conversations");
const sellerTrade2 = (sellerBranches.json.items ?? []).flatMap((item) => item.branches ?? [])
  .find((branch) => branch.conversation_kind === "trade" && branch.conversation_id === String(FX.tradeConversation));
check("B10", "发送后本人该分支未读为 0", send.status < 300 && sellerTrade2?.unread_count === 0,
  `send=${send.status} unread=${sellerTrade2?.unread_count}`);
const buyerBranches = await call(buyerB, "GET", "/conversations");
const buyerTrade2 = (buyerBranches.json.items ?? []).flatMap((item) => item.branches ?? [])
  .find((branch) => branch.conversation_kind === "trade" && branch.conversation_id === String(FX.tradeConversation));
check("B10", "接收方同一分支有未读", buyerTrade2?.unread_count >= 1, `unread=${buyerTrade2?.unread_count}`);
const buyerMessages = await call(buyerB, "GET", `/conversations/trade/${FX.tradeConversation}/messages`);
const lastSeq = (buyerMessages.json?.items ?? []).at(-1)?.seq ?? 0;
const markRead = await call(buyerB, "POST", `/conversations/trade/${FX.tradeConversation}/read-progress`,
  { displayed_seq: lastSeq }, "ev-read-1");
check("B10", "提交已读进度成功", markRead.status < 300, `status=${markRead.status} seq=${lastSeq}`);
const buyerAfterRead = await call(buyerB, "GET", "/conversations");
const buyerTrade2After = (buyerAfterRead.json.items ?? []).flatMap((item) => item.branches ?? [])
  .find((branch) => branch.conversation_kind === "trade" && branch.conversation_id === String(FX.tradeConversation));
check("B10", "查看后该分支未读归零", buyerTrade2After?.unread_count === 0, `unread=${buyerTrade2After?.unread_count}`);

// ---------------- B13 名称冲突与身份不变 ----------------
const categoryBefore = hashOf("category", "category_id", FX.conflictCategory);
const conflict = await call(manager, "POST", "/admin/categories", { name: "教材资料" }, "ev-conflict-1");
check("B13", "重复名称创建返回 409",
  conflict.status === 409 && conflict.json?.error?.code === "CATEGORY_NAME_CONFLICT",
  `status=${conflict.status} code=${conflict.json?.error?.code}`);
const categoryAfter = hashOf("category", "category_id", FX.conflictCategory);
check("B13", "冲突后分类身份与归属不变", categoryBefore === categoryAfter, `equal=${categoryBefore === categoryAfter}`);

// ---------------- B14 重复移除别名 ----------------
const aliasList = await call(manager, "GET", "/admin/categories?page=1&page_size=50");
const aliasCategory = (aliasList.json.items ?? []).find((item) => item.id === String(FX.aliasCategory));
let alias = (aliasCategory?.names ?? [])
  .find((name) => name.name === FX.aliasName && name.kind === "alias" && name.active);
if (!alias) {
  const createdAlias = await call(manager, "POST", `/admin/categories/${FX.aliasCategory}/aliases`,
    { name: FX.aliasName }, "ev-alias-create");
  alias = createdAlias.json ? { category_name_id: createdAlias.json.category_name_id } : undefined;
}
const firstRemoval = await call(manager, "DELETE",
  `/admin/categories/${FX.aliasCategory}/aliases/${alias?.category_name_id}`, undefined, "ev-alias-1");
const aliasAfterFirst = sql(
  `select (deactivated_at is not null)::text || '|' || deactivated_at from category_name where category_name_id = ${alias?.category_name_id}`);
const secondRemoval = await call(manager, "DELETE",
  `/admin/categories/${FX.aliasCategory}/aliases/${alias?.category_name_id}`, undefined, "ev-alias-2");
const aliasAfterSecond = sql(
  `select (deactivated_at is not null)::text || '|' || deactivated_at from category_name where category_name_id = ${alias?.category_name_id}`);
check("B14", "重复移除同一别名均幂等且保留历史",
  !!alias && firstRemoval.status === 204 && secondRemoval.status === 204
    && aliasAfterFirst === aliasAfterSecond,
  `first=${firstRemoval?.status} second=${secondRemoval?.status} same=${aliasAfterFirst === aliasAfterSecond}`);

// ---------------- B18 曾关联计数（在 B17 改变关联前采集） ----------------
const associated = (aliasList.json.items ?? []).find((item) => item.id === String(FX.associatedCategory))
  ?.associated_product_count;
const associatedRows = sql(
  `select count(*) from product_category where category_id = ${FX.associatedCategory}`);
check("B18", "管理端曾关联计数与数据库一致", String(associated) === associatedRows,
  `list=${associated} db=${associatedRows}`);

// ---------------- B17 交易中纠类与交易快照不变 ----------------
const tradeHashBefore = hashOf("trade", "id", FX.trade);
const snapshotHashBefore = hashOf("trade_purchase_product_snapshot", "trade_id", FX.trade);
const tradeStateBefore = sql(`select status || '|' || version || '|' || coalesce(active_agreement_id::text,'null') || '|' || coalesce(ended_at::text,'null') from trade where id = ${FX.trade}`);
const versionBefore = Number(sql(`select content_version from product where product_id = ${FX.tradeCategoryProduct}`));
// Alternate the link set so a rerun still changes the row and bumps the content version.
const currentLinks = sql(`select string_agg(category_id::text, ',' order by category_id) from product_category where product_id = ${FX.tradeCategoryProduct} and removed_at is null`);
const targetLinks = currentLinks === String(FX.multiCategories[0])
  ? FX.multiCategories
  : [FX.multiCategories[0]];
const correction2 = await call(manager, "POST", `/admin/products/${FX.tradeCategoryProduct}/category-correction`,
  { category_ids: targetLinks.map(String), reason: "交易中纠类验证",
    basis_ref: { type: "case", id: String(FX.trade) } }, "ev-correction-2");
const versionAfter = Number(sql(`select content_version from product where product_id = ${FX.tradeCategoryProduct}`));
const tradeHashAfter = hashOf("trade", "id", FX.trade);
const snapshotHashAfter = hashOf("trade_purchase_product_snapshot", "trade_id", FX.trade);
const tradeStateAfter = sql(`select status || '|' || version || '|' || coalesce(active_agreement_id::text,'null') || '|' || coalesce(ended_at::text,'null') from trade where id = ${FX.trade}`);
check("B17", "交易中商品可纠类且版本递增",
  correction2.status === 200 && versionAfter === versionBefore + 1,
  `status=${correction2.status} version ${versionBefore}->${versionAfter}`);
check("B17", "交易状态、约定与历史快照不变", tradeStateBefore === tradeStateAfter
  && tradeHashBefore === tradeHashAfter && snapshotHashBefore === snapshotHashAfter,
  `state=${tradeStateAfter} trade_same=${tradeHashBefore === tradeHashAfter} snapshot_same=${snapshotHashBefore === snapshotHashAfter}`);

const failed = results.filter((result) => !result.ok);
if (LOG) appendFileSync(LOG, `# SUMMARY total=${results.length} pass=${results.length - failed.length} fail=${failed.length}\n`);
console.log(`SUMMARY total=${results.length} pass=${results.length - failed.length} fail=${failed.length}`);
if (failed.length) process.exitCode = 1;
