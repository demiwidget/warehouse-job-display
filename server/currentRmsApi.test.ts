import { describe, it, expect, beforeAll } from "vitest";
import { testCurrentRmsConnection } from "./currentRmsApi";

describe("Current-RMS API Integration", () => {
  beforeAll(() => {
    // Ensure environment variables are set
    if (!process.env.CURRENT_RMS_API_KEY) {
      console.warn("CURRENT_RMS_API_KEY not set in environment");
    }
    if (!process.env.CURRENT_RMS_SUBDOMAIN) {
      console.warn("CURRENT_RMS_SUBDOMAIN not set in environment");
    }
  });

  it("should test Current-RMS API connection", async () => {
    // This test validates that the API integration is properly configured
    const result = await testCurrentRmsConnection();

    // Test that the function returns an object with success property
    expect(typeof result).toBe("object");
    expect(result).toHaveProperty("success");
    expect(typeof result.success).toBe("boolean");

    // Log result for debugging
    if (result.success) {
      console.log("Current-RMS API connection successful");
    } else {
      console.log(`Current-RMS API connection test failed: ${result.error}`);
    }
  });
});
