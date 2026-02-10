import { systemRouter } from "./_core/systemRouter";
import { router } from "./_core/trpc";
import { warehouseRouter } from "./warehouseRouter";
import { authRouter } from "./authRouter";

export const appRouter = router({
  system: systemRouter,
  auth: authRouter,
  warehouse: warehouseRouter,
});

export type AppRouter = typeof appRouter;
