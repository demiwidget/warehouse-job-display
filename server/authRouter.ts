import { z } from "zod";
import { publicProcedure, router } from "./_core/trpc";
import {
  authenticateAdminUser,
  createAdminUser,
  hasAdminUsers,
  getAdminUserByUsername,
} from "./authLocal";
import { TRPCError } from "@trpc/server";

const SESSION_COOKIE_NAME = "warehouse_admin_session";

export const authRouter = router({
  /**
   * Check if any admin users exist (for setup flow)
   */
  hasAdminUsers: publicProcedure.query(async () => {
    return hasAdminUsers();
  }),

  /**
   * Register a new admin user (only if no users exist)
   */
  register: publicProcedure
    .input(
      z.object({
        username: z.string().min(3).max(255),
        password: z.string().min(6),
        email: z.string().email().optional(),
      })
    )
    .mutation(async ({ input, ctx }) => {
      // Only allow registration if no admin users exist
      const hasUsers = await hasAdminUsers();
      if (hasUsers) {
        throw new TRPCError({
          code: "FORBIDDEN",
          message: "Admin user already exists. Use login instead.",
        });
      }

      try {
        const user = await createAdminUser({
          username: input.username,
          password: input.password,
          email: input.email,
        });

        // Set session cookie
        ctx.res.cookie(SESSION_COOKIE_NAME, String(user.id), {
          path: "/",
          httpOnly: true,
          sameSite: "lax",
          maxAge: 2592000000, // 30 days in milliseconds
        });

        return {
          success: true,
          user: {
            id: user.id,
            username: user.username,
            email: user.email,
          },
        };
      } catch (error: any) {
        if (error.message?.includes("Duplicate entry")) {
          throw new TRPCError({
            code: "CONFLICT",
            message: "Username already exists",
          });
        }
        throw error;
      }
    }),

  /**
   * Login with username and password
   */
  login: publicProcedure
    .input(
      z.object({
        username: z.string(),
        password: z.string(),
      })
    )
    .mutation(async ({ input, ctx }) => {
      const user = await authenticateAdminUser(input.username, input.password);

      if (!user) {
        throw new TRPCError({
          code: "UNAUTHORIZED",
          message: "Invalid username or password",
        });
      }

      // Set session cookie
      ctx.res.cookie(SESSION_COOKIE_NAME, String(user.id), {
        path: "/",
        httpOnly: true,
        sameSite: "lax",
        maxAge: 2592000000, // 30 days in milliseconds
      });

      return {
        success: true,
        user: {
          id: user.id,
          username: user.username,
          email: user.email,
        },
      };
    }),

  /**
   * Check current session
   */
  me: publicProcedure.query(async ({ ctx }) => {
    const cookies = ctx.req.headers.cookie || "";
    const sessionId = cookies
      .split(";")
      .find((c) => c.trim().startsWith(SESSION_COOKIE_NAME))
      ?.split("=")[1];

    if (!sessionId) {
      return null;
    }

    // In a real app, you'd look up the user by ID
    // For now, we just verify the session exists
    return { id: parseInt(sessionId), authenticated: true };
  }),

  /**
   * Logout
   */
  logout: publicProcedure.mutation(({ ctx }) => {
    ctx.res.clearCookie(SESSION_COOKIE_NAME, {
      path: "/",
      httpOnly: true,
      sameSite: "lax",
      maxAge: 0,
    });
    return { success: true };
  }),
});
