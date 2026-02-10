import { int, mysqlEnum, mysqlTable, text, timestamp, varchar } from "drizzle-orm/mysql-core";

/**
 * Core user table backing auth flow.
 * Extend this file with additional tables as your product grows.
 * Columns use camelCase to match both database fields and generated types.
 */
export const users = mysqlTable("users", {
  /**
   * Surrogate primary key. Auto-incremented numeric value managed by the database.
   * Use this for relations between tables.
   */
  id: int("id").autoincrement().primaryKey(),
  /** Manus OAuth identifier (openId) returned from the OAuth callback. Unique per user. */
  openId: varchar("openId", { length: 64 }).notNull().unique(),
  name: text("name"),
  email: varchar("email", { length: 320 }),
  loginMethod: varchar("loginMethod", { length: 64 }),
  role: mysqlEnum("role", ["user", "admin"]).default("user").notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  lastSignedIn: timestamp("lastSignedIn").defaultNow().notNull(),
});

export type User = typeof users.$inferSelect;
export type InsertUser = typeof users.$inferInsert;

/**
 * Warehouse areas (e.g., "Loading Bay A", "Dispatch Zone 1")
 */
export const warehouseAreas = mysqlTable("warehouse_areas", {
  id: int("id").autoincrement().primaryKey(),
  name: varchar("name", { length: 255 }).notNull(),
  description: text("description"),
  displayName: varchar("displayName", { length: 255 }).notNull(),
  isActive: int("isActive").default(1).notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
});

export type WarehouseArea = typeof warehouseAreas.$inferSelect;
export type InsertWarehouseArea = typeof warehouseAreas.$inferInsert;

/**
 * Mapping between warehouse areas and Current-RMS jobs/opportunities
 * Allows multiple jobs per area and tracks which jobs should display
 */
export const areaJobMappings = mysqlTable("area_job_mappings", {
  id: int("id").autoincrement().primaryKey(),
  areaId: int("areaId").notNull(),
  currentRmsJobId: varchar("currentRmsJobId", { length: 255 }).notNull(),
  currentRmsJobNumber: varchar("currentRmsJobNumber", { length: 255 }).notNull(),
  isActive: int("isActive").default(1).notNull(),
  sortOrder: int("sortOrder").default(0).notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
});

export type AreaJobMapping = typeof areaJobMappings.$inferSelect;
export type InsertAreaJobMapping = typeof areaJobMappings.$inferInsert;

/**
 * Display settings for each area screen
 */
export const displaySettings = mysqlTable("display_settings", {
  id: int("id").autoincrement().primaryKey(),
  areaId: int("areaId").notNull().unique(),
  refreshIntervalSeconds: int("refreshIntervalSeconds").default(30).notNull(),
  theme: mysqlEnum("theme", ["light", "dark"]).default("dark").notNull(),
  showLoadTime: int("showLoadTime").default(1).notNull(),
  showJobNumber: int("showJobNumber").default(1).notNull(),
  showJobTitle: int("showJobTitle").default(1).notNull(),
  fontSize: mysqlEnum("fontSize", ["small", "medium", "large", "xlarge"]).default("xlarge").notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
});

export type DisplaySettings = typeof displaySettings.$inferSelect;
export type InsertDisplaySettings = typeof displaySettings.$inferInsert;

/**
 * Cache of Current-RMS job data to reduce API calls
 */
export const jobCache = mysqlTable("job_cache", {
  id: int("id").autoincrement().primaryKey(),
  currentRmsJobId: varchar("currentRmsJobId", { length: 255 }).notNull().unique(),
  jobNumber: varchar("jobNumber", { length: 255 }).notNull(),
  jobTitle: text("jobTitle"),
  clientName: varchar("clientName", { length: 255 }),
  loadDate: timestamp("loadDate"),
  loadTime: varchar("loadTime", { length: 50 }),
  status: varchar("status", { length: 100 }),
  rawData: text("rawData"),
  lastFetched: timestamp("lastFetched").defaultNow().notNull(),
  expiresAt: timestamp("expiresAt"),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
});

export type JobCache = typeof jobCache.$inferSelect;
export type InsertJobCache = typeof jobCache.$inferInsert;

/**
 * Admin users for local authentication (username/password)
 */
export const adminUsers = mysqlTable("admin_users", {
  id: int("id").autoincrement().primaryKey(),
  username: varchar("username", { length: 255 }).notNull().unique(),
  email: varchar("email", { length: 320 }),
  passwordHash: varchar("passwordHash", { length: 255 }).notNull(),
  isActive: int("isActive").default(1).notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
});

export type AdminUser = typeof adminUsers.$inferSelect;
export type InsertAdminUser = typeof adminUsers.$inferInsert;