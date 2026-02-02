import { ENV } from "./_core/env";

export interface CurrentRmsOpportunity {
  id: string;
  number: string;
  name: string;
  status?: string;
  [key: string]: any;
}

export interface CurrentRmsJobData {
  id: string;
  jobNumber: string;
  jobTitle: string;
  loadDate?: Date;
  loadTime?: string;
  status?: string;
}

/**
 * Fetch opportunities (jobs) from Current-RMS API
 * Fetches jobs for the next 7 days using the specified view
 */
export async function fetchCurrentRmsOpportunities(page = 1, perPage = 48): Promise<CurrentRmsOpportunity[]> {
  const apiKey = process.env.CURRENT_RMS_API_KEY;
  const subdomain = process.env.CURRENT_RMS_SUBDOMAIN;

  if (!apiKey || !subdomain) {
    throw new Error("Current-RMS API credentials not configured");
  }

  try {
    // Use the correct endpoint with view_id for next 7 days jobs
    const url = `https://${subdomain}.current-rms.com/opportunities?page=${page}&per_page=${perPage}&view_id=1000067`;
    const response = await fetch(url, {
      method: "GET",
      headers: {
        "X-API-KEY": apiKey,
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      throw new Error(
        `Current-RMS API error: ${response.status} ${response.statusText}`
      );
    }

    const data = await response.json();
    return data.data || data || [];
  } catch (error) {
    console.error("Error fetching from Current-RMS API:", error);
    throw error;
  }
}

/**
 * Fetch a single opportunity by ID
 */
export async function fetchCurrentRmsOpportunityById(
  id: string
): Promise<CurrentRmsOpportunity | null> {
  const apiKey = process.env.CURRENT_RMS_API_KEY;
  const subdomain = process.env.CURRENT_RMS_SUBDOMAIN;

  if (!apiKey || !subdomain) {
    throw new Error("Current-RMS API credentials not configured");
  }

  try {
    const url = `https://${subdomain}.current-rms.com/opportunities/${id}`;
    const response = await fetch(url, {
      method: "GET",
      headers: {
        "X-API-KEY": apiKey,
        "Content-Type": "application/json",
      },
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
    return data.data || data || null;
  } catch (error) {
    console.error(`Error fetching opportunity ${id} from Current-RMS API:`, error);
    throw error;
  }
}

/**
 * Parse Current-RMS opportunity data into standardized job format
 */
export function parseOpportunityToJobData(
  opp: CurrentRmsOpportunity
): CurrentRmsJobData {
  // Extract load date and time from opportunity
  // This assumes Current-RMS stores these in specific fields
  // Adjust field names based on your Current-RMS setup
  let loadDate: Date | undefined;
  let loadTime: string | undefined;

  // Try to parse load date from various possible field names
  const possibleDateFields = [
    "load_date",
    "loadDate",
    "load_datetime",
    "loadDateTime",
    "start_date",
    "startDate",
  ];

  for (const field of possibleDateFields) {
    if (opp[field]) {
      const parsed = new Date(opp[field]);
      if (!isNaN(parsed.getTime())) {
        loadDate = parsed;
        break;
      }
    }
  }

  // Try to extract time from various possible field names
  const possibleTimeFields = [
    "load_time",
    "loadTime",
    "time",
    "start_time",
    "startTime",
  ];

  for (const field of possibleTimeFields) {
    if (opp[field]) {
      loadTime = String(opp[field]);
      break;
    }
  }

  return {
    id: String(opp.id),
    jobNumber: opp.number || String(opp.id),
    jobTitle: opp.name || "",
    loadDate,
    loadTime,
    status: opp.status || "pending",
  };
}

/**
 * Test Current-RMS API connection
 */
export async function testCurrentRmsConnection(): Promise<boolean> {
  try {
    const opportunities = await fetchCurrentRmsOpportunities();
    return Array.isArray(opportunities);
  } catch (error) {
    console.error("Current-RMS connection test failed:", error);
    return false;
  }
}
