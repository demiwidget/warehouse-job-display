import { scryptSync, randomBytes, timingSafeEqual } from "crypto";
import { eq } from "drizzle-orm";
import { adminUsers, type AdminUser, type InsertAdminUser } from "../drizzle/schema";
import { getDb } from "./db";

/**
 * Hash a password using scrypt
 */
export function hashPassword(password: string): string {
  const salt = randomBytes(16).toString("hex");
  const hash = scryptSync(password, salt, 64).toString("hex");
  return `${salt}:${hash}`;
}

/**
 * Verify a password against a hash
 */
export function verifyPassword(password: string, hash: string): boolean {
  try {
    const [salt, storedHash] = hash.split(":");
    if (!salt || !storedHash) return false;

    const computedHash = scryptSync(password, salt, 64).toString("hex");
    return timingSafeEqual(Buffer.from(computedHash), Buffer.from(storedHash));
  } catch (error) {
    return false;
  }
}

/**
 * Create a new admin user
 */
export async function createAdminUser(data: {
  username: string;
  password: string;
  email?: string;
}): Promise<AdminUser> {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  const passwordHash = hashPassword(data.password);

  await db.insert(adminUsers).values({
    username: data.username,
    email: data.email,
    passwordHash,
    isActive: 1,
  });

  const result = await db
    .select()
    .from(adminUsers)
    .where(eq(adminUsers.username, data.username))
    .limit(1);

  if (result.length === 0) throw new Error("Failed to create admin user");
  return result[0];
}

/**
 * Get admin user by username
 */
export async function getAdminUserByUsername(username: string): Promise<AdminUser | null> {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  const result = await db
    .select()
    .from(adminUsers)
    .where(eq(adminUsers.username, username))
    .limit(1);

  return result.length > 0 ? result[0] : null;
}

/**
 * Authenticate admin user with username and password
 */
export async function authenticateAdminUser(
  username: string,
  password: string
): Promise<AdminUser | null> {
  const user = await getAdminUserByUsername(username);
  if (!user) return null;

  if (!user.isActive) return null;

  const isValid = verifyPassword(password, user.passwordHash);
  if (!isValid) return null;

  return user;
}

/**
 * Check if any admin users exist
 */
export async function hasAdminUsers(): Promise<boolean> {
  const db = await getDb();
  if (!db) return false;

  const result = await db.select().from(adminUsers).limit(1);
  return result.length > 0;
}
