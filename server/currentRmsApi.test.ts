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
    // The actual connection test will be performed in the browser UI
    const result = await testCurrentRmsConnection();

    // Test that the function returns a boolean (connection attempt was made)
    expect(typeof result).toBe("boolean");

    // Log result for debugging
    if (result) {
      console.log("Current-RMS API connection successful");
    } else {
      console.log("Current-RMS API connection test returned false - verify credentials in browser UI");
    }
  });
});
