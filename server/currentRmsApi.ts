export interface CurrentRmsOpportunity {
  id: string | number;
  number: string;
  name?: string;
  description?: string;
  status?: string;
  deliver_starts_at?: string;
  deliver_ends_at?: string;
  load_starts_at?: string;
  load_ends_at?: string;
  member?: {
    name?: string;
    id?: number;
  };
  [key: string]: any;
}

export interface CurrentRmsJobData {
  id: string;
  jobNumber: string;
  jobTitle: string;
  clientName?: string;
  loadDate?: Date;
  loadTime?: string;
  status?: string;
}

const API_BASE = "https://api.current-rms.com/api/v1";

/**
 * Get headers for Current-RMS API requests
 * Uses X-AUTH-TOKEN and X-SUBDOMAIN headers
 */
function getHeaders(): Record<string, string> {
  const apiKey = process.env.CURRENT_RMS_API_KEY;
  const subdomain = process.env.CURRENT_RMS_SUBDOMAIN;

  if (!apiKey || !subdomain) {
    throw new Error("Current-RMS API credentials not configured");
  }

  return {
    "X-AUTH-TOKEN": apiKey,
    "X-SUBDOMAIN": subdomain,
    "Accept": "application/json",
  };
}

/**
 * Fetch opportunities (jobs) from Current-RMS API
 * Fetches jobs for the next 7 days using the specified view
 */
export async function fetchCurrentRmsOpportunities(
  page = 1,
  perPage = 48
): Promise<CurrentRmsOpportunity[]> {
  try {
    const headers = getHeaders();
    const url = `${API_BASE}/opportunities?page=${page}&per_page=${perPage}&view_id=1000067`;

    console.log(`[Current-RMS API] Fetching opportunities from: ${url}`);

    const response = await fetch(url, {
      method: "GET",
      headers,
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error(
        `[Current-RMS API] Error ${response.status}: ${errorText.substring(0, 200)}`
      );
      throw new Error(
        `Current-RMS API error: ${response.status} ${response.statusText}`
      );
    }

    const data = await response.json();
    const opportunities = data.opportunities || [];
    console.log(`[Current-RMS API] Successfully fetched ${opportunities.length} opportunities`);
    return opportunities;
  } catch (error) {
    console.error("[Current-RMS API] Error fetching opportunities:", error);
    throw error;
  }
}

/**
 * Fetch a single opportunity by ID
 */
export async function fetchCurrentRmsOpportunityById(
  id: string | number
): Promise<CurrentRmsOpportunity | null> {
  try {
    const headers = getHeaders();
    const url = `${API_BASE}/opportunities/${id}`;

    const response = await fetch(url, {
      method: "GET",
      headers,
    });

    if (!response.ok) {
      if (response.status === 404) {
        return null;
      }
      throw new Error(
        `Current-RMS API error: ${response.status} ${response.statusText}`
      );
    }

    const data = await response.json();
    return data.opportunity || data || null;
  } catch (error) {
    console.error(`[Current-RMS API] Error fetching opportunity ${id}:`, error);
    throw error;
  }
}

/**
 * Parse Current-RMS opportunity data into standardized job format
 * Uses deliver_starts_at as the primary load date field
 */
export function parseOpportunityToJobData(
  opp: CurrentRmsOpportunity
): CurrentRmsJobData {
  let loadDate: Date | undefined;
  let loadTime: string | undefined;

  // Use deliver_starts_at as the primary date field
  if (opp.deliver_starts_at) {
    const parsed = new Date(opp.deliver_starts_at);
    if (!isNaN(parsed.getTime())) {
      loadDate = parsed;
      // Extract time from the datetime
      loadTime = parsed.toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
      });
    }
  }

  // Fallback to load_starts_at if deliver_starts_at is not available
  if (!loadDate && opp.load_starts_at) {
    const parsed = new Date(opp.load_starts_at);
    if (!isNaN(parsed.getTime())) {
      loadDate = parsed;
      loadTime = parsed.toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
      });
    }
  }

  return {
    id: String(opp.id),
    jobNumber: opp.number || String(opp.id),
    jobTitle: opp.description || opp.name || "",
    clientName: opp.member?.name || "",
    loadDate,
    loadTime,
    status: opp.status || "pending",
  };
}

/**
 * Test Current-RMS API connection
 */
export async function testCurrentRmsConnection(): Promise<{
  success: boolean;
  error?: string;
}> {
  try {
    const headers = getHeaders();
    const url = `${API_BASE}/opportunities?page=1&per_page=1&view_id=1000067`;

    console.log("[Current-RMS API] Testing connection...");

    const response = await fetch(url, {
      method: "GET",
      headers,
    });

    if (response.status === 200) {
      console.log("[Current-RMS API] Connection test successful");
      return { success: true };
    }

    if (response.status === 401) {
      console.error("[Current-RMS API] Authentication failed (401)");
      return {
        success: false,
        error: "Invalid API Key or Subdomain. Please check your credentials.",
      };
    }

    const errorText = await response.text();
    console.error(
      `[Current-RMS API] Connection test failed: ${response.status} - ${errorText}`
    );
    return {
      success: false,
      error: `API returned status ${response.status}`,
    };
  } catch (error: any) {
    console.error("[Current-RMS API] Connection test error:", error);
    return {
      success: false,
      error: error.message || "Network or API error",
    };
  }
}
