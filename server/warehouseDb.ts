import { eq, and } from "drizzle-orm";
import {
  warehouseAreas,
  areaJobMappings,
  displaySettings,
  jobCache,
  type WarehouseArea,
  type AreaJobMapping,
  type DisplaySettings,
  type JobCache,
} from "../drizzle/schema";
import { getDb } from "./db";

/**
 * Get all active warehouse areas
 */
export async function getAllAreas(): Promise<WarehouseArea[]> {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  return db
    .select()
    .from(warehouseAreas)
    .where(eq(warehouseAreas.isActive, 1));
}

/**
 * Get a single area by ID
 */
export async function getAreaById(areaId: number): Promise<WarehouseArea | null> {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  const result = await db
    .select()
    .from(warehouseAreas)
    .where(eq(warehouseAreas.id, areaId))
    .limit(1);

  return result.length > 0 ? result[0] : null;
}

/**
 * Create a new warehouse area
 */
export async function createArea(data: {
  name: string;
  displayName: string;
  description?: string;
}): Promise<WarehouseArea> {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  await db.insert(warehouseAreas).values({
    name: data.name,
    displayName: data.displayName,
    description: data.description,
    isActive: 1,
  });

  // Get the newly created area
  const areas = await db
    .select()
    .from(warehouseAreas)
    .where(eq(warehouseAreas.name, data.name))
    .orderBy(warehouseAreas.id)
    .limit(1);

  if (areas.length === 0) throw new Error("Failed to create area");
  const area = areas[0];

  // Create default display settings for this area
  await db.insert(displaySettings).values({
    areaId: area.id,
    refreshIntervalSeconds: 30,
    theme: "dark",
    fontSize: "xlarge",
  });

  return area;
}

/**
 * Update a warehouse area
 */
export async function updateArea(
  areaId: number,
  data: Partial<{
    name: string;
    displayName: string;
    description: string;
    isActive: number;
  }>
): Promise<WarehouseArea | null> {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  await db
    .update(warehouseAreas)
    .set(data)
    .where(eq(warehouseAreas.id, areaId));

  return getAreaById(areaId);
}

/**
 * Get all job mappings for an area
 */
export async function getAreaJobMappings(areaId: number): Promise<AreaJobMapping[]> {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  return db
    .select()
    .from(areaJobMappings)
    .where(and(eq(areaJobMappings.areaId, areaId), eq(areaJobMappings.isActive, 1)))
    .orderBy(areaJobMappings.sortOrder);
}

/**
 * Add a job to an area
 */
export async function addJobToArea(data: {
  areaId: number;
  currentRmsJobId: string;
  currentRmsJobNumber: string;
  sortOrder?: number;
}): Promise<AreaJobMapping> {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  await db.insert(areaJobMappings).values({
    areaId: data.areaId,
    currentRmsJobId: data.currentRmsJobId,
    currentRmsJobNumber: data.currentRmsJobNumber,
    sortOrder: data.sortOrder || 0,
    isActive: 1,
  });

  // Get the newly created mapping
  const mappings = await db
    .select()
    .from(areaJobMappings)
    .where(
      and(
        eq(areaJobMappings.areaId, data.areaId),
        eq(areaJobMappings.currentRmsJobId, data.currentRmsJobId)
      )
    )
    .orderBy(areaJobMappings.id)
    .limit(1);

  if (mappings.length === 0) throw new Error("Failed to create job mapping");
  return mappings[0];
}

/**
 * Remove a job from an area
 */
export async function removeJobFromArea(mappingId: number): Promise<void> {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  await db
    .update(areaJobMappings)
    .set({ isActive: 0 })
    .where(eq(areaJobMappings.id, mappingId));
}

/**
 * Get display settings for an area
 */
export async function getDisplaySettings(areaId: number): Promise<DisplaySettings | null> {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  const result = await db
    .select()
    .from(displaySettings)
    .where(eq(displaySettings.areaId, areaId))
    .limit(1);

  return result.length > 0 ? result[0] : null;
}

/**
 * Update display settings for an area
 */
export async function updateDisplaySettings(
  areaId: number,
  data: Partial<{
    refreshIntervalSeconds: number;
    theme: "light" | "dark";
    showLoadTime: number;
    showJobNumber: number;
    showJobTitle: number;
    fontSize: "small" | "medium" | "large" | "xlarge";
  }>
): Promise<DisplaySettings | null> {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  await db
    .update(displaySettings)
    .set(data)
    .where(eq(displaySettings.areaId, areaId));

  return getDisplaySettings(areaId);
}

/**
 * Get cached job data
 */
export async function getCachedJob(jobId: string): Promise<JobCache | null> {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  const result = await db
    .select()
    .from(jobCache)
    .where(eq(jobCache.currentRmsJobId, jobId))
    .limit(1);

  return result.length > 0 ? result[0] : null;
}

/**
 * Cache job data
 */
export async function cacheJobData(data: {
  currentRmsJobId: string;
  jobNumber: string;
  jobTitle?: string;
  clientName?: string;
  loadDate?: Date;
  loadTime?: string;
  status?: string;
  rawData?: string;
}): Promise<JobCache> {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  // Set cache expiry to 5 minutes from now
  const expiresAt = new Date(Date.now() + 5 * 60 * 1000);

  const existing = await getCachedJob(data.currentRmsJobId);

  if (existing) {
    await db
      .update(jobCache)
      .set({
        jobNumber: data.jobNumber,
        jobTitle: data.jobTitle,
        clientName: data.clientName,
        loadDate: data.loadDate,
        loadTime: data.loadTime,
        status: data.status,
        rawData: data.rawData,
        lastFetched: new Date(),
        expiresAt,
      })
      .where(eq(jobCache.currentRmsJobId, data.currentRmsJobId));

    const updated = await getCachedJob(data.currentRmsJobId);
    if (!updated) throw new Error("Failed to update cache");
    return updated;
  } else {
    const result = await db.insert(jobCache).values({
      currentRmsJobId: data.currentRmsJobId,
      jobNumber: data.jobNumber,
      jobTitle: data.jobTitle,
      clientName: data.clientName,
      loadDate: data.loadDate,
      loadTime: data.loadTime,
      status: data.status,
      rawData: data.rawData,
      lastFetched: new Date(),
      expiresAt,
    });

    const cached = await getCachedJob(data.currentRmsJobId);
    if (!cached) throw new Error("Failed to cache job");
    return cached;
  }
}
