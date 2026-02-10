import { z } from "zod";
import { protectedProcedure, router } from "./_core/trpc";
import {
  getAllAreas,
  getAreaById,
  createArea,
  updateArea,
  getAreaJobMappings,
  addJobToArea,
  removeJobFromArea,
  getDisplaySettings,
  updateDisplaySettings,
  getCachedJob,
  cacheJobData,
} from "./warehouseDb";
import {
  fetchCurrentRmsOpportunities,
  fetchCurrentRmsOpportunityById,
  parseOpportunityToJobData,
  testCurrentRmsConnection,
} from "./currentRmsApi";

export const warehouseRouter = router({
  // Area management
  listAreas: protectedProcedure.query(async () => {
    return getAllAreas();
  }),

  getArea: protectedProcedure.input(z.object({ areaId: z.number() })).query(async ({ input }) => {
    return getAreaById(input.areaId);
  }),

  createArea: protectedProcedure
    .input(
      z.object({
        name: z.string().min(1),
        displayName: z.string().min(1),
        description: z.string().optional(),
      })
    )
    .mutation(async ({ input }) => {
      return createArea(input);
    }),

  updateArea: protectedProcedure
    .input(
      z.object({
        areaId: z.number(),
        name: z.string().optional(),
        displayName: z.string().optional(),
        description: z.string().optional(),
        isActive: z.number().optional(),
      })
    )
    .mutation(async ({ input }) => {
      const { areaId, ...data } = input;
      return updateArea(areaId, data);
    }),

  // Job mappings
  getAreaJobs: protectedProcedure
    .input(z.object({ areaId: z.number() }))
    .query(async ({ input }) => {
      return getAreaJobMappings(input.areaId);
    }),

  addJobToArea: protectedProcedure
    .input(
      z.object({
        areaId: z.number(),
        currentRmsJobId: z.string(),
        currentRmsJobNumber: z.string(),
        sortOrder: z.number().optional(),
      })
    )
    .mutation(async ({ input }) => {
      try {
        const opp = await fetchCurrentRmsOpportunityById(input.currentRmsJobId);
        if (opp) {
          const jobData = parseOpportunityToJobData(opp);
          await cacheJobData({
            currentRmsJobId: jobData.id,
            jobNumber: jobData.jobNumber,
            jobTitle: jobData.jobTitle,
            clientName: jobData.clientName,
            loadDate: jobData.loadDate,
            loadTime: jobData.loadTime,
            status: jobData.status,
            rawData: JSON.stringify(opp),
          });
        }
      } catch (error) {
        console.error("Error fetching job details for caching:", error);
      }
      return addJobToArea(input);
    }),

  removeJobFromArea: protectedProcedure
    .input(z.object({ mappingId: z.number() }))
    .mutation(async ({ input }) => {
      await removeJobFromArea(input.mappingId);
      return { success: true };
    }),

  // Display settings
  getDisplaySettings: protectedProcedure
    .input(z.object({ areaId: z.number() }))
    .query(async ({ input }) => {
      return getDisplaySettings(input.areaId);
    }),

  updateDisplaySettings: protectedProcedure
    .input(
      z.object({
        areaId: z.number(),
        refreshIntervalSeconds: z.number().optional(),
        theme: z.enum(["light", "dark"]).optional(),
        showLoadTime: z.number().optional(),
        showJobNumber: z.number().optional(),
        showJobTitle: z.number().optional(),
        fontSize: z.enum(["small", "medium", "large", "xlarge"]).optional(),
      })
    )
    .mutation(async ({ input }) => {
      const { areaId, ...data } = input;
      return updateDisplaySettings(areaId, data);
    }),

  // Current-RMS integration
  searchCurrentRmsJobs: protectedProcedure
    .input(z.object({ query: z.string().optional() }))
    .query(async ({ input }) => {
      try {
        const opportunities = await fetchCurrentRmsOpportunities();

        // Filter by query if provided
        let filtered = opportunities;
        if (input.query) {
          const q = input.query.toLowerCase();
          filtered = opportunities.filter(
            (opp) =>
              opp.name?.toLowerCase().includes(q) ||
              opp.number?.toLowerCase().includes(q)
          );
        }

        // Parse to standardized format
        return filtered.map((opp) => parseOpportunityToJobData(opp));
      } catch (error) {
        console.error("Error searching Current-RMS jobs:", error);
        throw error;
      }
    }),

  getJobDetails: protectedProcedure
    .input(z.object({ jobId: z.string() }))
    .query(async ({ input }) => {
      try {
        // Check cache first
        const cached = await getCachedJob(input.jobId);
        if (cached && cached.expiresAt && new Date(cached.expiresAt) > new Date()) {
          return cached;
        }

        // Fetch from Current-RMS
        const opp = await fetchCurrentRmsOpportunityById(input.jobId);
        if (!opp) {
          throw new Error("Job not found");
        }

        const jobData = parseOpportunityToJobData(opp);

        // Cache the result
        await cacheJobData({
          currentRmsJobId: jobData.id,
          jobNumber: jobData.jobNumber,
          jobTitle: jobData.jobTitle,
          clientName: jobData.clientName,
          loadDate: jobData.loadDate,
          loadTime: jobData.loadTime,
          status: jobData.status,
          rawData: JSON.stringify(opp),
        });

        return jobData;
      } catch (error) {
        console.error("Error fetching job details:", error);
        throw error;
      }
    }),

  testConnection: protectedProcedure.query(async () => {
    try {
      const success = await testCurrentRmsConnection();
      return { success };
    } catch (error) {
      console.error("Connection test error:", error);
      return { success: false, error: String(error) };
    }
  }),
});
