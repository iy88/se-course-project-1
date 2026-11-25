import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { peerAccountId, peerName, rememberPeer } from "./conversation-directory";

describe("conversation peer directory", () => {
  it("keeps the account id while the display name is refreshed", () => {
    rememberPeer("trade", "directory-test", "旧名字", "42");
    assert.equal(peerName("trade", "directory-test"), "旧名字");
    assert.equal(peerAccountId("trade", "directory-test"), "42");

    rememberPeer("trade", "directory-test", "新名字");
    assert.equal(peerName("trade", "directory-test"), "新名字");
    assert.equal(peerAccountId("trade", "directory-test"), "42");
  });

  it("does not expose a peer id for an unknown branch", () => {
    assert.equal(peerName("chat", "missing"), null);
    assert.equal(peerAccountId("chat", "missing"), null);
  });
});
