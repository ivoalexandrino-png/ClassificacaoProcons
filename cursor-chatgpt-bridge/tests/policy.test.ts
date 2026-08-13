import { describe, expect, it } from "vitest";
import { evaluateInstruction } from "../src/security/policy.js";
import { bearerAuth } from "../src/security/auth.js";

describe("security policy", () => {
  it("should block dangerous actions without explicit authorization", () => {
    expect(evaluateInstruction("run terraform destroy")).toMatchObject({
      allowed: false, requiresExplicitAuthorization: true
    });
  });

  it("should allow normal coding instructions", () => {
    expect(evaluateInstruction("add a regression test and run lint")).toEqual({
      allowed: true, requiresExplicitAuthorization: false
    });
  });

  it("should accept only the configured bearer token", () => {
    const middleware = bearerAuth("correct-token-1234");
    const invoke = (authorization?: string) => {
      let status = 0;
      let nextCalled = false;
      middleware(
        { header: () => authorization } as never,
        { status: (code: number) => { status = code; return { json: () => undefined }; } } as never,
        () => { nextCalled = true; }
      );
      return { status, nextCalled };
    };
    expect(invoke()).toEqual({ status: 401, nextCalled: false });
    expect(invoke("Bearer wrong-token-123")).toEqual({ status: 401, nextCalled: false });
    expect(invoke("Bearer correct-token-1234")).toEqual({ status: 0, nextCalled: true });
  });
});
